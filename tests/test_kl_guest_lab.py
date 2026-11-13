"""5.5-K-L: admision de visitante en el mismo ASGI K-G (solo laboratorio)."""
import asyncio
import ast
from pathlib import Path
from contextlib import asynccontextmanager
from time import sleep, monotonic
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute

from app.config.settings import Settings, get_settings
from app.public_control.http import ScopedControlMiddleware
from app.public_control.kg_bootstrap import create_kg_app, WSS_PATH
from app.public_control.ki_ingress import router as guest_router
from app.public_control.kk_admin_lab import router as admin_router
from app.public_control.legacy_handover import LegacyHandoverGate
from app.public_control.single_link_admission_lab import SingleLinkAdmissionLab

HOST = "192.168.1.82:8443"
BASE = "https://" + HOST
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGIN = "https://yori7v7.github.io"
ADMIN_SECRET = "k" * 64
HTTP_KEY = "clave-de-pruebas-KL-nunca-publicar-123456"
HEAD_GUEST = {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}
HEAD_ADMIN = {**HEAD_GUEST, "X-API-Key": HTTP_KEY}


class FakeDemos:
    async def close_all(self):
        return None


class VirtualKC:
    def __init__(self, token, online=True):
        self.lock = asyncio.Lock()
        self.gate = SingleLinkAdmissionLab(token)
        self.connected = online
        self.last_neutral_virtual = online
        self.stop_requests = 0
        self.responds_to_hmac = True
        self.stall_on_probe = False

    async def dispatch(self, code):
        assert code == 0
        self.stop_requests += 1
        if self.stall_on_probe:
            await asyncio.sleep(10)
        if not self.connected or not self.responds_to_hmac:
            raise OSError("Sin ACK HMAC nuevo del ESP")
        self.last_neutral_virtual = True

    async def run_supervision_watchdog(self, event):
        await event.wait()

    async def close_on_fault(self):
        self.connected = False
        self.gate.device_lost()

    async def supervisor_pulse(self):
        async with self.lock:
            self.gate.supervisor_heartbeat(ADMIN_SECRET)
            return {"supervision": True, "vigencia_s": 15, "control_fisico": False}

    async def approve_ticket(self, ticket, *, mode, seconds):
        async with self.lock:
            await self.dispatch(0)
            self.gate.neutral_confirmed_by_transport_for_lab(
                ADMIN_SECRET, signed_neutral_ack=True)
            self.gate.approve(ADMIN_SECRET, ticket, mode=mode, turn_seconds=seconds)
            return {"aprobada": True, "control_fisico": False}

    async def revoke_all(self):
        async with self.lock:
            self.gate.revoke(ADMIN_SECRET)
            await self.dispatch(0)
            self.gate.neutral_confirmed_by_transport_for_lab(
                ADMIN_SECRET, signed_neutral_ack=True)
            return {"detener": True, "neutral_virtual": True,
                    "parada_fisica_verificada": False}

    def status(self):
        return {"simulado": True, "control_fisico": False}


def factory():
    @asynccontextmanager
    async def lifespan(_app):
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(ScopedControlMiddleware)
    app.include_router(guest_router)
    app.include_router(admin_router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="development", api_key=HTTP_KEY)
    app.state.public_control_settings = SimpleNamespace(
        app_env="development", control_publico_simulation=False,
        device_lab_enabled=False)
    app.state.public_control_simulation = False
    app.state.public_control = None
    app.state.legacy_handover = LegacyHandoverGate()
    app.state.demo_execution_manager = FakeDemos()

    @app.websocket(WSS_PATH)
    async def old_ws(websocket):
        await websocket.close()

    return app


def mock_kc(online=True):
    carrier = FastAPI()

    @carrier.websocket(WSS_PATH)
    async def kc_ws(websocket):
        await websocket.close()

    return SimpleNamespace(
        app=carrier, device_connection=kc_ws,
        KCController=lambda token: VirtualKC(token, online=online),
        old=SimpleNamespace(
            load_config=lambda: ({"ip": "192.168.1.82"}, bytes(range(32))),
            ensure_token=lambda _role: ADMIN_SECRET),
    )


