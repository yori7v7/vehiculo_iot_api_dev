"""Lab-only shared-authority integration; no real network, AWS, RDS or motors."""
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

from app.device_channel.authenticated_lab import (
    BOOT_LEN, NONCE_LEN, SESSION_LEN, TX_CONTEXT, decoded,
    device_auth_reply, verify_server_auth,
)
from app.device_channel.command_wire import (
    CommandWire, DeviceAck, PHASE_NEUTRAL, PHASE_RECEIVED,
)
from app.public_control.kv_kx_virtual_bridge_lab import (
    LOCAL_ACTION, create_kv_kx_virtual_lab_app,
)
from app.public_control.kx_signed_wss import PATH

ADMIN = "TEST-VIRTUAL-ADMIN-" + "A" * 50
PROXY = "TEST-VIRTUAL-PROXY-" + "P" * 50
DEVICE = bytes(range(32))  # Published fixture only, NEVER a device secret.
BASE = "https://100-30-4-62.nip.io"
GUEST = "/publico/vehiculos/1/solicitudes"
INBOX = "/admin/vehiculos/1/control-publico/solicitudes"
HEAD = {
    "Host": "100-30-4-62.nip.io",
    "Origin": "https://yori7v7.github.io",
    "X-Admission-Proxy-Token": PROXY,
    "X-Admission-Client-IP": "8.8.8.8",
    "X-Admission-Scheme": "https",
}
AUTH = {**HEAD, "X-API-Key": ADMIN}


class Clock:
    def __init__(self):
        self.current = 1000.0

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += seconds


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv("KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only")
    clock = Clock()
    db = tmp_path / "bridge.sqlite3"

    def factory():
        return create_kv_kx_virtual_lab_app(db, ADMIN, PROXY, DEVICE, clock=clock)

    return factory, clock


def browser(app):
    return TestClient(app, base_url=BASE, client=("127.0.0.1", 54000))


def guest_request(client):
    secret = secrets.token_urlsafe(32)
    response = client.post(GUEST, headers={
        **HEAD, "Idempotency-Key": secrets.token_urlsafe(32),
        "X-Browser-Proposal": secret,
    })
    assert response.status_code == 201, response.text
    return secret, response.json()["request_id"]


def approve(client, request_id, *, supervised=False):
    assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200
    mode = {"modo": "supervised"} if supervised else {"modo": "timed", "segundos": 120}
    result = client.post(INBOX + f"/{request_id}/aprobar", headers=AUTH, json=mode)
    assert result.status_code == 200, result.text
    assert result.json()["canDrive"] is False


def action(client, secret, code=9, duration_ms=250, *, extra=None):
    return client.post(LOCAL_ACTION.replace("{id_vehiculo}", "1"), headers={
        **HEAD, "X-Browser-Session": secret, **(extra or {}),
    }, json={"codigo": code, "duracion_ms": duration_ms})


def authenticate(ws):
    challenge = ws.receive_json()
    boot, nonce = secrets.token_bytes(BOOT_LEN), secrets.token_bytes(BOOT_LEN)
    proof = device_auth_reply(DEVICE, challenge, boot=boot, nonce_device=nonce)
    ws.send_json(proof)
    confirmation = ws.receive_json()
    telemetry_key = verify_server_auth(DEVICE, challenge, proof, confirmation)
    binding = (struct.pack(">I", 1) + decoded(challenge["desafio"], NONCE_LEN) +
               boot + nonce + decoded(confirmation["sesion"], SESSION_LEN))
    command_key = hmac.new(DEVICE, TX_CONTEXT + binding, sha256).digest()
    return CommandWire(SimpleNamespace(vehicle_id=1,
        session_id=confirmation["sesion"], command_key=command_key,
        telemetry_key=telemetry_key))


def ack_two_phases(ws, wire):
    frame = ws.receive_json()
    order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
    for phase, neutral in ((PHASE_RECEIVED, False), (PHASE_NEUTRAL, True)):
        reply = DeviceAck(1, order.session_id, order.operation_id,
                          order.generation, order.epoch, order.sequence,
                          int(time.time() * 1000), phase, neutral)
        ws.send_json(wire.sign_ack(reply))
    return order


def wait_ready(app):
    for _ in range(200):
        if app.state.kx_diag_hub.ready:
            return
        time.sleep(.01)
    pytest.fail("WSS no inició la sesión virtual")


