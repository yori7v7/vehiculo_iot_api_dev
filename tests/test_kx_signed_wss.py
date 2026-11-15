"""K-X: conexión WSS AUTENTICADA al mismo ASGI; solo dispositivo simulado.

Ninguna prueba abre puertos, usa ESP/RDS/AWS ni habilita salidas físicas.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import hmac
import secrets
import struct
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.device_channel.authenticated_lab import (
    BOOT_LEN, NONCE_LEN, SESSION_LEN, TX_CONTEXT, decoded,
    device_auth_reply, verify_server_auth,
)
from app.device_channel.command_wire import (
    CommandWire, DeviceAck, PHASE_NEUTRAL, PHASE_RECEIVED,
)
from app.main import create_app
from app.public_control.kx_signed_wss import KXDiagnosticWSSHub, PATH

HOST = "https://100-30-4-62.nip.io"
ORIGIN = "https://yori7v7.github.io"
GUEST = "/publico/vehiculos/1/solicitudes"
ACTION = GUEST + "/verificar-accion"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
KEY = "KX-PRUEBA-" + "X" * 58


@pytest.fixture
def env(tmp_path, monkeypatch):
    device_key = secrets.token_bytes(32)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(tmp_path / "kx.sqlite3"))
    monkeypatch.setenv("CONTROL_PUBLICO_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_SIMULATION", "false")
    monkeypatch.setenv("DEVICE_LAB_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    app.state.kx_diag_hub = KXDiagnosticWSSHub(device_key)
    yield app, device_key
    get_settings.cache_clear()


def make_turn(client):
    browser = secrets.token_urlsafe(32)
    response = client.post(GUEST, headers={
        "Origin": ORIGIN,
        "Idempotency-Key": secrets.token_urlsafe(32),
        "X-Browser-Proposal": browser,
    })
    assert response.status_code == 201, response.text
    rid = response.json()["request_id"]
    admin = {"Origin": ORIGIN, "X-API-Key": KEY}
    assert client.post(ADMIN + "/supervision", headers=admin).status_code == 200
    response = client.post(
        ADMIN + f"/{rid}/aprobar", headers=admin,
        json={"modo": "timed", "segundos": 120},
    )
    assert response.status_code == 200, response.text
    return browser, admin


def do_action(client, browser, code=9):
    return client.post(ACTION, headers={
        "Origin": ORIGIN, "X-Browser-Session": browser,
    }, json={"codigo": code, "duracion_ms": 250})


def handshake(ws, key):
    challenge = ws.receive_json()
    boot = secrets.token_bytes(BOOT_LEN)
    nonce = secrets.token_bytes(BOOT_LEN)
    reply = device_auth_reply(key, challenge, boot=boot, nonce_device=nonce)
    ws.send_json(reply)
    confirmation = ws.receive_json()
    telemetry_key = verify_server_auth(key, challenge, reply, confirmation)
    context = (
        struct.pack(">I", 1) + decoded(challenge["desafio"], NONCE_LEN)
        + boot + nonce + decoded(confirmation["sesion"], SESSION_LEN)
    )
    command_key = hmac.new(key, TX_CONTEXT + context, sha256).digest()
    return CommandWire(SimpleNamespace(
        vehicle_id=1, session_id=confirmation["sesion"],
        command_key=command_key, telemetry_key=telemetry_key,
    ))


def reply_with_signed_acks(ws, wire):
    signed = ws.receive_json()
    order = wire.verify_order(signed, now_ms=int(time.time() * 1000))
    for phase, neutral in ((PHASE_RECEIVED, False), (PHASE_NEUTRAL, True)):
        ack = DeviceAck(
            1, order.session_id, order.operation_id, order.generation,
            order.epoch, order.sequence, int(time.time() * 1000), phase, neutral,
        )
        ws.send_json(wire.sign_ack(ack))
    return order


def test_same_process_kx_lease_to_signed_wss_and_virtual_stop(env):
    app, key = env
    with TestClient(app, base_url=HOST) as client:
        browser, admin = make_turn(client)

        # No aceptar control aunque el ticket esté aprobado si no hay WSS.
        assert do_action(client, browser).status_code == 503
        with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH) as ws:
            wire = handshake(ws, key)
            initial = reply_with_signed_acks(ws, wire)
            assert initial.code == 0

            for _ in range(100):
                if app.state.kx_diag_hub.ready:
                    break
                time.sleep(.01)
            assert app.state.kx_diag_hub.ready

            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(do_action, client, browser, 9)
                move = reply_with_signed_acks(ws, wire)
                stop = reply_with_signed_acks(ws, wire)
                result = future.result(timeout=6)
            assert move.code == 9
            assert move.duration_ms == 250
            assert stop.code == 0
            assert result.status_code == 200, result.text
            assert result.json()["despacho_wss"] is True
            assert result.json()["neutral_virtual_reportado"] is True
            assert result.json()["control_fisico"] is False
            assert result.json()["canDrive"] is False

            # Revocar invalida primero el permiso. El segundo STOP firmado
            # tampoco acredita inmovilidad mecánica.
            with ThreadPoolExecutor(max_workers=1) as workers:
                revoked = workers.submit(client.post, ADMIN + "/revocar", headers=admin)
                stop_revoke = reply_with_signed_acks(ws, wire)
                response = revoked.result(timeout=6)
            assert stop_revoke.code == 0
            assert response.status_code == 200, response.text
            assert response.json()["neutral_virtual_reportado"] is True
            assert response.json()["stop_fisico_confirmado"] is False
            assert do_action(client, browser).status_code == 403


def test_no_injected_diagnostic_hub_has_no_wss_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(tmp_path / "kx-off.sqlite3"))
    monkeypatch.setenv("DEVICE_LAB_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_SIMULATION", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, base_url=HOST) as client:
        assert app.state.kx_diag_hub is None
        with pytest.raises(Exception):
            with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH):
                pass
    get_settings.cache_clear()