def connected_app(online=True):
    return create_kg_app(mock_kc(online=online), app_factory=factory)


def wait_for_handover(app):
    for _ in range(60):
        if app.state.ki_contract_test_enabled:
            return
        sleep(0.05)
    raise AssertionError("K-L no se habilito despues del handover")


def test_single_controller_guest_admin_and_revoke():
    app = connected_app()
    with TestClient(app, base_url=BASE,
                    client=("192.168.1.82", 50001)) as client:
        wait_for_handover(app)
        assert app.state.kf_wss_controller is app.state.control
        assert app.state.ki_ingress.controller is app.state.control
        assert app.state.kf_bridge.controller is app.state.control
        assert app.state.kj_lab_enabled is True

        ticket_resp = client.post(GUEST, headers=HEAD_GUEST)
        assert ticket_resp.status_code == 201
        ticket = ticket_resp.json()
        assert ticket["simulado"] is True and ticket["control_fisico"] is False
        secret = ticket["browser_secret"]
        guest_headers = {**HEAD_GUEST, "X-Browser-Session": secret}
        waiting = client.get(GUEST + "/estado", headers=guest_headers)
        assert waiting.status_code == 200
        assert waiting.json()["estado"] == "esperando_autorizacion"

        inbox = client.get(ADMIN, headers=HEAD_ADMIN)
        assert inbox.status_code == 200
        assert inbox.json()["solicitudes"][0]["request_id"] == ticket["request_id"]
        assert secret not in inbox.text
        assert client.post(ADMIN + "/supervision", headers=HEAD_ADMIN).status_code == 200
        approval = client.post(
            ADMIN + "/" + ticket["request_id"] + "/aprobar",
            headers=HEAD_ADMIN, json={"modo": "timed", "segundos": 120})
        assert approval.status_code == 200
        approved = client.get(GUEST + "/estado", headers=guest_headers)
        assert approved.status_code == 200
        assert approved.json()["estado"] == "autorizado"
        assert "guest_token" not in approved.text
        assert app.state.control.stop_requests >= 2

        revoked = client.post(ADMIN + "/revocar", headers=HEAD_ADMIN)
        assert revoked.status_code == 200 and revoked.json()["revocado"] is True
        stopped = client.get(GUEST + "/estado", headers=guest_headers)
        assert stopped.status_code == 200
        assert stopped.json()["estado"] == "revocado_o_caducado"
        assert client.get(ADMIN, headers=HEAD_ADMIN).json()["turno_activo"] is False
        assert client.post(GUEST + "/accion", headers=HEAD_GUEST).status_code == 404
    assert app.state.ki_contract_test_enabled is False
    assert app.state.ki_ingress is None


def test_remote_lan_proxy_and_credentials_are_blocked():
    app = connected_app()
    with TestClient(app, base_url=BASE,
                    client=("192.168.1.82", 50111)) as local:
        wait_for_handover(app)
        remote = TestClient(app, base_url=BASE, client=("192.168.1.194", 50112))
        assert remote.post(GUEST, headers=HEAD_GUEST).status_code == 403
        assert remote.get(GUEST + "/estado", headers=HEAD_GUEST).status_code == 403
        assert local.post(GUEST, headers={**HEAD_GUEST,
                                         "X-Forwarded-Host": HOST}).status_code == 403
        assert local.post(GUEST, headers={**HEAD_GUEST,
                                         "X-API-Key": HTTP_KEY}).status_code == 403
        assert local.post(GUEST, headers={**HEAD_GUEST,
                                         "Cookie": "session=1"}).status_code == 403
        assert local.post(GUEST, headers={**HEAD_GUEST,
                                         "Origin": "https://evil.test"}).status_code == 403
        assert GUEST not in local.get("/openapi.json").json()["paths"]


