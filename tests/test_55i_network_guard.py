"""55-I network gateway denies all HTTP and untrusted WebSocket peers."""
from __future__ import annotations

import asyncio

import pytest

from scripts.servidor_55i_kv_kx_esp_lab import WssOnlyFromESP
from app.public_control.kv_kx_virtual_bridge_lab import HOTSPOT_PATH

HOST = "172.22.82.209:8443"
ESP = "172.22.82.5"


class Spy:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            await send({"type": "http.response.body", "body": b"EXPOSED"})
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1000})


async def call(gateway, kind, peer, path=HOTSPOT_PATH, headers=None,
               query=b""):
    events = []
    scope = {
        "type": kind, "client": (peer, 50000), "path": path,
        "headers": headers if headers is not None else [(b"host", HOST.encode())],
        "query_string": query,
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(item):
        events.append(item)

    await gateway(scope, receive, send)
    return events


def test_http_never_reaches_app_even_from_esp_or_loopback():
    spy = Spy()
    gate = WssOnlyFromESP(spy, esp_ip=ESP, host=HOST)
    for peer in (ESP, "127.0.0.1", "172.22.82.6", "8.8.8.8"):
        result = asyncio.run(call(gate, "http", peer,
                                  path="/admin/vehiculos/1/control-publico/solicitudes"))
        assert result[0]["status"] == 404
        assert result[1]["body"] == b""
    assert spy.calls == []


@pytest.mark.parametrize("peer,path,headers,query", [
    ("172.22.82.6", HOTSPOT_PATH, None, b""),
    ("127.0.0.1", HOTSPOT_PATH, None, b""),
    (ESP, "/ws/kx-diagnostico/1", None, b""),
    (ESP, HOTSPOT_PATH, [(b"host", b"attacker.invalid")], b""),
    (ESP, HOTSPOT_PATH, [(b"host", HOST.encode())], b"debug=1"),
    (ESP, HOTSPOT_PATH, [(b"host", HOST.encode()),
                         (b"authorization", b"Bearer invalid")], b""),
    (ESP, HOTSPOT_PATH, [(b"host", HOST.encode()),
                         (b"origin", b"https://evil.invalid")], b""),
    (ESP, HOTSPOT_PATH, [(b"host", HOST.encode()),
                         (b"cookie", b"session=other")], b""),
    (ESP, HOTSPOT_PATH, [(b"host", HOST.encode()),
                         (b"host", HOST.encode())], b""),
])
def test_websocket_refuses_unapproved_scope(peer, path, headers, query):
    spy = Spy()
    gate = WssOnlyFromESP(spy, esp_ip=ESP, host=HOST)
    out = asyncio.run(call(gate, "websocket", peer, path,
                           headers=headers, query=query))
    assert out == [{"type": "websocket.close", "code": 1008}]
    assert spy.calls == []


def test_only_esp_wss_exact_route_reaches_app():
    spy = Spy()
    gate = WssOnlyFromESP(spy, esp_ip=ESP, host=HOST)
    out = asyncio.run(call(gate, "websocket", ESP))
    assert out == [{"type": "websocket.close", "code": 1000}]
    assert len(spy.calls) == 1


def test_invalid_esp_ip_fail_closed():
    for ip in ("8.8.8.8", "127.0.0.1", "::1"):
        with pytest.raises(ValueError):
            WssOnlyFromESP(Spy(), esp_ip=ip, host=HOST)
