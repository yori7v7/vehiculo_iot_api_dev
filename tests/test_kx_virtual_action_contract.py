"""Contrato K-X de orden VIRTUAL: denegacion/revocacion/caducidad.

No se usa motor, firmware, RDS, ni proceso EC2. Este endpoint NO es
la interfaz final de conduccion; comprueba el enlace de autorizacion.
"""
from __future__ import annotations

from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.main import create_app

HOST = "https://100-30-4-62.nip.io"
ORIGIN = "https://yori7v7.github.io"
GUEST = "/publico/vehiculos/1/solicitudes"
ACTION = GUEST + "/verificar-accion"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
KEY = "PRUEBA-KX-" + "Q" * 54


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(tmp_path / "kx-gate.sqlite3"))
    monkeypatch.setenv("CONTROL_PUBLICO_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_SIMULATION", "false")
    monkeypatch.setenv("DEVICE_LAB_ENABLED", "false")
    get_settings.cache_clear()
    application = create_app()
    yield application
    get_settings.cache_clear()


def request_and_approve(client):
    proposal = token_urlsafe(32)
    data = client.post(GUEST, headers={
        "Origin": ORIGIN,
        "Idempotency-Key": token_urlsafe(32),
        "X-Browser-Proposal": proposal,
    })
    assert data.status_code == 201, data.text
    row = data.json()
    admin = {"Origin": ORIGIN, "X-API-Key": KEY}
    assert client.post(ADMIN + "/supervision", headers=admin).status_code == 200
    approved = client.post(
        ADMIN + f"/{row['request_id']}/aprobar", headers=admin,
        json={"modo": "timed", "segundos": 120},
    )
    assert approved.status_code == 200, approved.text
    return proposal, admin


def call(client, secret, code=1, duration=250):
    return client.post(ACTION,
                       headers={"Origin": ORIGIN, "X-Browser-Session": secret},
                       json={"codigo": code, "duracion_ms": duration})


def test_virtual_order_requires_live_approved_turn_and_revocation(app):
    with TestClient(app, base_url=HOST) as client:
        proposal = token_urlsafe(32)
        created = client.post(GUEST, headers={
            "Origin": ORIGIN,
            "Idempotency-Key": token_urlsafe(32),
            "X-Browser-Proposal": proposal,
        })
        assert created.status_code == 201
        assert call(client, proposal).status_code == 403
        assert call(client, token_urlsafe(32)).status_code == 403
        admin = {"Origin": ORIGIN, "X-API-Key": KEY}
        assert client.post(ADMIN + "/supervision", headers=admin).status_code == 200
        rid = created.json()["request_id"]
        assert client.post(ADMIN + f"/{rid}/aprobar", headers=admin,
                           json={"modo": "timed", "segundos": 120}).status_code == 200
        valid = call(client, proposal, code=9)
        assert valid.status_code == 200, valid.text
        assert valid.json() == {
            "permiso_virtual_verificado": True,
            "codigo": 9, "duracion_ms": 250, "despacho_wss": False,
            "stop_fisico_confirmado": False, "simulado": True,
            "control_fisico": False, "canDrive": False,
        }
        assert client.post(ADMIN + "/revocar", headers=admin).status_code == 200
        assert call(client, proposal).status_code == 403


def test_virtual_order_rejects_unauthorized_inputs_and_legacy(app):
    with TestClient(app, base_url=HOST) as client:
        proposal, admin = request_and_approve(client)
        assert call(client, proposal, code=64).status_code == 422
        assert call(client, proposal, duration=600).status_code == 422
        assert client.post(ACTION, headers={"Origin": ORIGIN},
                           json={"codigo": 1, "duracion_ms": 250}).status_code == 401
        assert client.post(ACTION,
                           headers={"Origin": "https://example.com",
                                    "X-Browser-Session": proposal},
                           json={"codigo": 1, "duracion_ms": 250}).status_code == 403
        assert client.post(ACTION,
                           headers={"Origin": ORIGIN, "X-Browser-Session": proposal,
                                    "X-API-Key": KEY},
                           json={"codigo": 1, "duracion_ms": 250}).status_code == 403
        assert client.post("/vehiculos/1/movimientos", headers=admin,
                           json={"id_comando": 2}).status_code == 503


def test_virtual_order_expires_without_supervisor_heartbeat(app):
    with TestClient(app, base_url=HOST) as client:
        proposal, _admin = request_and_approve(client)
        assert call(client, proposal).status_code == 200
        ledger = app.state.kx_ledger
        after = ledger._now() + 16
        ledger._clock = lambda: after
        assert call(client, proposal).status_code == 403
        row = client.get(GUEST + "/estado",
                         headers={"Origin": ORIGIN, "X-Browser-Session": proposal})
        assert row.status_code == 200
        assert row.json()["estado"] == "revocado_o_caducado"
