"""K-I: contrato HTTPS y CORS de admisión, sin AWS, dispositivos ni RDS."""
import asyncio
from secrets import token_urlsafe
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.public_control.http import ScopedControlMiddleware
from app.public_control.ki_ingress import router, GuestIngressLab
from app.public_control.single_link_admission_lab import AdmissionDenied

BASE = "https://api.example.test"
PATH = "/publico/vehiculos/1/solicitudes"
HEAD = {"Origin": "https://yori7v7.github.io", "Sec-Fetch-Site": "cross-site"}


def ticket_headers(i: int = 0) -> dict:
    return {**HEAD, "Idempotency-Key": chr(65 + i) * 43,
            "X-Browser-Proposal": chr(80 + i) * 43}


class FakeGate:
    def __init__(self):
        self.data = {}
        self.requests = 0
        self.replays = {}

    def arrive_idempotent(self, *, idempotency_key, browser_secret, client_identity):
        previous = self.replays.get(idempotency_key)
        if previous is not None:
            if previous["browser_secret"] != browser_secret or previous["client"] != client_identity:
                raise AdmissionDenied("Reintento no autorizado")
            return {key: val for key, val in previous.items() if key != "client"} | {"idempotent_replay": True}
        self.requests += 1
        if self.requests > 5:
            raise AdmissionDenied("Demasiadas solicitudes pendientes.")
        row = {"request_id": f"request-{self.requests}", "browser_secret": browser_secret,
               "display_code": "A1B2C3D4", "estado": "esperando_autorizacion",
               "idempotent_replay": False, "client": client_identity}
        self.data[browser_secret] = "esperando_autorizacion"
        self.replays[idempotency_key] = row
        return {key: val for key, val in row.items() if key != "client"}

    def arrive(self):
        self.requests += 1
        if self.requests > 5:
            raise AdmissionDenied()
        secret = token_urlsafe(32)
        row = {"request_id": f"request-{self.requests}", "browser_secret": secret,
               "display_code": "A1B2C3D4", "estado": "esperando_autorizacion"}
        self.data[secret] = "esperando_autorizacion"
        return row

    def visitor_status(self, secret):
        if secret not in self.data:
            raise AdmissionDenied()
        return {"estado": self.data[secret], "display_code": "A1B2C3D4",
                "guest_token": "NUNCA-ENVIAR-ESTO", "control_fisico": False}


class FakeController:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.connected = True
        self.gate = FakeGate()


@pytest.fixture
def rig():
    app = FastAPI()
    app.add_middleware(ScopedControlMiddleware)
    app.include_router(router)
    controller = FakeController()
    app.state.public_control_settings = SimpleNamespace(app_env="development")
    app.state.public_control_simulation = False
    app.state.public_control = None
    app.state.ki_contract_test_enabled = False
    app.state.exclusive_device_control_enabled = True
    app.state.kf_wss_controller = controller
    app.state.legacy_handover = SimpleNamespace(phase="exclusive")
    app.state.ki_ingress = GuestIngressLab(controller)
    app.state.ki_expected_host = "api.example.test"
    return app, controller


def test_fail_closed_by_default(rig):
    app, controller = rig
    with TestClient(app, base_url=BASE) as client:
        assert client.post(PATH, headers=HEAD).status_code == 503


def test_ticket_wait_approval_and_revoke_never_leak_turn_token(rig):
    app, controller = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        result = client.post(PATH, headers=ticket_headers())
        assert result.status_code == 201
        assert result.json()["control_fisico"] is False
        secret = result.json()["browser_secret"]
        headers = {**HEAD, "X-Browser-Session": secret}
        assert client.get(PATH + "/estado", headers=headers).json()["estado"] == "esperando_autorizacion"
        controller.gate.data[secret] = "autorizado"
        current = client.get(PATH + "/estado", headers=headers)
        assert current.status_code == 200
        assert current.json()["estado"] == "autorizado"
        assert "guest_token" not in current.json()
        assert current.headers["cache-control"] == "no-store"
        controller.gate.data[secret] = "revocado_o_caducado"
        assert client.get(PATH + "/estado", headers=headers).json()["estado"] == "revocado_o_caducado"
        assert client.post(PATH + "/accion", headers=HEAD).status_code == 404
        replay = client.post(PATH, headers=ticket_headers())
        assert replay.status_code == 200
        assert replay.json()["browser_secret"] == secret
        assert replay.json()["idempotent_replay"] is True
        assert controller.gate.requests == 1


