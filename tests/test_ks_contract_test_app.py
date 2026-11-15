"""K-S: contrato HTTPS aislado; ninguna ruta controla actuadores ni AWS."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.public_control.ks_contract_test_app import create_ks_contract_test_app


HOST = "ks.localhost:9443"
BASE = "https://" + HOST
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGIN = "https://yori7v7.github.io"
KEY = "clave-admin-solo-tests-KS-" + "x" * 42
GUEST_HEADERS = {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}
ADMIN_HEADERS = {**GUEST_HEADERS, "X-API-Key": KEY}


class Clock:
    def __init__(self, now=1000):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, value):
        self.now += value


def app(tmp_path, *, clock=None, **kwargs):
    return create_ks_contract_test_app(tmp_path / "ks.sqlite3", KEY,
                                       clock=clock or Clock(), **kwargs)


def client_of(app, ip="127.0.0.1"):
    return TestClient(app, base_url=BASE, client=(ip, 54321))


def test_ks_complete_guest_admin_contract_without_motor(tmp_path):
    instance = app(tmp_path)
    with client_of(instance) as client:
        pending = client.post(GUEST, headers=GUEST_HEADERS)
        assert pending.status_code == 201
        issued = pending.json()
        assert issued["estado"] == "esperando_autorizacion"
        assert len(issued["browser_secret"]) == 43
        assert issued["canDrive"] is False and issued["control_fisico"] is False

        guest = {**GUEST_HEADERS, "X-Browser-Session": issued["browser_secret"]}
        waiting = client.get(GUEST + "/estado", headers=guest)
        assert waiting.status_code == 200
        assert waiting.json()["estado"] == "esperando_autorizacion"
        assert waiting.json()["canDrive"] is False

        queue = client.get(ADMIN, headers=ADMIN_HEADERS)
        assert queue.status_code == 200
        assert queue.json()["solicitudes"][0]["request_id"] == issued["request_id"]
        assert issued["browser_secret"] not in queue.text
        assert queue.json()["turno_activo"] is False

        assert client.post(ADMIN + "/supervision", headers=ADMIN_HEADERS).json()["vigencia_s"] == 15
        approval = client.post(
            ADMIN + "/" + issued["request_id"] + "/aprobar",
            headers=ADMIN_HEADERS, json={"modo": "timed", "segundos": 120}
        )
        assert approval.status_code == 200
        assert approval.json()["aprobada"] is True
        assert approval.json()["canDrive"] is False
        assert client.get(GUEST + "/estado", headers=guest).json()["estado"] == "autorizado"
        assert client.get(ADMIN, headers=ADMIN_HEADERS).json()["turno_activo"] is True

        revocation = client.post(ADMIN + "/revocar", headers=ADMIN_HEADERS)
        assert revocation.status_code == 200
        assert revocation.json()["stop_fisico_confirmado"] is False
        assert revocation.json()["revocado"] is True
        assert client.get(GUEST + "/estado", headers=guest).json()["estado"] == "revocado_o_caducado"
        assert client.get(ADMIN, headers=ADMIN_HEADERS).json()["solicitudes"] == []
        assert client.get(ADMIN, headers=ADMIN_HEADERS).json()["turno_activo"] is False
        for forbidden in ("/ws/dispositivos-lab/1/contrato", "/vehiculos/1/movimientos",
                          "/publico/vehiculos/1/sesion/acciones", "/docs",
                          "/admin/vehiculos/1/control-publico/ventana"):
            assert client.post(forbidden, headers=ADMIN_HEADERS).status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health/database").status_code == 404
        assert revocation.headers["cache-control"] == "no-store"
        assert revocation.headers["referrer-policy"] == "no-referrer"


def test_ks_rejects_wrong_origin_proxy_lan_api_key_leaks(tmp_path):
    instance = app(tmp_path)
    with client_of(instance) as c:
        bads = [
            {"Origin": "https://evil.test"},
            {**GUEST_HEADERS, "Host": "attacker.test"},
            {**GUEST_HEADERS, "X-Forwarded-For": "127.0.0.1"},
            {**GUEST_HEADERS, "Forwarded": "for=127.0.0.1"},
            {**GUEST_HEADERS, "Via": "1.1 proxy"},
            {**GUEST_HEADERS, "Cookie": "admin=1"},
            {**GUEST_HEADERS, "Authorization": "Bearer shared"},
            {**GUEST_HEADERS, "X-API-Key": KEY},
            {**GUEST_HEADERS, "X-Browser-Session": "x" * 43},
        ]
        for headers in bads:
            assert c.post(GUEST, headers=headers).status_code == 403, headers
        assert c.post(GUEST + "?hack=1", headers=GUEST_HEADERS).status_code == 403
        assert c.post(GUEST, headers=GUEST_HEADERS, json={"x": 1}).status_code == 400
        assert c.post(GUEST.replace("/1/", "/2/"), headers=GUEST_HEADERS).status_code == 403
        assert c.get(ADMIN, headers=GUEST_HEADERS).status_code == 401
        assert c.get(ADMIN, headers={**GUEST_HEADERS, "X-API-Key": "falsa"}).status_code == 403
        assert c.get(ADMIN, headers={**ADMIN_HEADERS, "X-Browser-Session": "x" * 43}).status_code == 403
        assert c.get(GUEST + "/estado", headers=GUEST_HEADERS).status_code == 401
        assert c.post(ADMIN + "/revocar", headers=GUEST_HEADERS).status_code == 401

        remote = client_of(instance, "192.168.1.181")
        assert remote.post(GUEST, headers=GUEST_HEADERS).status_code == 403
        assert remote.get(ADMIN, headers=ADMIN_HEADERS).status_code == 403

        preflight = c.options(
            GUEST, headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == ORIGIN
        assert "access-control-allow-credentials" not in preflight.headers
        evil = c.options(
            GUEST, headers={"Origin": "https://evil.test",
                            "Access-Control-Request-Method": "POST"}
        )
        assert evil.status_code == 400


def test_ks_reject_double_approval_while_guest_remains_virtual(tmp_path):
    instance = app(tmp_path)
    with client_of(instance) as c:
        a = c.post(GUEST, headers=GUEST_HEADERS).json()
        b = c.post(GUEST, headers=GUEST_HEADERS).json()
        assert c.post(ADMIN + "/supervision", headers=ADMIN_HEADERS).status_code == 200
        first = ADMIN + "/" + a["request_id"] + "/aprobar"
        second = ADMIN + "/" + b["request_id"] + "/aprobar"
        assert c.post(first, headers=ADMIN_HEADERS,
                      json={"modo": "timed", "segundos": 120}).status_code == 200
        assert c.post(second, headers=ADMIN_HEADERS,
                      json={"modo": "timed", "segundos": 120}).status_code == 409
        assert c.post(first, headers=ADMIN_HEADERS,
                      json={"modo": "timed", "segundos": 120}).status_code == 409
        assert c.post(second, headers=ADMIN_HEADERS,
                      json={"modo": "supervised"}).status_code == 422
        assert c.post(second, headers=ADMIN_HEADERS,
                      json={"modo": "timed", "segundos": 300}).status_code == 422
        assert c.post(ADMIN + "/revocar", headers=ADMIN_HEADERS).status_code == 200
        assert c.get(ADMIN, headers=ADMIN_HEADERS).json()["turno_activo"] is False
        assert c.get(GUEST + "/estado", headers={**GUEST_HEADERS,
                     "X-Browser-Session": a["browser_secret"]}).json()["canDrive"] is False


def test_ks_restart_invalidates_old_ticket_but_keeps_rate_budget(tmp_path):
    clock = Clock()
    path = tmp_path / "ks.sqlite3"
    first = create_ks_contract_test_app(path, KEY, clock=clock, max_per_client=1)
    with client_of(first) as c:
        ticket = c.post(GUEST, headers=GUEST_HEADERS).json()
        c.post(ADMIN + "/supervision", headers=ADMIN_HEADERS)
        assert c.post(ADMIN + "/" + ticket["request_id"] + "/aprobar",
                      headers=ADMIN_HEADERS, json={"modo": "timed",
                                                  "segundos": 120}).status_code == 200
    second = create_ks_contract_test_app(path, KEY, clock=clock, max_per_client=1)
    with client_of(second) as c:
        old = {**GUEST_HEADERS, "X-Browser-Session": ticket["browser_secret"]}
        assert c.get(GUEST + "/estado", headers=old).status_code == 401
        assert c.get(ADMIN, headers=ADMIN_HEADERS).json()["turno_activo"] is False
        assert c.post(GUEST, headers=GUEST_HEADERS).status_code == 429
        with sqlite3.connect(path) as db:
            old_state = db.execute(
                "SELECT state FROM kr_ticket WHERE request_id=?",
                (ticket["request_id"],)
            ).fetchone()[0]
            assert old_state == "revoked"
        clock.advance(301)
        assert c.post(GUEST, headers=GUEST_HEADERS).status_code == 201


def test_ks_expiration_rejection_clock_rollback_and_permanent_fail_closed(tmp_path):
    clock = Clock()
    instance = app(tmp_path, clock=clock, pending_ttl=20)
    with client_of(instance) as c:
        ticket = c.post(GUEST, headers=GUEST_HEADERS).json()
        session = {**GUEST_HEADERS, "X-Browser-Session": ticket["browser_secret"]}
        clock.advance(20)
        assert c.get(GUEST + "/estado", headers=session).json()["estado"] == "revocado_o_caducado"
        assert c.post(ADMIN + "/supervision", headers=ADMIN_HEADERS).status_code == 200
        assert c.post(ADMIN + "/" + ticket["request_id"] + "/aprobar",
                      headers=ADMIN_HEADERS, json={"modo": "timed",
                                                  "segundos": 120}).status_code == 409
        assert c.post(GUEST, headers=GUEST_HEADERS).status_code == 201
        clock.advance(-1)
        assert c.get(ADMIN, headers=ADMIN_HEADERS).status_code == 503
        assert c.post(GUEST, headers=GUEST_HEADERS).status_code == 429
        clock.advance(2)
        assert c.get(ADMIN, headers=ADMIN_HEADERS).status_code == 503


def test_ks_no_startup_if_production_or_db_inside_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        create_ks_contract_test_app(tmp_path / "ks.sqlite3", KEY)
    monkeypatch.delenv("APP_ENV")
    repo_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError):
        create_ks_contract_test_app(repo_root / "ks.sqlite3", KEY)


def test_ks_contract_not_auto_wired_into_main_or_kg():
    repo_root = Path(__file__).resolve().parents[1]
    for path in ("app/main.py", "app/public_control/kg_bootstrap.py",
                 "app/public_control/ki_ingress.py", "app/public_control/kk_admin_lab.py"):
        text = (repo_root / path).read_text(encoding="utf-8")
        assert "ks_contract_test_app" not in text
    app_file = (repo_root / "app/public_control/ks_contract_test_app.py").read_text(encoding="utf-8")
    assert "await controller.dispatch(" not in app_file
    assert "/sesion/acciones" not in app_file
    assert "websocket" not in app_file.lower()
