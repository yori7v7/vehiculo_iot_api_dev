"""Recorrido WSS completo HMAC sin red, sin AWS y sin actuadores."""
import hmac
from hashlib import sha256
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceSession, TX_CONTEXT, RX_CONTEXT, decoded, encoded,
    device_auth_reply, verify_server_auth,
)
from app.device_channel.command_wire import (
    CommandWire, DeviceAck, WireProtocolError,
)
from app.device_channel.command_lab_ws import router
from app.device_channel.ws_lab import DeviceLabRegistry


KEY = bytes(range(32))
HEADERS = {"Host": "127.0.0.1"}
PATH = "/ws/dispositivos-lab/1/contrato"


class Secret:
    def get_secret_value(self):
        return encoded(KEY)


class Settings:
    app_env = "development"
    device_lab_enabled = True
    device_lab_vehicle_id = 1
    device_lab_key = Secret()


def fixture(enabled=True):
    a = FastAPI()
    a.state.device_lab_settings = Settings()
    a.state.device_lab_registry = DeviceLabRegistry()
    a.state.device_lab_settings.device_lab_enabled = enabled
    a.include_router(router)
    return a


def auth(ws):
    challenge = ws.receive_json()
    boot, nonce = b"b" * 16, b"n" * 16
    reply = device_auth_reply(KEY, challenge, boot=boot, nonce_device=nonce)
    ws.send_json(reply)
    confirmation = ws.receive_json()
    rx = verify_server_auth(KEY, challenge, reply, confirmation)
    body = (1).to_bytes(4, "big") + decoded(challenge["desafio"], 32) \
        + boot + nonce + decoded(confirmation["sesion"], 16)
    tx = hmac.new(KEY, TX_CONTEXT + body, sha256).digest()
    assert hmac.compare_digest(rx, hmac.new(KEY, RX_CONTEXT + body, sha256).digest())
    return CommandWire(DeviceSession(1, confirmation["sesion"], encoded(boot),
                                     encoded(nonce), tx, rx, body))


def respond(ws, wire, *, expect_code, expect_epoch, expect_sequence):
    frame = ws.receive_json()
    assert frame["tipo"] == "orden_dispositivo_v1"
    order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
    assert (order.code, order.epoch, order.sequence) == (
        expect_code, expect_epoch, expect_sequence,
    )
    for phase, neutral in ((1, False), (2, True)):
        ack = DeviceAck(order.vehicle_id, order.session_id, order.operation_id,
                        order.generation, order.epoch, order.sequence,
                        int(time.time() * 1000), phase, neutral)
        ws.send_json(wire.sign_ack(ack))
    return order


def test_virtual_websocket_8_direction_then_stop_with_signed_acks():
    app = fixture()
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HEADERS) as ws:
            wire = auth(ws)
            drive = respond(ws, wire, expect_code=9, expect_epoch=1, expect_sequence=1)
            stop = respond(ws, wire, expect_code=0, expect_epoch=2, expect_sequence=2)
            assert drive.operation_id != stop.operation_id
            assert drive.duration_ms == 250 and stop.duration_ms == 0
            end = ws.receive_json()
            assert end == {
                "tipo": "prueba_contrato_terminada", "simulado": True,
                "movimiento": 9, "detener": 0, "parada_fisica_verificada": False,
            }
    assert not app.state.device_lab_registry.is_active(1)


def test_bad_signed_ack_fails_closed_and_releases():
    app = fixture()
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HEADERS) as ws:
            wire = auth(ws)
            frame = ws.receive_json()
            order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
            wrong = DeviceAck(order.vehicle_id, order.session_id, str(uuid4()),
                              order.generation, order.epoch, order.sequence,
                              int(time.time() * 1000), 1, False)
            ws.send_json(wire.sign_ack(wrong))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert not app.state.device_lab_registry.is_active(1)


def test_repeated_phase_fails_closed():
    app = fixture()
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HEADERS) as ws:
            wire = auth(ws)
            order = wire.verify_order(ws.receive_json(), now_ms=int(time.time() * 1000))
            ack = DeviceAck(order.vehicle_id, order.session_id, order.operation_id,
                            order.generation, order.epoch, order.sequence,
                            int(time.time() * 1000), 1, False)
            packet = wire.sign_ack(ack)
            ws.send_json(packet)
            ws.send_json(packet)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


@pytest.mark.parametrize("path,enabled,host,origin", [
    (PATH, False, "127.0.0.1", None),
    (PATH, True, "198.51.100.10", None),
    ("/ws/dispositivos-lab/2/contrato", True, "127.0.0.1", None),
    (PATH + "?key=test", True, "127.0.0.1", None),
    (PATH, True, "127.0.0.1", "https://yori7v7.github.io"),
])
def test_denies_unapproved_context(path, enabled, host, origin):
    app = fixture(enabled)
    with TestClient(app, base_url="http://127.0.0.1", client=(host, 5000)) as c:
        headers = dict(HEADERS)
        if origin:
            headers["Origin"] = origin
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(path, headers=headers) as ws:
                ws.receive_json()
