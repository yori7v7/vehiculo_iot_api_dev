"""K-K: rutas administrativas reales bajo FastAPI, con ESP virtual, sin motores."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.public_control.http import ScopedControlMiddleware
from app.public_control.kf_bridge import KFBridge
from app.public_control.kk_admin_lab import router
from app.public_control.single_link_admission_lab import SingleLinkAdmissionLab

ADMIN = "token-servidor-KK-para-pruebas-locales-12345678901234"
API_KEY = "clave-http-administrador-KK-123456"
BASE = "https://192.168.1.82:8443"
PATH = "/admin/vehiculos/1/control-publico/solicitudes"
HEADERS = {
    "X-API-Key": API_KEY,
    "Origin": "https://yori7v7.github.io",
    "Sec-Fetch-Site": "cross-site",
}


class VirtualKC:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.gate = SingleLinkAdmissionLab(ADMIN)
        self.connected = True
        self.stop_ok = True
        self.calls = []

    async def supervisor_pulse(self):
        async with self.lock:
            self.gate.supervisor_heartbeat(ADMIN)
            self.calls.append("heartbeat")
            return {"supervision": True, "vigencia_s": 15,
                    "control_fisico": False}

    async def approve_ticket(self, ticket_id, *, mode, seconds):
        async with self.lock:
            self.gate.approve(ADMIN, ticket_id, mode=mode,
                              turn_seconds=seconds)
            self.calls.append(("approve", ticket_id, mode))
            return {"aprobada": True, "control_fisico": False}

    async def revoke_all(self):
        async with self.lock:
            self.gate.revoke(ADMIN)
            self.calls.append("STOP")
            if not self.stop_ok:
                return {"detener": False, "neutral_virtual": False,
                        "parada_fisica_verificada": False}
            self.gate.neutral_confirmed_by_transport_for_lab(
                ADMIN, signed_neutral_ack=True)
            return {"detener": True, "neutral_virtual": True,
                    "parada_fisica_verificada": False}

    def status(self):
        return {"simulado": True}


@pytest.fixture
def rig():
    app = FastAPI()
    app.add_middleware(ScopedControlMiddleware)
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="development", api_key=API_KEY
    )
    kc = VirtualKC()
    app.state.public_control_settings = SimpleNamespace(app_env="development")
    app.state.public_control_simulation = False
    app.state.public_control = None
    app.state.kf_wss_controller = kc
    app.state.kf_bridge = KFBridge(kc, ADMIN)
    app.state.legacy_handover = SimpleNamespace(phase="exclusive")
    app.state.exclusive_device_control_enabled = True
    app.state.kg_lab_mode = True
    app.state.kg_lab_local_ip = "192.168.1.82"
    app.state.kj_lab_enabled = False
    app.state.kj_expected_host = "192.168.1.82:8443"
    return app, kc


def client(app, address="192.168.1.82"):
    return TestClient(app, base_url=BASE, client=(address, 57777))


def test_closed_without_explicit_kg_handover(rig):
    app, _ = rig
    with client(app) as c:
        assert c.get(PATH, headers=HEADERS).status_code == 503


def test_list_pending_and_supervision_then_approve(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    ticket = kc.gate.arrive()
    with client(app) as c:
        before = c.get(PATH, headers=HEADERS)
        assert before.status_code == 200
        assert before.json()["solicitudes"][0]["request_id"] == ticket["request_id"]
        assert before.json()["turno_activo"] is False
        assert "browser_secret" not in before.text
        assert before.json()["control_fisico"] is False

        approve = PATH + "/" + ticket["request_id"] + "/aprobar"
        assert c.post(approve, headers=HEADERS, json={"modo": "supervised"}).status_code == 409
        heartbeat = c.post(PATH + "/supervision", headers=HEADERS)
        assert heartbeat.status_code == 200
        assert heartbeat.json()["vigencia_s"] == 15
        accepted = c.post(approve, headers=HEADERS, json={"modo": "supervised"})
        assert accepted.status_code == 200
        assert accepted.json()["aprobada"] is True
        assert c.get(PATH, headers=HEADERS).json()["turno_activo"] is True


def test_reject_only_selected_ticket(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    a, b = kc.gate.arrive(), kc.gate.arrive()
    with client(app) as c:
        result = c.post(PATH + "/" + a["request_id"] + "/rechazar", headers=HEADERS)
        assert result.status_code == 200 and result.json()["rechazada"] is True
        remaining = c.get(PATH, headers=HEADERS).json()["solicitudes"]
        assert [row["request_id"] for row in remaining] == [b["request_id"]]
        assert c.post(PATH + "/" + a["request_id"] + "/rechazar", headers=HEADERS).status_code == 409


def test_revoke_invalidate_then_stop_ack(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    ticket = kc.gate.arrive()
    with client(app) as c:
        c.post(PATH + "/supervision", headers=HEADERS)
        assert c.post(PATH + "/" + ticket["request_id"] + "/aprobar",
                      headers=HEADERS, json={"modo": "supervised"}).status_code == 200
        assert c.post(PATH + "/revocar", headers=HEADERS).json()["revocado"] is True
        assert kc.gate.visitor_status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
        assert c.get(PATH, headers=HEADERS).json()["turno_activo"] is False
        assert "STOP" in kc.calls


def test_stop_not_confirmed_fails_closed(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    kc.stop_ok = False
    with client(app) as c:
        assert c.post(PATH + "/revocar", headers=HEADERS).status_code == 503


@pytest.mark.parametrize("missing", ["absent", "wrong", "bearer"])
def test_api_key_and_bearer_rejected(rig, missing):
    app, kc = rig
    app.state.kj_lab_enabled = True
    h = dict(HEADERS)
    if missing == "absent":
        del h["X-API-Key"]
    elif missing == "wrong":
        h["X-API-Key"] = "credencial-incorrecta"
    else:
        h["Authorization"] = "Bearer visitante"
    with client(app) as c:
        assert c.get(PATH, headers=h).status_code in (401, 403)


def test_wrong_origin_and_remote_lan_denied(rig):
    app, _ = rig
    app.state.kj_lab_enabled = True
    with client(app) as c:
        assert c.get(PATH, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
        assert c.get(PATH, headers={**HEADERS, "X-Forwarded-For": "127.0.0.1"}).status_code == 403
        assert c.get(PATH + "?role=admin", headers=HEADERS).status_code == 403
    with client(app, "192.168.1.194") as c:
        assert c.get(PATH, headers=HEADERS).status_code == 403


def test_same_wss_controller_required(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    with client(app) as c:
        kc.connected = False
        assert c.get(PATH, headers=HEADERS).status_code == 503
        kc.connected = True
        app.state.kf_wss_controller = VirtualKC()
        assert c.get(PATH, headers=HEADERS).status_code == 503


@pytest.mark.parametrize("body", [
    {"modo": "timed", "segundos": 1000},
    {"modo": "timed"},
    {"modo": "supervised", "segundos": 120},
    {"modo": "unexpected"},
    {"modo": "timed", "segundos": 120, "override_stop": True},
])
def test_invalid_approval_payloads(rig, body):
    app, kc = rig
    app.state.kj_lab_enabled = True
    ticket = kc.gate.arrive()
    with client(app) as c:
        assert c.post(PATH + "/supervision", headers=HEADERS).status_code == 200
        response = c.post(
            PATH + "/" + ticket["request_id"] + "/aprobar",
            headers=HEADERS, json=body,
        )
        assert response.status_code == 422
        assert kc.gate.visitor_status(ticket["browser_secret"])["estado"] == "esperando_autorizacion"


def test_cors_for_official_site_and_no_store(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    with client(app) as c:
        preflight = c.options(PATH, headers={
            "Origin": "https://yori7v7.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://yori7v7.github.io"
        assert preflight.headers["cache-control"] == "no-store"
        result = c.get(PATH, headers=HEADERS)
        assert result.headers["cache-control"] == "no-store"


def test_hidden_from_swagger_and_no_motion_routes(rig):
    app, kc = rig
    app.state.kj_lab_enabled = True
    with client(app) as c:
        assert PATH not in c.get("/openapi.json").json()["paths"]
        assert c.post(PATH + "/accion", headers=HEADERS, json={"codigo": 1}).status_code == 404
