"""Pruebas del servidor 55-H hotspot: TLS/HMAC virtual, sin ESP ni AWS."""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceSession, TX_CONTEXT, decoded, device_auth_reply, encoded,
    verify_server_auth,
)
from app.device_channel.command_wire import CommandWire, DeviceAck
from scripts import preparar_55h_hotspot_seguro as generator
from scripts.servidor_55h_hotspot_seguro import (
    WSS_PATH, create_55h_hotspot_lab_app, read_private_identity,
)

IP = "172.22.82.209"
DEVICE_IP = "172.22.82.5"


@pytest.fixture
def private(tmp_path, monkeypatch):
    sketch = tmp_path / "sketch"
    sketch.mkdir()
    (sketch / "Excavadora_IoT_55H_Hotspot_Seguro.ino").write_text(
        "// CI: sin firmware real", encoding="utf-8"
    )
    monkeypatch.setattr(generator, "SKETCH", sketch)
    monkeypatch.setattr(generator, "PRIVATE", sketch / "private")
    generator.prepare(IP, "CLAVE-CI-55H-123", ci_fixture=True)
    return sketch / "private"


def make_wire(key, ws):
    challenge = ws.receive_json()
    assert challenge["tipo"] == "desafio_dispositivo_lab"
    boot = b"B" * 16
    nonce = b"N" * 16
    answer = device_auth_reply(key, challenge, boot=boot, nonce_device=nonce)
    ws.send_json(answer)
    confirmation = ws.receive_json()
    telem_key = verify_server_auth(key, challenge, answer, confirmation)
    binding = (
        (1).to_bytes(4, "big") + decoded(challenge["desafio"], 32) +
        boot + nonce + decoded(confirmation["sesion"], 16)
    )
    cmd_key = hmac.new(key, TX_CONTEXT + binding, sha256).digest()
    return CommandWire(DeviceSession(
        1, confirmation["sesion"], encoded(boot), encoded(nonce),
        cmd_key, telem_key, binding,
    ))


def reply_virtual(ws, wire, expected):
    frame = ws.receive_json()
    order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
    assert order.code == expected
    assert order.duration_ms == (250 if expected == 9 else 0)
    for phase, neutral in ((1, False), (2, True)):
        if phase == 2 and expected == 9:
            time.sleep(.25)
        ack = DeviceAck(
            order.vehicle_id, order.session_id, order.operation_id,
            order.generation, order.epoch, order.sequence,
            int(time.time() * 1000), phase, neutral,
        )
        ws.send_json(wire.sign_ack(ack))


def test_signed_wss_55h_hotspot_diagnostic_full_flow(private):
    cfg, key = read_private_identity(private)
    assert cfg["physical_enabled"] is False
    app = create_55h_hotspot_lab_app(private)
    with TestClient(app, base_url=f"https://{IP}:8443",
                    client=(DEVICE_IP, 51234)) as client:
        status = client.get("/55h/estado").json()
        assert status["canDrive"] is False
        assert status["control_fisico"] is False
        with client.websocket_connect(
            WSS_PATH, headers={"Host": f"{IP}:8443"}
        ) as ws:
            wire = make_wire(key, ws)
            reply_virtual(ws, wire, 9)
            reply_virtual(ws, wire, 0)
            final = ws.receive_json()
            assert final["tipo"] == "prueba_contrato_terminada"
            assert final["parada_fisica_verificada"] is False
            assert final["movimiento"] == 9
            assert final["detener"] == 0
    assert app.state.active_device is False


@pytest.mark.parametrize("host,origin,device_ip", [
    ("host.evil", None, DEVICE_IP),
    (f"{IP}:8443", "https://yori7v7.github.io", DEVICE_IP),
    (f"{IP}:8443", None, "8.8.8.8"),
    (f"{IP}:8443", None, "192.168.1.100"),
])
def test_peer_guards_fail_closed(private, host, origin, device_ip):
    app = create_55h_hotspot_lab_app(private)
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    with TestClient(app, base_url=f"https://{IP}:8443",
                    client=(device_ip, 51000)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(WSS_PATH, headers=headers):
                pass
    assert app.state.active_device is False


def test_physical_flag_and_wrong_key_file_rejected(private):
    path = private / "settings.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["physical_enabled"] = True
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError, match="NO-GO"):
        create_55h_hotspot_lab_app(private)

    obj["physical_enabled"] = False
    path.write_text(json.dumps(obj), encoding="utf-8")
    (private / "device-key.bin").write_bytes(b"bad")
    with pytest.raises(ValueError, match="NO-GO"):
        read_private_identity(private)
