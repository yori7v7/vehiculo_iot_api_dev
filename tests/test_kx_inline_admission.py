"""K-X: ASGI HTTPS real dentro de TestClient, sin EC2, RDS ni ESP.

La nueva puerta solo permite autorización de OBSERVACION VIRTUAL. Ningún
endpoint nuevo despacha movimiento; los antiguos quedan bloqueados al activar
el modo. Un fallo debe cerrar el acceso en vez de abrir motores.
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
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
KEY = "KX-CLAVE-PRIVADA-DE-PRUEBA-" + "X" * 48


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "virtual-only.sqlite3"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(db))
    monkeypatch.setenv("CONTROL_PUBLICO_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_SIMULATION", "false")
    monkeypatch.setenv("DEVICE_LAB_ENABLED", "false")
    get_settings.cache_clear()
    application = create_app()
    yield application
    get_settings.cache_clear()


def identity():
    return {
        "Origin": ORIGIN,
        "Idempotency-Key": token_urlsafe(32),
        "X-Browser-Proposal": token_urlsafe(32),
    }


def test_kx_in_process_virtual_only_full_contract(app):
    with TestClient(app, base_url=HOST) as client:
        original = identity()
        requested = client.post(GUEST, headers=original)
        assert requested.status_code == 201, requested.text
        row = requested.json()
        assert row["browser_secret"] == original["X-Browser-Proposal"]
        assert row["simulado"] is True
        assert row["control_fisico"] is False
        assert row["canDrive"] is False
        assert len(row["display_code"]) == 8
        assert client.post(GUEST, headers=original).status_code == 200

        visitor = {
            "Origin": ORIGIN,
            "X-Browser-Session": row["browser_secret"],
        }
        waiting = client.get(GUEST + "/estado", headers=visitor)
        assert waiting.status_code == 200
        assert waiting.json()["estado"] == "esperando_autorizacion"

        unauth = client.get(ADMIN, headers={"Origin": ORIGIN})
        assert unauth.status_code == 401
        wrong = client.get(ADMIN, headers={"Origin": ORIGIN, "X-API-Key": "incorrecto"})
        assert wrong.status_code == 403

        admin_headers = {"Origin": ORIGIN, "X-API-Key": KEY}
        inbox = client.get(ADMIN, headers=admin_headers)
        assert inbox.status_code == 200
        assert inbox.json()["canDrive"] is False
        assert len(inbox.json()["solicitudes"]) == 1
        assert original["X-Browser-Proposal"] not in inbox.text

        pulse = client.post(ADMIN + "/supervision", headers=admin_headers)
        assert pulse.status_code == 200
        assert pulse.json()["vigencia_s"] == 15
        approve = client.post(
            ADMIN + f"/{row['request_id']}/aprobar",
            headers=admin_headers,
            json={"modo": "timed", "segundos": 120},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["canDrive"] is False
        authorized = client.get(GUEST + "/estado", headers=visitor)
        assert authorized.json()["estado"] == "autorizado"
        assert authorized.json()["canDrive"] is False

        # API de movimiento y DEMO legacy: bloqueadas aun con la clave.
        assert client.post("/vehiculos/1/movimientos",
                           headers=admin_headers, json={"id_comando": 2}).status_code == 503
        assert client.post("/vehiculos/1/demos/1/ejecutar",
                           headers=admin_headers).status_code == 503
        assert client.post("/vehiculos/1/demos/1/cancelar",
                           headers=admin_headers).status_code == 503

        revoked = client.post(ADMIN + "/revocar", headers=admin_headers)
        assert revoked.status_code == 200
        assert revoked.json()["stop_fisico_confirmado"] is False
        assert revoked.json()["canDrive"] is False
        assert client.get(GUEST + "/estado", headers=visitor).json()["estado"] == "revocado_o_caducado"
        assert client.get("/docs").status_code == 200


def test_kx_rejects_invalid_context_and_never_exposes_motion(app):
    with TestClient(app, base_url=HOST) as client:
        headers = identity()
        assert client.post(GUEST, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.post(GUEST, headers={**headers, "Cookie": "sid=x"}).status_code == 403
        assert client.post(GUEST, headers={**headers, "X-API-Key": KEY}).status_code == 403
        assert client.post(GUEST, headers=headers, json={"codigo": 1}).status_code == 400
        assert client.post(GUEST, headers={
            **headers, "X-Browser-Proposal": headers["Idempotency-Key"]
        }).status_code == 428
        assert client.post(GUEST, headers=headers).status_code == 201
        assert client.post(GUEST, headers={
            **headers, "X-Browser-Proposal": token_urlsafe(32)
        }).status_code != 201

        allowed = client.options(GUEST, headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,x-browser-proposal",
        })
        assert allowed.status_code == 200
        assert allowed.headers.get("access-control-allow-origin") == ORIGIN
        evil = client.options(GUEST, headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        assert evil.status_code == 400
        assert client.post(ADMIN + "/accion", headers={"Origin": ORIGIN, "X-API-Key": KEY}).status_code == 404


def test_kx_disabled_by_default_without_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "false")
    get_settings.cache_clear()
    application = create_app()
    with TestClient(application, base_url=HOST) as client:
        assert client.get(GUEST + "/estado", headers={"Origin": ORIGIN}).status_code == 503
        # Las rutas de K-I/K-K ya existentes siguen cerradas.
        assert application.state.kx_enabled is False
    get_settings.cache_clear()


def test_kx_cannot_coexist_with_simulation_or_device_lab(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(tmp_path / "stage.sqlite"))
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        create_app()
    get_settings.cache_clear()
