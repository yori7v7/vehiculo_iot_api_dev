"""K-V: pruebas ASGI de futuro staging, NO pruebas de Internet ni de motores."""
from __future__ import annotations

from pathlib import Path
from secrets import token_urlsafe
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.public_control.kv_virtual_staging import create_kv_virtual_app


ADMIN = "administrador-virtual-tests-" + "A" * 48
PROXY = "proxy-caddy-ficticio-tests-" + "P" * 48
PAGES = "https://yori7v7.github.io"
BASE = "https://100-30-4-62.nip.io"
REQUEST = "/publico/vehiculos/1/solicitudes"
INBOX = "/admin/vehiculos/1/control-publico/solicitudes"
HEAD = {
    "Host": "100-30-4-62.nip.io",
    "Origin": PAGES,
    "X-Admission-Proxy-Token": PROXY,
    "X-Admission-Client-IP": "8.8.8.8",
    "X-Admission-Scheme": "https",
}
AUTH = {**HEAD, "X-API-Key": ADMIN}


class Clock:
    value = 1000.0

    def __call__(self):
        return self.value


def factory(tmp_path, monkeypatch, *, name="private.sqlite3", clock=None, **kwargs):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    return create_kv_virtual_app(
        tmp_path / name, ADMIN, PROXY, clock=clock or Clock(), **kwargs
    )


def browser(app, address="127.0.0.1"):
    return TestClient(app, base_url=BASE, client=(address, 51020))


def identity():
    return {**HEAD, "Idempotency-Key": token_urlsafe(32),
            "X-Browser-Proposal": token_urlsafe(32)}


def test_kv_rejects_start_without_explicit_virtual_staging(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ADMISSION_VIRTUAL_ONLY", raising=False)
    with pytest.raises(ValueError):
        create_kv_virtual_app(tmp_path / "stage.sqlite3", ADMIN, PROXY)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    with pytest.raises(ValueError):
        create_kv_virtual_app(tmp_path / "stage.sqlite3", ADMIN, PROXY)
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValueError):
        create_kv_virtual_app(tmp_path / "stage.sqlite3", ADMIN, ADMIN)


def test_kv_virtual_flow_multiple_sessions_replay_and_revoke(tmp_path, monkeypatch):
    instance = factory(tmp_path, monkeypatch)
    headers = identity()
    with browser(instance) as client:
        first = client.post(REQUEST, headers=headers)
        assert first.status_code == 201
        row = first.json()
        assert row["estado"] == "esperando_autorizacion"
        assert row["browser_secret"] == headers["X-Browser-Proposal"]
        assert row["canDrive"] is False and row["control_fisico"] is False
        retry = client.post(REQUEST, headers=headers)
        assert retry.status_code == 200
        assert retry.json()["request_id"] == row["request_id"]
        assert retry.json()["idempotent_replay"] is True
        assert client.get(INBOX, headers=HEAD).status_code == 401
        assert client.get(INBOX, headers={**HEAD, "X-API-Key": "falso"}).status_code == 403
        inbox = client.get(INBOX, headers=AUTH)
        assert inbox.status_code == 200
        assert len(inbox.json()["solicitudes"]) == 1
        assert headers["X-Browser-Proposal"] not in inbox.text
        assert inbox.json()["canDrive"] is False
        assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200
        approval = client.post(
            INBOX + f"/{row['request_id']}/aprobar",
            headers=AUTH, json={"modo": "timed", "segundos": 60}
        )
        assert approval.status_code == 200
        assert approval.json()["canDrive"] is False
        guest_headers = {**HEAD, "X-Browser-Session": row["browser_secret"]}
        approved = client.get(REQUEST + "/estado", headers=guest_headers)
        assert approved.status_code == 200
        assert approved.json()["estado"] == "autorizado"
        assert approved.json()["canDrive"] is False
        assert client.post(REQUEST, headers=headers).status_code == 409
        revoked = client.post(INBOX + "/revocar", headers=AUTH)
        assert revoked.status_code == 200
        assert revoked.json()["stop_fisico_confirmado"] is False
        assert client.get(REQUEST + "/estado", headers=guest_headers).json()["estado"] == "revocado_o_caducado"
        for path in ("/docs", "/openapi.json", "/vehiculos/1/movimientos",
                     "/ws/vehiculos/1", "/publico/vehiculos/1/sesion/acciones"):
            assert client.post(path, headers=AUTH).status_code == 404
        assert revoked.headers["cache-control"] == "no-store"