def test_cors_preflight_isolated_from_legacy_guest_routes(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        headers = {"Origin": HEAD["Origin"], "Access-Control-Request-Method": "GET",
                   "Access-Control-Request-Headers": "x-browser-session"}
        good = client.options(PATH + "/estado", headers=headers)
        assert good.status_code == 200
        pair_preflight = client.options(PATH, headers={
            "Origin": HEAD["Origin"], "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,x-browser-proposal",
        })
        assert pair_preflight.status_code == 200
        assert pair_preflight.headers["access-control-allow-origin"] == HEAD["Origin"]
        assert good.headers["access-control-allow-origin"] == HEAD["Origin"]
        assert good.headers["cache-control"] == "no-store"
        assert good.headers["referrer-policy"] == "no-referrer"
        old = client.options("/publico/vehiculos/1/sesion", headers=headers)
        assert old.status_code == 400
        bad = client.options(PATH, headers={
            "Origin": HEAD["Origin"], "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key",
        })
        assert bad.status_code == 400


def test_untrusted_origin_host_and_http_rejected(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        assert client.post(PATH, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post(PATH, headers={**HEAD, "Host": "evil.example"}).status_code == 403
        assert client.post(PATH, headers={**HEAD, "X-Forwarded-For": "1.2.3.4"}).status_code == 403
        assert client.post(PATH + "?token=1", headers=HEAD).status_code == 403
    with TestClient(app, base_url="http://api.example.test") as client:
        assert client.post(PATH, headers=HEAD).status_code == 403


def test_guest_cannot_supply_admin_credentials_or_cookies(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        for credentials in ({"X-API-Key": "admin"},
                            {"Authorization": "Bearer admin"},
                            {"Cookie": "session=123"}):
            assert client.post(PATH, headers={**HEAD, **credentials}).status_code == 403


def test_secret_required_and_no_reuse_during_creation(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        assert client.get(PATH + "/estado", headers=HEAD).status_code == 401
        assert client.get(PATH + "/estado", headers={
            **HEAD, "X-Browser-Session": "bad"}).status_code == 401
        assert client.post(PATH, headers={
            **HEAD, "X-Browser-Session": "x" * 43}).status_code == 403
        assert client.post(PATH, headers=HEAD).status_code == 428
        assert client.post(PATH, headers={**HEAD, "Idempotency-Key": "x" * 43}).status_code == 428
        assert client.post(PATH, headers={
            **HEAD, "Idempotency-Key": "x" * 43,
            "X-Browser-Proposal": "x" * 43}).status_code == 428


def test_idempotent_replay_does_not_add_second_ticket(rig):
    app, controller = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        first = client.post(PATH, headers=ticket_headers())
        again = client.post(PATH, headers=ticket_headers())
        assert first.status_code == 201
        assert again.status_code == 200
        assert again.json()["request_id"] == first.json()["request_id"]
        assert controller.gate.requests == 1
        changed = {**ticket_headers(), "X-Browser-Proposal": "Z" * 43}
        assert client.post(PATH, headers=changed).status_code == 409
        assert controller.gate.requests == 1


def test_global_queue_bound(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        for i in range(5):
            assert client.post(PATH, headers=ticket_headers(i)).status_code == 201
        exhausted = client.post(PATH, headers=ticket_headers(5))
        assert exhausted.status_code == 429
        assert exhausted.headers["cache-control"] == "no-store"


def test_disconnected_or_different_controller_closed(rig):
    app, controller = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        controller.connected = False
        assert client.post(PATH, headers=HEAD).status_code == 503
        controller.connected = True
        app.state.kf_wss_controller = FakeController()
        assert client.post(PATH, headers=HEAD).status_code == 503


def test_not_exposed_in_openapi(rig):
    app, _ = rig
    assert PATH not in app.openapi()["paths"]


def test_reject_different_vehicle(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        assert client.post("/publico/vehiculos/2/solicitudes", headers=HEAD).status_code == 503


def test_body_rejected(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    with TestClient(app, base_url=BASE) as client:
        assert client.post(PATH, headers=HEAD, content=b"not needed").status_code == 400


def test_production_denied_even_when_fake_adapter_installed(rig):
    app, _ = rig
    app.state.ki_contract_test_enabled = True
    app.state.public_control_settings.app_env = "production"
    with TestClient(app, base_url=BASE) as client:
        assert client.post(PATH, headers=HEAD).status_code == 503