def test_offline_disallows_guest_and_admin_and_stays_closed():
    app = connected_app()
    with TestClient(app, base_url=BASE,
                    client=("192.168.1.82", 50222)) as local:
        wait_for_handover(app)
        app.state.control.connected = False
        assert local.post(GUEST, headers=HEAD_GUEST).status_code == 503
        assert local.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
        sleep(0.2)
        assert app.state.ki_contract_test_enabled is False
        assert app.state.kj_lab_enabled is False
        # No auto-reentrada sin nuevo handover seguro.
        app.state.control.connected = True
        sleep(0.2)
        assert app.state.ki_contract_test_enabled is False


def test_before_authenticated_esp_guest_routes_closed():
    app = connected_app(online=False)
    with TestClient(app, base_url=BASE,
                    client=("192.168.1.82", 50333)) as local:
        assert app.state.ki_ingress is None
        assert app.state.ki_contract_test_enabled is False
        assert local.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
        assert local.post(GUEST, headers=HEAD_GUEST).status_code in (403, 503)


def test_local_manual_script_has_valid_python_and_no_motion_routes():
    source = (Path(__file__).resolve().parents[1] / "scripts"
              / "prueba_55kl_admision_local.py").read_text(encoding="utf-8")
    ast.parse(source, filename="prueba_55kl_admision_local.py")
    assert "/movimientos" not in source
    assert "/demos/" not in source
    assert "/accion" not in source


def test_ko_socket_obsoleto_con_connected_true_cierra_admin_y_visitante(monkeypatch):
    """Un TCP aparentemente abierto NO reemplaza el acuse HMAC firmado."""
    monkeypatch.setattr("app.public_control.kg_bootstrap.KG_PROBE_INTERVAL_S", 0.05)
    app = connected_app()
    with TestClient(app, base_url=BASE, client=("192.168.1.82", 53333)) as client:
        wait_for_handover(app)
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 200
        controller = app.state.control
        assert controller.connected is True
        controller.responds_to_hmac = False
        deadline = monotonic() + 3
        while monotonic() < deadline and not app.state.kg_transport_fenced:
            sleep(0.03)
        assert app.state.kg_transport_fenced is True
        assert app.state.kg_last_signed_stop_at is None
        assert app.state.kj_lab_enabled is False
        assert app.state.ki_contract_test_enabled is False
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
        assert client.post(GUEST, headers=HEAD_GUEST).status_code == 503
        # Reconectar socket simulado no debe reabrir K-K/K-I sin nuevo arranque.
        controller.connected = True
        controller.responds_to_hmac = True
        sleep(0.15)
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
        assert client.post(GUEST, headers=HEAD_GUEST).status_code == 503


def test_ko_lease_vencida_denegada_aunque_connected_true():
    from app.public_control.kg_liveness import (
        ACK_LEASE_SECONDS, signed_transport_recent,
    )
    state = SimpleNamespace(kg_lab_mode=True, kg_transport_fenced=False,
                            kg_last_signed_stop_at=float(monotonic() - ACK_LEASE_SECONDS - 1))
    assert signed_transport_recent(state) is False
    state.kg_last_signed_stop_at = float(monotonic())
    assert signed_transport_recent(state) is True
    state.kg_transport_fenced = True
    assert signed_transport_recent(state) is False


def test_ko_wss_silencioso_sin_ack_cierra_por_timeout_y_no_reabre(monkeypatch):
    """El USB puede morir sin enviar close; un recv bloqueado debe vencer."""
    monkeypatch.setattr("app.public_control.kg_bootstrap.KG_PROBE_INTERVAL_S", 0.05)
    monkeypatch.setattr("app.public_control.kg_bootstrap.KG_PROBE_TIMEOUT_S", 0.16)
    app = connected_app()
    with TestClient(app, base_url=BASE, client=("192.168.1.82", 53344)) as client:
        wait_for_handover(app)
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 200
        app.state.control.stall_on_probe = True
        deadline = monotonic() + 2
        while monotonic() < deadline and not app.state.kg_transport_fenced:
            sleep(0.03)
        assert app.state.kg_transport_fenced is True
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
        assert client.post(GUEST, headers=HEAD_GUEST).status_code == 503
        app.state.control.stall_on_probe = False
        app.state.control.connected = True
        sleep(0.1)
        assert client.get(ADMIN, headers=HEAD_ADMIN).status_code == 503