def test_kv_proxy_boundary_rejects_headers_and_non_loopback(tmp_path, monkeypatch):
    instance = factory(tmp_path, monkeypatch)
    with browser(instance) as client:
        invalid = [
            {**HEAD, "Host": "attacker.example"},
            {**HEAD, "Origin": "https://attacker.example"},
            {**HEAD, "X-Admission-Proxy-Token": "fake"},
            {**HEAD, "X-Admission-Client-IP": "127.0.0.1"},
            {**HEAD, "X-Admission-Client-IP": "192.168.1.33"},
            {**HEAD, "X-Admission-Client-IP": "bad.ip"},
            {**HEAD, "X-Admission-Scheme": "http"},
            {**HEAD, "X-Forwarded-For": "8.8.8.8"},
            {**HEAD, "X-Forwarded-Proto": "https"},
            {**HEAD, "Cookie": "admin=1"},
            {**HEAD, "Authorization": "Bearer x"},
            {**HEAD, "X-API-Key": ADMIN},
        ]
        for h in invalid:
            assert client.post(REQUEST, headers=h).status_code in (403, 400), h
        assert client.post(REQUEST + "?x=1", headers=identity()).status_code == 403
        assert client.post(REQUEST, headers=identity(), json={"move": 1}).status_code == 400
        remote = browser(instance, "192.168.1.2")
        assert remote.post(REQUEST, headers=identity()).status_code == 403
        assert client.get(INBOX, headers=AUTH).json()["solicitudes"] == []


def test_kv_validates_keys_duplicate_expiration_and_quota(tmp_path, monkeypatch):
    clock = Clock()
    instance = factory(tmp_path, monkeypatch, clock=clock, pending_ttl=20,
                       max_per_client=1)
    with browser(instance) as c:
        a = identity()
        assert c.post(REQUEST, headers=HEAD).status_code == 428
        assert c.post(REQUEST, headers={**a, "X-Browser-Proposal": "bad"}).status_code == 428
        assert c.post(REQUEST, headers={**a,
                      "X-Browser-Proposal": a["Idempotency-Key"]}).status_code == 428
        assert c.post(REQUEST, headers=a).status_code == 201
        assert c.post(REQUEST, headers=a).status_code == 200
        assert c.post(REQUEST, headers=identity()).status_code == 429
        clock.value = 1020
        assert c.post(REQUEST, headers=a).status_code == 409
        guest = {**HEAD, "X-Browser-Session": a["X-Browser-Proposal"]}
        assert c.get(REQUEST + "/estado", headers=guest).json()["estado"] == "revocado_o_caducado"


def test_kv_restart_prevents_replay_and_revives_no_tickets(tmp_path, monkeypatch):
    clock = Clock()
    one = factory(tmp_path, monkeypatch, clock=clock)
    idem = identity()
    with browser(one) as c:
        old = c.post(REQUEST, headers=idem).json()
        assert old["canDrive"] is False
    two = factory(tmp_path, monkeypatch, clock=clock)
    with browser(two) as c:
        assert c.post(REQUEST, headers=idem).status_code == 409
        old_session = {**HEAD, "X-Browser-Session": old["browser_secret"]}
        assert c.get(REQUEST + "/estado", headers=old_session).status_code == 401
        assert c.get(INBOX, headers=AUTH).json()["solicitudes"] == []
    with sqlite3.connect(tmp_path / "private.sqlite3") as db:
        status = db.execute(
            "SELECT state FROM kr_ticket WHERE request_id=?",
            (old["request_id"],)
        ).fetchone()[0]
        assert status == "revoked"


def test_kv_cors_and_no_motor_wiring_in_source(tmp_path, monkeypatch):
    instance = factory(tmp_path, monkeypatch)
    with browser(instance) as c:
        allowed = c.options(REQUEST, headers={
            "Origin": PAGES, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,x-browser-proposal",
        })
        assert allowed.status_code == 200
        assert allowed.headers.get("access-control-allow-origin") == PAGES
        evil = c.options(REQUEST, headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        assert evil.status_code == 400
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/public_control/kv_virtual_staging.py").read_text("utf-8")
    assert "KRTicketLedger" in source
    assert "kc_module" not in source
    assert "controller.dispatch" not in source
    for name in ("app/main.py", "app/public_control/kg_bootstrap.py",
                 "app/public_control/kf_bridge.py"):
        assert "kv_virtual_staging" not in (root / name).read_text("utf-8")
