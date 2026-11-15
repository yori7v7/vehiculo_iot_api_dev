"""55-J: no Internet/AWS/physical outputs; only controlled offline ASGI gating."""
from __future__ import annotations

import asyncio

import pytest

from app.public_control.kv_kx_virtual_bridge_lab import HOTSPOT_PATH
from scripts.servidor_55i_kv_kx_esp_lab import WssOnlyFromESP
from scripts.servidor_55j_reconexion_esp_lab import DisconnectGate

HOST = "172.22.82.209:8443"
ESP = "172.22.82.5"


class Spy:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1000})
        if scope["type"] == "http":
            raise AssertionError("HTTP escaped WSS-only perimeter")


async def invoke(gate, kind, peer=ESP, path=HOTSPOT_PATH):
    received = []
    scope = {
        "type": kind, "client": (peer, 56000), "path": path,
        "query_string": b"", "headers": [(b"host", HOST.encode("ascii"))],
    }

    async def recv():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(item):
        received.append(item)

    await gate(scope, recv, send)
    return received


def test_55j_pause_closes_websocket_before_app():
    spy = Spy()
    gate = DisconnectGate(WssOnlyFromESP(spy, esp_ip=ESP, host=HOST))
    gate.allow_wss = False
    got = asyncio.run(invoke(gate, "websocket"))
    assert got == [{"type": "websocket.close", "code": 1008}]
    assert spy.calls == []


def test_55j_reopen_only_exact_esp_path_not_any_http():
    spy = Spy()
    gate = DisconnectGate(WssOnlyFromESP(spy, esp_ip=ESP, host=HOST))
    gate.allow_wss = False
    gate.allow_wss = True
    got = asyncio.run(invoke(gate, "websocket"))
    assert got == [{"type": "websocket.close", "code": 1000}]
    assert len(spy.calls) == 1

    out = asyncio.run(invoke(gate, "http", path="/admin/vehiculos/1/control-publico/solicitudes"))
    assert out[0]["type"] == "http.response.start"
    assert out[0]["status"] == 404
    assert len(spy.calls) == 1


def test_55j_does_not_bypass_55i_peer_filter():
    spy = Spy()
    gate = DisconnectGate(WssOnlyFromESP(spy, esp_ip=ESP, host=HOST))
    got = asyncio.run(invoke(gate, "websocket", peer="172.22.82.6"))
    assert got == [{"type": "websocket.close", "code": 1008}]
    assert spy.calls == []
