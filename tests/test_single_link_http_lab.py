import pytest
from fastapi.testclient import TestClient
from app.public_control.single_link_http_lab import create_portal_http_lab_app

ADMIN = "Admin-para-pruebas-KB-secreto-generado-000123456789"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def step(self, delta):
        self.t += delta


@pytest.fixture
def lab():
    clock = Clock()
    client = TestClient(
        create_portal_http_lab_app(ADMIN, clock=clock),
        base_url="http://127.0.0.1:8767",
        client=("127.0.0.1", 54321),
    )
    return client, clock


def admin():
    return {"X-Lab-Admin": ADMIN, "Origin": "http://127.0.0.1:8767"}


def arrive(client):
    response = client.post("/api/k/solicitud", headers={"Origin": "http://127.0.0.1:8767"})
    assert response.status_code == 201
    assert response.json()["control_fisico"] is False
    return response.json()


def status(client, visitor):
    return client.get(
        "/api/k/solicitud/estado",
        headers={"X-Browser-Session": visitor["browser_secret"]},
    )


def heartbeat(client):
    return client.post("/api/k/admin/supervision", headers=admin())


def approve(client, visitor, **extra):
    return client.post(
        "/api/k/admin/aprobar", headers=admin(),
        json={"request_id": visitor["request_id"], **extra},
    )


def test_waiting_not_automatically_approved(lab):
    client, clock = lab
    visitor = arrive(client)
    assert status(client, visitor).json()["estado"] == "esperando_autorizacion"
    assert approve(client, visitor).status_code == 409
    assert client.get("/api/k/admin/pendientes").status_code == 401
    pending = client.get("/api/k/admin/pendientes", headers=admin()).json()["solicitudes"]
    assert pending[0]["display_code"] == visitor["display_code"]


def test_supervised_approval_and_automatic_expiration(lab):
    client, clock = lab
    visitor = arrive(client)
    assert heartbeat(client).status_code == 200
    assert approve(client, visitor).status_code == 200
    assert status(client, visitor).json()["estado"] == "autorizado"
    for _ in range(4):
        clock.step(10)
        assert heartbeat(client).status_code == 200
        assert status(client, visitor).json()["estado"] == "autorizado"
    clock.step(15)
    assert status(client, visitor).json()["estado"] == "revocado_o_caducado"
    assert client.get("/api/k/admin/estado", headers=admin()).json()["stop_required"]


def test_revoke_blocks_and_never_moves(lab):
    client, clock = lab
    visitor = arrive(client)
    assert heartbeat(client).status_code == 200
    assert approve(client, visitor).status_code == 200
    result = client.post(
        "/api/k/accion", json={"codigo": 9},
        headers={"X-Browser-Session": visitor["browser_secret"]},
    )
    assert result.status_code == 403
    assert client.post("/api/k/admin/revocar", headers=admin()).status_code == 200
    assert status(client, visitor).json()["estado"] == "revocado_o_caducado"
    second = arrive(client)
    assert approve(client, second).status_code == 409  # Neutral lógico requerido


def test_timed_permission_expires(lab):
    client, clock = lab
    visitor = arrive(client)
    assert heartbeat(client).status_code == 200
    assert approve(client, visitor, modo="timed", segundos=5).status_code == 200
    clock.step(5)
    assert status(client, visitor).json()["estado"] == "revocado_o_caducado"


def test_reject_exact_request_and_invalid_uuid(lab):
    client, clock = lab
    visitor = arrive(client)
    result = client.post("/api/k/admin/rechazar", headers=admin(),
                         json={"request_id": visitor["request_id"]})
    assert result.status_code == 200
    assert status(client, visitor).json()["estado"] == "revocado_o_caducado"
    bad = client.post("/api/k/admin/aprobar", headers=admin(), json={"request_id": "not-uuid"})
    assert bad.status_code == 422


def test_external_origin_and_lan_host_rejected(lab):
    client, clock = lab
    assert client.post("/api/k/solicitud", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/k/solicitud", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/k/ping", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    assert client.get("/api/k/ping", headers={"Host": "192.168.1.82:8767"}).status_code == 403
    assert client.get("/api/k/ping").headers["cache-control"] == "no-store"


def test_no_admin_secret_exposed_to_visitor(lab):
    client, clock = lab
    visitor = arrive(client)
    assert ADMIN not in str(visitor)
    assert ADMIN not in status(client, visitor).text
    assert "browser_secret" not in client.get(
        "/api/k/admin/pendientes", headers=admin(),
    ).text


def test_bounded_queue(lab):
    client, clock = lab
    for _ in range(5):
        arrive(client)
    assert client.post("/api/k/solicitud").status_code == 409


def test_admin_credential_required_even_for_revoke(lab):
    client, clock = lab
    for path in ("/api/k/admin/estado", "/api/k/admin/pendientes"):
        assert client.get(path).status_code == 401
    assert client.post("/api/k/admin/revocar").status_code == 401
    assert heartbeat(client).json()["supervision"]


def test_invalid_content_type_and_body_limit(lab):
    client, clock = lab
    bad_content = client.post(
        "/api/k/admin/aprobar",
        headers={**admin(), "Content-Type": "text/plain"}, content="x",
    )
    assert bad_content.status_code == 415
    too_large = client.post(
        "/api/k/admin/aprobar",
        headers=admin(), json={"request_id": "x", "junk": "A" * 2000},
    )
    assert too_large.status_code == 413
