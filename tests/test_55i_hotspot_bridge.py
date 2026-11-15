"""55-I: contrato K-V/K-X con firmware 55-H en hotspot, SOLO virtual CI.

TestClient no conecta el Wi-Fi real ni prueba GPIO. Claves y sesiones ficticias.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import hmac
import secrets
import struct
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    BOOT_LEN, NONCE_LEN, SESSION_LEN, TX_CONTEXT, decoded,
    device_auth_reply, verify_server_auth,
)
from app.device_channel.command_wire import CommandWire, DeviceAck
from app.public_control.kv_kx_virtual_bridge_lab import (
    HOTSPOT_PATH, LOCAL_ACTION, create_kv_kx_virtual_lab_app,
)

IP = "172.22.82.209"
DEVICE_IP = "172.22.82.5"
LAN_HOST = IP + ":8443"
PUBLIC = "https://100-30-4-62.nip.io"
ADMIN = "CI-ADMIN-" + "A" * 55
PROXY = "CI-PROXY-" + "P" * 55
DEVICE = bytes(range(32))  # Solamente ficticia, no desplegar.
INBOX = "/admin/vehiculos/1/control-publico/solicitudes"
GUEST = "/publico/vehiculos/1/solicitudes"
HEAD = {
    "Host": "100-30-4-62.nip.io",
    "Origin": "https://yori7v7.github.io",
    "X-Admission-Proxy-Token": PROXY,
    "X-Admission-Client-IP": "8.8.8.8",
    "X-Admission-Scheme": "https",
}
AUTH = {**HEAD, "X-API-Key": ADMIN}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv("KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only")
    return create_kv_kx_virtual_lab_app(
        tmp_path / "kv55i.sqlite3", ADMIN, PROXY, DEVICE,
        hotspot_host=LAN_HOST, hotspot_device_ip=DEVICE_IP,
    )


def auth_device(ws):
    challenge = ws.receive_json()
    assert challenge["tipo"] == "desafio_dispositivo_lab"
    boot = secrets.token_bytes(BOOT_LEN)
    nonce = secrets.token_bytes(BOOT_LEN)
    proof = device_auth_reply(DEVICE, challenge, boot=boot, nonce_device=nonce)
    ws.send_json(proof)
    confirm = ws.receive_json()
    tel = verify_server_auth(DEVICE, challenge, proof, confirm)
    binding = (struct.pack(">I", 1) + decoded(challenge["desafio"], NONCE_LEN)
               + boot + nonce + decoded(confirm["sesion"], SESSION_LEN))
    cmd = hmac.new(DEVICE, TX_CONTEXT + binding, sha256).digest()
    return CommandWire(SimpleNamespace(
        vehicle_id=1, session_id=confirm["sesion"],
        command_key=cmd, telemetry_key=tel,
    ))


def acknowledge(ws, wire):
    frame = ws.receive_json()
    order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
    for phase, neutral in ((1, False), (2, True)):
        ack = DeviceAck(
            1, order.session_id, order.operation_id,
            order.generation, order.epoch, order.sequence,
            int(time.time() * 1000), phase, neutral,
        )
        ws.send_json(wire.sign_ack(ack))
    return order


def wait_ready(app):
    for _ in range(200):
        if app.state.kx_diag_hub.ready:
            return
        time.sleep(.01)
    pytest.fail("hub virtual nunca quedó listo")


def test_hotspot_guard_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv("KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only")
    def build(host, peer):
        return create_kv_kx_virtual_lab_app(
            tmp_path / "refuse.sqlite3", ADMIN, PROXY, DEVICE,
            hotspot_host=host, hotspot_device_ip=peer,
        )
    for host, peer in [
        (LAN_HOST, None),
        (None, DEVICE_IP),
        ("8.8.8.8:8443", DEVICE_IP),
        (LAN_HOST, "8.8.8.8"),
        (LAN_HOST, IP),
        ("127.0.0.1:8443", DEVICE_IP),
        ("172.22.83.209:8443", DEVICE_IP),
    ]:
        with pytest.raises(ValueError, match="NO-GO"):
            build(host, peer)


def test_reject_wrong_peer_host_and_browser_origin(app):
    with TestClient(app, base_url=PUBLIC, client=("127.0.0.1", 5000)) as browser:
        for ip, host, headers in [
            ("172.22.82.6", LAN_HOST, {}),
            (DEVICE_IP, "attacker.invalid", {}),
            (DEVICE_IP, LAN_HOST, {"Origin": "https://evil.invalid"}),
        ]:
            device = TestClient(app, base_url=f"https://{IP}:8443", client=(ip, 54000))
            # Reutilizar el MISMO event loop ASGI que las solicitudes K-V.
            device.portal = browser.portal
            with pytest.raises(WebSocketDisconnect):
                with device.websocket_connect(HOTSPOT_PATH, headers={
                    "Host": host, **headers,
                }):
                    pass
    assert app.state.kx_diag_hub.ready is False


def test_kv_permission_to_real_55h_wire_contract_virtual_only(app):
    with TestClient(app, base_url=PUBLIC, client=("127.0.0.1", 54000)) as browser:
        secret = secrets.token_urlsafe(32)
        created = browser.post(GUEST, headers={
            **HEAD, "Idempotency-Key": secrets.token_urlsafe(32),
            "X-Browser-Proposal": secret,
        })
        assert created.status_code == 201, created.text
        rid = created.json()["request_id"]
        assert browser.post(INBOX + "/supervision", headers=AUTH).status_code == 200
        approved = browser.post(INBOX + f"/{rid}/aprobar", headers=AUTH,
                                json={"modo": "timed", "segundos": 120})
        assert approved.status_code == 200, approved.text
        endpoint = LOCAL_ACTION.replace("{id_vehiculo}", "1")
        def action():
            return browser.post(endpoint, headers={
                **HEAD, "X-Browser-Session": secret,
            }, json={"codigo": 9, "duracion_ms": 250})
        assert action().status_code == 503  # Device not yet authenticated

        device = TestClient(app, base_url=f"https://{IP}:8443",
                            client=(DEVICE_IP, 54001))
        # Un solo servidor ASGI/event loop, simulando distintos peers.
        device.portal = browser.portal
        with device.websocket_connect(HOTSPOT_PATH, headers={"Host": LAN_HOST}) as ws:
            wire = auth_device(ws)
            initial = acknowledge(ws, wire)
            assert initial.code == 0 and initial.duration_ms == 0
            wait_ready(app)
            with ThreadPoolExecutor(max_workers=1) as threads:
                future = threads.submit(action)
                move = acknowledge(ws, wire)
                stop = acknowledge(ws, wire)
                response = future.result(timeout=7)
            assert (move.code, move.duration_ms, stop.code) == (9, 250, 0)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["motor"] is False
            assert result["control_fisico"] is False
            assert result["canDrive"] is False
            assert result["stop_fisico_confirmado"] is False

            with ThreadPoolExecutor(max_workers=1) as threads:
                future = threads.submit(browser.post, INBOX + "/revocar", headers=AUTH)
                emergency = acknowledge(ws, wire)
                revoked = future.result(timeout=7)
            assert emergency.code == 0
            assert revoked.status_code == 200, revoked.text
            assert action().status_code == 403
