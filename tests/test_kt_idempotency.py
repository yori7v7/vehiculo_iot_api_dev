"""K-T: idempotencia de la solicitud de visitante en el contrato ASGI aislado.

Sin AWS, WSS, ESP ni motores; solo pruebas en memoria con SQLite temporal.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from secrets import token_urlsafe

from fastapi.testclient import TestClient

from app.public_control.ks_contract_test_app import create_ks_contract_test_app


BASE = "https://ks.localhost:9443"
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGIN = "https://yori7v7.github.io"
ADMIN_KEY = "k" * 64
HEAD = {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}
ADM = {**HEAD, "X-API-Key": ADMIN_KEY}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def app(tmp_path, clock=None, **kw):
    return create_ks_contract_test_app(
        tmp_path / "kt-ledger.sqlite3",
        ADMIN_KEY, clock=clock or Clock(),
        kt_idempotency_required=True, **kw,
    )


def headers(key=None, proposal=None):
    return {**HEAD, "Idempotency-Key": key or token_urlsafe(32),
            "X-Browser-Proposal": proposal or token_urlsafe(32)}


def tc(instance, ip="127.0.0.1"):
    return TestClient(instance, base_url=BASE, client=(ip, 50000))


def test_kt_lost_response_replayed_without_duplicate_or_second_rate_charge(tmp_path):
    instance = app(tmp_path, max_per_client=1)
    request_headers = headers()
    with tc(instance) as client:
        # Simular respuesta HTTP que el navegador nunca recibió.
        first_response = client.post(GUEST, headers=request_headers)
        first = first_response.json()
        assert first_response.status_code == 201
        assert first["idempotent_replay"] is False
        assert first["canDrive"] is False
        assert first["browser_secret"] == request_headers["X-Browser-Proposal"]
        # La repetición no suma al contador por cliente, incluso si ya agotó cuota.
        second_response = client.post(GUEST, headers=request_headers)
        second = second_response.json()
        assert second_response.status_code == 200
        assert second["idempotent_replay"] is True
        assert second["request_id"] == first["request_id"]
        assert second["display_code"] == first["display_code"]
        assert second["browser_secret"] == first["browser_secret"]
        assert second["canDrive"] is False
        assert len(client.get(ADMIN, headers=ADM).json()["solicitudes"]) == 1
        assert client.post(GUEST, headers=headers()).status_code == 429

    db = tmp_path / "kt-ledger.sqlite3"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM kr_ticket").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM kt_idempotency").fetchone()[0] == 1
        assert len(conn.execute("SELECT key_digest FROM kt_idempotency").fetchone()[0]) == 32
    assert request_headers["Idempotency-Key"].encode() not in db.read_bytes()
    assert request_headers["X-Browser-Proposal"].encode() not in db.read_bytes()


def test_kt_conflicts_wrong_secret_different_key_or_different_client(tmp_path):
    instance = app(tmp_path)
    original = headers()
    with tc(instance) as client:
        first = client.post(GUEST, headers=original)
        assert first.status_code == 201
        mismatch = {**original, "X-Browser-Proposal": token_urlsafe(32)}
        assert client.post(GUEST, headers=mismatch).status_code == 409
        reused_secret = {**original, "Idempotency-Key": token_urlsafe(32)}
        assert client.post(GUEST, headers=reused_secret).status_code == 409
        # Dos clientes sobre EL MISMO ASGI activo, sin iniciar otro lifespan
        # ni disputar el mismo propietario de SQLite (protección K-Q).
        another_ip = tc(instance, "::1")
        assert another_ip.post(GUEST, headers=original).status_code == 409
        assert len(client.get(ADMIN, headers=ADM).json()["solicitudes"]) == 1
        assert client.post(GUEST, headers=original).status_code == 200


def test_kt_requires_complete_unique_headers_and_does_not_store_on_errors(tmp_path):
    instance = app(tmp_path)
    with tc(instance) as client:
        assert client.post(GUEST, headers=HEAD).status_code == 428
        assert client.post(GUEST, headers={**HEAD, "Idempotency-Key": token_urlsafe(32)}).status_code == 400
        assert client.post(GUEST, headers={**HEAD, "X-Browser-Proposal": token_urlsafe(32)}).status_code == 400
        both = token_urlsafe(32)
        assert client.post(GUEST, headers=headers(both, both)).status_code == 400
        assert client.post(GUEST, headers=headers("x" * 42)).status_code == 400
        assert client.post(GUEST, headers={**headers(), "Authorization": "Bearer test"}).status_code == 403
        assert client.post(GUEST, headers={**headers(), "X-API-Key": ADMIN_KEY}).status_code == 403
        assert client.post(GUEST, headers={**headers(), "X-Forwarded-For": "127.0.0.1"}).status_code == 403
        assert client.get(ADMIN, headers=ADM).json()["solicitudes"] == []


def test_kt_expiration_and_approval_never_recover_access_on_replay(tmp_path):
    clock = Clock()
    instance = app(tmp_path, clock=clock, pending_ttl=20)
    with tc(instance) as client:
        expired_headers = headers()
        first = client.post(GUEST, headers=expired_headers).json()
        clock.advance(20)
        assert client.post(GUEST, headers=expired_headers).status_code == 409
        state = client.get(GUEST + "/estado", headers={
            **HEAD, "X-Browser-Session": first["browser_secret"]
        })
        assert state.status_code == 200
        assert state.json()["estado"] == "revocado_o_caducado"
        approved_headers = headers()
        current = client.post(GUEST, headers=approved_headers).json()
        assert client.post(ADMIN + "/supervision", headers=ADM).status_code == 200
        assert client.post(ADMIN + "/" + current["request_id"] + "/aprobar",
                           headers=ADM, json={"modo": "timed", "segundos": 120}).status_code == 200
        assert client.post(GUEST, headers=approved_headers).status_code == 409
        assert client.get(GUEST + "/estado", headers={
            **HEAD, "X-Browser-Session": current["browser_secret"]
        }).json()["canDrive"] is False
        assert client.post(ADMIN + "/revocar", headers=ADM).status_code == 200
        assert client.post(GUEST, headers=approved_headers).status_code == 409


def test_kt_restart_never_replays_old_epoch_and_retains_request_limits(tmp_path):
    clock = Clock()
    identity = headers()
    db = tmp_path / "kt-ledger.sqlite3"
    first = app(tmp_path, clock=clock, max_per_client=1)
    with tc(first) as client:
        old = client.post(GUEST, headers=identity)
        assert old.status_code == 201
        old_id = old.json()["request_id"]
    second = app(tmp_path, clock=clock, max_per_client=1)
    with tc(second) as client:
        assert client.post(GUEST, headers=identity).status_code == 409
        assert client.post(GUEST, headers=headers()).status_code == 429
        assert client.get(ADMIN, headers=ADM).json()["solicitudes"] == []
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT state FROM kr_ticket WHERE request_id=?",
                                (old_id,)).fetchone()[0] == "revoked"
        clock.advance(301)
        assert client.post(GUEST, headers=headers()).status_code == 201


def test_kt_concurrent_duplicate_has_exactly_one_ticket(tmp_path):
    instance = app(tmp_path, max_per_client=1)
    identity = headers()
    with tc(instance) as client:
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: client.post(GUEST, headers=identity), range(6)))
        assert [r.status_code for r in results].count(201) == 1
        assert [r.status_code for r in results].count(200) == 5
        ids = {r.json()["request_id"] for r in results}
        assert len(ids) == 1
        assert all(r.json()["canDrive"] is False for r in results)
        assert len(client.get(ADMIN, headers=ADM).json()["solicitudes"]) == 1


def test_kt_legacy_ks_support_is_explicitly_not_a_production_guarantee(tmp_path):
    """Solo la bandera de prueba nueva exige cabeceras; K-S legado permanece aislado."""
    from app.public_control.ks_contract_test_app import create_ks_contract_test_app
    legacy = create_ks_contract_test_app(
        tmp_path / "ks-legacy.sqlite3", ADMIN_KEY, clock=Clock()
    )
    with tc(legacy) as client:
        a = client.post(GUEST, headers=HEAD)
        b = client.post(GUEST, headers=HEAD)
        assert a.status_code == b.status_code == 201
        assert a.json()["request_id"] != b.json()["request_id"]
        assert a.json()["canDrive"] is b.json()["canDrive"] is False
