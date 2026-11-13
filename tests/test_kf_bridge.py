"""K-F: ASGI test contracts; virtual controller, no motor or AWS."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.public_control.kf_attach import attach_verified_kf_bridge
from app.public_control.kf_bridge import router, KFBridge
from app.public_control.legacy_handover import LegacyHandoverGate
from app.public_control.single_link_admission_lab import SingleLinkAdmissionLab, AdmissionDenied

ADMIN = "administrador-pruebas-kf-no-publicar-123456789012345"
PATH = "/interno/55kf"


class FakeKC:
    def __init__(self):
        self.connected = True
        self.lock = asyncio.Lock()
        self.gate = SingleLinkAdmissionLab(ADMIN)
        self.last_neutral_virtual = False
        self.orders = []
        self.actor = "admin"
        self.fail_stop = False

    async def dispatch(self, code):
        self.orders.append(code)
        if self.fail_stop:
            raise RuntimeError("HMAC ACK no recibido")
        self.last_neutral_virtual = code == 0

    async def supervisor_pulse(self):
        async with self.lock:
            self.gate.supervisor_heartbeat(ADMIN)
            return {"supervision": True, "vigencia_s": 15, "control_fisico": False}

    async def approve_ticket(self, ticket_id, *, mode, seconds):
        async with self.lock:
            await self.dispatch(0)
            try:
                self.gate.approve(ADMIN, ticket_id, mode=mode, turn_seconds=seconds)
            except AdmissionDenied:
                raise HTTPException(409, "Solicitud no disponible") from None
            self.actor = "guest"
            return {"aprobada": True, "control_fisico": False}

    async def revoke_all(self):
        self.gate.revoke(ADMIN)
        async with self.lock:
            await self.dispatch(0)
            self.gate.neutral_confirmed_by_transport_for_lab(
                ADMIN, signed_neutral_ack=True,
            )
            self.actor = "admin"
            return {"detener": True, "neutral_virtual": True,
                    "parada_fisica_verificada": False}

    def status(self):
        return {"operador": self.actor, "simulado": True, "gpio_inhibido": True}


class FakeDemos:
    def __init__(self):
        self.closed = False

    async def close_all(self):
        self.closed = True


def app():
    obj = FastAPI()
    obj.include_router(router)
    obj.state.public_control_settings = SimpleNamespace(
        app_env="development", control_publico_simulation=False,
        device_lab_enabled=False,
    )
    obj.state.legacy_handover = LegacyHandoverGate()
    obj.state.exclusive_device_control_enabled = False
    obj.state.kf_bridge = None
    obj.state.kf_wss_controller = None
    obj.state.demo_execution_manager = FakeDemos()
    return obj


async def install(obj, device):
    obj.state.kf_wss_controller = device
    await attach_verified_kf_bridge(obj, device, ADMIN)


def client(obj):
    return AsyncClient(transport=ASGITransport(app=obj), base_url="http://127.0.0.1")


def admin():
    return {"X-KF-Admin": ADMIN}


@pytest.mark.asyncio
async def test_closed_by_default():
    api = app()
    async with client(api) as c:
        assert (await c.post(PATH + "/solicitud")).status_code == 503
        assert (await c.post(PATH + "/accion")).status_code == 403


@pytest.mark.asyncio
async def test_handover_drains_demos_and_requires_neutral():
    api, device = app(), FakeKC()
    await install(api, device)
    assert api.state.legacy_handover.phase == "exclusive"
    assert api.state.demo_execution_manager.closed
    assert api.state.exclusive_device_control_enabled
    assert api.state.kf_bridge.controller is device
    assert device.orders == [0]


@pytest.mark.asyncio
async def test_request_approve_revoke_same_controller():
    api, device = app(), FakeKC()
    await install(api, device)
    async with client(api) as c:
        request = (await c.post(PATH + "/solicitud")).json()
        session = {"X-Browser-Session": request["browser_secret"]}
        assert (await c.get(PATH + "/solicitud/estado", headers=session)).json()["estado"] == "esperando_autorizacion"
        data = {"request_id": request["request_id"]}
        assert (await c.post(PATH + "/admin/aprobar", json=data, headers=admin())).status_code == 409
        assert (await c.post(PATH + "/admin/supervision", headers=admin())).status_code == 200
        assert (await c.post(PATH + "/admin/aprobar", json=data, headers=admin())).status_code == 200
        result = (await c.get(PATH + "/solicitud/estado", headers=session)).json()
        assert result["estado"] == "autorizado" and "guest_token" not in result
        assert (await c.post(PATH + "/accion", json={"codigo": 9})).status_code == 403
        assert (await c.post(PATH + "/admin/detener", headers=admin())).status_code == 200
        assert (await c.get(PATH + "/solicitud/estado", headers=session)).json()["estado"] == "revocado_o_caducado"
    assert device.orders == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_admin_header_required():
    api, device = app(), FakeKC()
    await install(api, device)
    async with client(api) as c:
        assert (await c.get(PATH + "/estado")).status_code == 401
        assert (await c.post(PATH + "/admin/supervision", headers={"X-KF-Admin": "bad"})).status_code == 401
        row = (await c.post(PATH + "/solicitud")).json()
        assert ADMIN not in str(row)
        assert (await c.get(PATH + "/admin/pendientes", headers=admin())).json()["solicitudes"][0]["request_id"] == row["request_id"]


@pytest.mark.asyncio
async def test_rejection():
    api, device = app(), FakeKC()
    await install(api, device)
    async with client(api) as c:
        row = (await c.post(PATH + "/solicitud")).json()
        assert (await c.post(PATH + "/admin/rechazar", headers=admin(),
                             json={"request_id": row["request_id"]})).status_code == 200
        assert (await c.get(PATH + "/solicitud/estado",
                            headers={"X-Browser-Session": row["browser_secret"]})).json()["estado"] == "revocado_o_caducado"


@pytest.mark.asyncio
async def test_public_origin_proxy_and_host_blocked():
    api, device = app(), FakeKC()
    await install(api, device)
    async with client(api) as c:
        for headers in (
            {"Origin": "https://yori7v7.github.io"},
            {"X-Forwarded-For": "127.0.0.1"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Host": "example.org"},
        ):
            assert (await c.post(PATH + "/solicitud", headers=headers)).status_code == 403
        assert (await c.post(PATH + "/solicitud?guest=1")).status_code == 403


@pytest.mark.asyncio
async def test_stop_failure_leaves_gate_blocked():
    api, device = app(), FakeKC()
    device.fail_stop = True
    api.state.kf_wss_controller = device
    with pytest.raises(RuntimeError):
        await attach_verified_kf_bridge(api, device, ADMIN)
    assert api.state.kf_bridge is None
    assert api.state.legacy_handover.phase == "blocked"


@pytest.mark.asyncio
async def test_disconnected_denied():
    api, device = app(), FakeKC()
    device.connected = False
    api.state.kf_wss_controller = device
    with pytest.raises(RuntimeError):
        await attach_verified_kf_bridge(api, device, ADMIN)


@pytest.mark.asyncio
async def test_production_denied():
    api, device = app(), FakeKC()
    api.state.public_control_settings.app_env = "production"
    api.state.kf_wss_controller = device
    with pytest.raises(RuntimeError):
        await attach_verified_kf_bridge(api, device, ADMIN)


@pytest.mark.asyncio
async def test_disconnect_after_attach_closes_http():
    api, device = app(), FakeKC()
    await install(api, device)
    device.connected = False
    async with client(api) as c:
        assert (await c.post(PATH + "/solicitud")).status_code == 503


@pytest.mark.asyncio
async def test_browser_token_does_not_replace_admin_token():
    api, device = app(), FakeKC()
    await install(api, device)
    async with client(api) as c:
        row = (await c.post(PATH + "/solicitud")).json()
        assert (await c.post(PATH + "/admin/supervision",
                   headers={"X-KF-Admin": row["browser_secret"]})).status_code == 401
        status = await c.get(PATH + "/solicitud/estado",
                             headers={"X-Browser-Session": row["browser_secret"]})
        assert status.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_identity_and_parallel_simulation_rejected():
    api, device, other = app(), FakeKC(), FakeKC()
    api.state.kf_wss_controller = other
    with pytest.raises(RuntimeError):
        await attach_verified_kf_bridge(api, device, ADMIN)
    api.state.kf_wss_controller = device
    api.state.public_control_settings.control_publico_simulation = True
    with pytest.raises(RuntimeError):
        await attach_verified_kf_bridge(api, device, ADMIN)