def test_opt_in_and_key_length_required(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.delenv("KX_KV_VIRTUAL_BRIDGE_LAB", raising=False)
    with pytest.raises(ValueError, match="laboratorio aislado"):
        create_kv_kx_virtual_lab_app(tmp_path / "x.db", ADMIN, PROXY, DEVICE)
    monkeypatch.setenv("KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only")
    with pytest.raises(ValueError, match="32 bytes"):
        create_kv_kx_virtual_lab_app(tmp_path / "x.db", ADMIN, PROXY, b"insegura")


def test_headers_schema_exclusivity_heartbeat_and_old_routes_fail_closed(lab):
    factory, clock = lab
    app = factory()
    with browser(app) as client:
        secret, rid = guest_request(client)
        url = LOCAL_ACTION.replace("{id_vehiculo}", "1")
        assert client.post(url, headers=HEAD, json={"codigo": 9, "duracion_ms": 250}).status_code == 401
        assert action(client, secret).status_code == 403  # Awaiting approval
        approve(client, rid)
        assert action(client, secret).status_code == 503  # No authenticated WSS
        assert action(client, secret, 16).status_code == 422
        assert action(client, secret, 9, 700).status_code == 422
        assert action(client, secret, 0, 250).status_code == 422
        assert action(client, secret, 0, 0).status_code == 503
        assert action(client, secret, extra={"X-API-Key": ADMIN}).status_code == 403
        assert action(client, secret, extra={"Host": "attacker.invalid"}).status_code == 403
        assert client.post(INBOX + "/revocar", headers={**HEAD, "X-API-Key": "INVALID"}).status_code == 403
        for path in ("/vehiculos/1/movimientos", "/ws/vehiculos/1", "/docs", "/openapi.json"):
            assert client.post(path, headers=AUTH).status_code == 404
        clock.advance(16)
        assert action(client, secret).status_code == 403  # Heartbeat lost
        assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200
        assert action(client, secret).status_code == 403  # Cannot resurrect lease


def test_restart_invalidates_approved_ticket_even_if_supervision_returns(lab):
    factory, _ = lab
    with browser(factory()) as client:
        secret, rid = guest_request(client)
        approve(client, rid)
        assert client.get(GUEST + "/estado", headers={**HEAD, "X-Browser-Session": secret}).json()["estado"] == "autorizado"
    with browser(factory()) as client:
        assert action(client, secret).status_code == 403
        assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200
        assert action(client, secret).status_code == 403


def test_signed_wss_virtual_move_and_admin_revoke(lab):
    factory, _ = lab
    app = factory()
    with browser(app) as client:
        secret, rid = guest_request(client)
        approve(client, rid)
        with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0  # Initial signed STOP
            wait_ready(app)
            assert client.post(INBOX + "/revocar", headers={**HEAD, "X-API-Key": "INVALID"}).status_code == 403
            assert app.state.kx_diag_hub.ready  # No hostile forced interlock
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(action, client, secret)
                move = ack_two_phases(ws, wire)
                stop = ack_two_phases(ws, wire)
                response = future.result(timeout=7)
            assert (move.code, move.duration_ms, stop.code) == (9, 250, 0)
            assert response.status_code == 200, response.text
            assert response.json()["motor"] is False
            assert response.json()["canDrive"] is False
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(client.post, INBOX + "/revocar", headers=AUTH)
                emergency_stop = ack_two_phases(ws, wire)
                revoked = future.result(timeout=7)
            assert emergency_stop.code == 0
            assert revoked.status_code == 200, revoked.text
            assert revoked.json()["stop_fisico_confirmado"] is False
            assert action(client, secret).status_code == 403


def test_inflight_revoke_preempts_next_virtual_dispatch(lab):
    factory, _ = lab
    app = factory()
    with browser(app) as client:
        secret, rid = guest_request(client)
        approve(client, rid)
        with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)
            with ThreadPoolExecutor(max_workers=2) as workers:
                moving = workers.submit(action, client, secret)
                first = ws.receive_json()
                move = wire.verify_order(first, now_ms=int(time.time() * 1000))
                assert move.code == 9
                revoking = workers.submit(client.post, INBOX + "/revocar", headers=AUTH)
                for _ in range(200):
                    if not app.state.kx_diag_hub.ready:
                        break
                    time.sleep(.005)
                assert not app.state.kx_diag_hub.ready  # Interlock set before lock.
                for phase, neutral in ((PHASE_RECEIVED, False), (PHASE_NEUTRAL, True)):
                    reply = DeviceAck(1, move.session_id, move.operation_id,
                                      move.generation, move.epoch, move.sequence,
                                      int(time.time() * 1000), phase, neutral)
                    ws.send_json(wire.sign_ack(reply))
                assert ack_two_phases(ws, wire).code == 0  # STOP of current action
                failed = moving.result(timeout=7)
                assert failed.status_code in (409, 503)
                assert ack_two_phases(ws, wire).code == 0  # Revocation STOP
                revoked = revoking.result(timeout=7)
            assert revoked.status_code == 200
            assert action(client, secret).status_code == 403
