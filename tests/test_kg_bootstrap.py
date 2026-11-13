"""K-G: pruebas aisladas del arranque conjunto; no necesitan el ESP físico."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute
import pytest

from app.public_control.kg_bootstrap import create_kg_app, WSS_PATH
from app.public_control.kf_bridge import router as kf_router
from app.public_control.legacy_handover import LegacyHandoverGate


class Device:
    connected = False
    last_neutral_virtual = False

    def __init__(self, *_args):
        pass

    async def run_supervision_watchdog(self, event):
        await event.wait()

    async def close_on_fault(self):
        pass


def factory(*, env="development"):
    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(kf_router)
    app.state.public_control_settings = SimpleNamespace(
        app_env=env, control_publico_simulation=False, device_lab_enabled=False)
    app.state.legacy_handover = LegacyHandoverGate()
    app.state.exclusive_device_control_enabled = False
    app.state.kf_bridge = None

    @app.websocket(WSS_PATH)
    async def historical(ws):
        await ws.close(code=1008)

    return app


def kc():
    carrier = FastAPI()

    @carrier.websocket(WSS_PATH)
    async def kc_websocket(ws):
        await ws.close(code=1008)

    return SimpleNamespace(
        app=carrier, device_connection=kc_websocket, KCController=Device,
        old=SimpleNamespace(load_config=lambda: ({"ip": "192.168.1.82"}, bytes(range(32))),
                            ensure_token=lambda name: "a" * 64),
    )


def test_kf_closed_until_device_auth():
    server = kc()
    app = create_kg_app(server, app_factory=factory)
    assert app.state.exclusive_device_control_enabled
    assert app.router.routes[0].endpoint is server.device_connection
    assert len([r for r in app.router.routes if isinstance(r, WebSocketRoute)
                and r.path == WSS_PATH]) == 2
    with TestClient(app, base_url="https://192.168.1.82",
                    client=("192.168.1.82", 1234)) as client:
        assert client.post("/interno/55kf/solicitud").status_code == 503
        assert app.state.kf_wss_controller is app.state.control
    assert app.state.kf_bridge is None


def test_production_denied_before_startup():
    with pytest.raises(RuntimeError):
        create_kg_app(kc(), app_factory=lambda: factory(env="production"))


def test_other_device_lan_forbidden():
    app = create_kg_app(kc(), app_factory=factory)
    with TestClient(app, base_url="https://192.168.1.82",
                    client=("192.168.1.194", 10000)) as client:
        assert client.post("/interno/55kf/solicitud").status_code == 403
