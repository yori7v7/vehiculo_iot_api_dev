"""Pruebas de autenticación WSS SOLO de laboratorio y dispositivo virtual."""
from __future__ import annotations

from dataclasses import dataclass
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceLabHandshake, DeviceTelemetryVerifier, LabDeviceProtocolError,
    device_auth_reply, verify_server_auth, make_virtual_telemetry,
    encoded, decoded,
)
from app.device_channel.ws_lab import DeviceLabRegistry, router


KEY = bytes(range(32))  # SOLO PRUEBAS: jamás para un dispositivo real.
PATH = "/ws/dispositivos-lab/1"
HOST = {"Host": "127.0.0.1"}


@dataclass
class LabSettings:
    app_env: str = "development"
    device_lab_enabled: bool = True
    device_lab_vehicle_id: int = 1
    device_lab_key: object = None


class FakeSecret:
    def __init__(self, raw):
        self.raw = raw

    def get_secret_value(self):
        return self.raw


def app(enabled=True, env="development"):
    a = FastAPI()
    a.state.device_lab_settings = LabSettings(
        app_env=env, device_lab_enabled=enabled,
        device_lab_key=FakeSecret(encoded(KEY)),
    )
    a.state.device_lab_registry = DeviceLabRegistry()
    a.include_router(router)
    return a


def connect_and_auth(ws, key=KEY, boot=b"b" * 16, device_nonce=b"d" * 16):
    challenge = ws.receive_json()
    reply = device_auth_reply(key, challenge, boot=boot, nonce_device=device_nonce)
    ws.send_json(reply)
    confirmed = ws.receive_json()
    return challenge, reply, confirmed


def test_nonce_codec_roundtrip_and_strict_canonical_length():
    data = b"a" * 32
    assert decoded(encoded(data), 32) == data
    for wrong in ("a"*42, "a"*44, "a"*43+"=", "/"*43, "A"*42+"B"):
        with pytest.raises(LabDeviceProtocolError):
            decoded(wrong, 32)


def test_handshake_is_challenge_bound_and_single_use():
    hs = DeviceLabHandshake(1, KEY, nonce=b"n"*32)
    challenge = hs.challenge
    reply = device_auth_reply(KEY, challenge, boot=b"b"*16, nonce_device=b"d"*16)
    session, confirmation = hs.verify(reply)
    assert confirmation["simulado"] is True
    device_rx_key = verify_server_auth(KEY, challenge, reply, confirmation)
    assert device_rx_key == session.telemetry_key
    with pytest.raises(LabDeviceProtocolError):
        hs.verify(reply)


@pytest.mark.parametrize("change", [
    lambda r: dict(r, vehiculo=2),
    lambda r: dict(r, prueba="0"*64),
    lambda r: dict(r, simulado=False),
    lambda r: dict(r, version=2),
    lambda r: dict(r, extra="yes"),
])
def test_wrong_auth_fails_closed(change):
    hs = DeviceLabHandshake(1, KEY)
    reply = device_auth_reply(KEY, hs.challenge, boot=b"b"*16, nonce_device=b"d"*16)
    with pytest.raises(LabDeviceProtocolError):
        hs.verify(change(reply))


def test_replay_from_old_challenge_rejected():
    a = DeviceLabHandshake(1, KEY, nonce=b"a"*32)
    b = DeviceLabHandshake(1, KEY, nonce=b"b"*32)
    old = device_auth_reply(KEY, a.challenge, boot=b"b"*16, nonce_device=b"d"*16)
    with pytest.raises(LabDeviceProtocolError):
        b.verify(old)


def test_telemetry_fails_for_replay_tamper_wrong_session_and_nonzero_output():
    hs = DeviceLabHandshake(1, KEY)
    reply = device_auth_reply(KEY, hs.challenge, boot=b"b"*16, nonce_device=b"d"*16)
    session, _ = hs.verify(reply)
    v = DeviceTelemetryVerifier(session)
    frame = make_virtual_telemetry(session.telemetry_key, session.session_id, 1)
    assert v.verify(frame) == 1
    with pytest.raises(LabDeviceProtocolError):
        v.verify(frame)
    frame2 = make_virtual_telemetry(session.telemetry_key, session.session_id, 2)
    for change in (dict(frame2, firma="0"*64), dict(frame2, codigo_salida=1),
                   dict(frame2, sesion=encoded(b"x"*16)), dict(frame2, simulado=False),
                   dict(frame2, contador=3)):
        with pytest.raises(LabDeviceProtocolError):
            v.verify(change)
    assert v.verify(frame2) == 2
    assert v.safe_for_physical_control is False


def test_wss_handshake_auth_telemetry_and_signed_reply():
    a = app()
    with TestClient(a, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as client:
        with client.websocket_connect(PATH, headers=HOST) as ws:
            challenge, reply, confirmed = connect_and_auth(ws)
            key = verify_server_auth(KEY, challenge, reply, confirmed)
            assert a.state.device_lab_registry.is_active(1)
            ws.send_json(make_virtual_telemetry(key, confirmed["sesion"], 1))
            answer = ws.receive_json()
            assert answer["tipo"] == "telemetria_recibida_lab"
            assert answer["contador"] == 1
            assert answer["simulado"] is True
            assert len(answer["firma"]) == 64
    assert not a.state.device_lab_registry.is_active(1)


@pytest.mark.parametrize("enabled,env,host,path,origin", [
    (False, "development", "127.0.0.1", PATH, None),
    (True, "production", "127.0.0.1", PATH, None),
    (True, "development", "198.51.100.9", PATH, None),
    (True, "development", "127.0.0.1", "/ws/dispositivos-lab/2", None),
    (True, "development", "127.0.0.1", PATH, "https://yori7v7.github.io"),
    (True, "development", "127.0.0.1", PATH+"?token=123", None),
])
def test_wss_rejects_nonlocal_or_disabled(enabled, env, host, path, origin):
    a = app(enabled=enabled, env=env)
    with TestClient(a, base_url="http://127.0.0.1", client=(host, 4999)) as c:
        extra = {"headers": {"Origin": origin, "Host": "127.0.0.1"}} if origin else {"headers": HOST}
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(path, **extra):
                pass


def test_wss_does_not_accept_bad_proof():
    with TestClient(app(), base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HOST) as ws:
            challenge = ws.receive_json()
            reply = device_auth_reply(KEY, challenge, boot=b"b"*16, nonce_device=b"d"*16)
            reply["prueba"] = "0"*64
            ws.send_json(reply)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_wss_rejects_duplicate_telemetry_and_releases_lease():
    a = app()
    with TestClient(a, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HOST) as ws:
            challenge, reply, confirm = connect_and_auth(ws)
            key = verify_server_auth(KEY, challenge, reply, confirm)
            frame = make_virtual_telemetry(key, confirm["sesion"], 1)
            ws.send_json(frame)
            assert ws.receive_json()["contador"] == 1
            ws.send_json(frame)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert not a.state.device_lab_registry.is_active(1)


def test_second_device_rejected_while_first_is_active():
    a = app()
    with TestClient(a, base_url="http://127.0.0.1", client=("127.0.0.1", 5050)) as c:
        with c.websocket_connect(PATH, headers=HOST) as first:
            connect_and_auth(first)
            with pytest.raises(WebSocketDisconnect):
                with c.websocket_connect(PATH, headers=HOST):
                    pass
            assert a.state.device_lab_registry.is_active(1)
    assert not a.state.device_lab_registry.is_active(1)
