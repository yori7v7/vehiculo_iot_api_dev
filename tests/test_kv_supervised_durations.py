"""K-V: duraciones virtuales y revocación sin acceso físico, solo CI."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.public_control.kq_restart_fence import KQRestartFence
from app.public_control.kr_ticket_ledger import KRTicketDenied, KRTicketLedger
from app.public_control.kv_virtual_staging import create_kv_virtual_app


ADMIN = "kv-test-administrador-" + "K" * 43
PROXY = "kv-test-caddy-" + "P" * 43
BASE = "https://100-30-4-62.nip.io"
GUEST = "/publico/vehiculos/1/solicitudes"
INBOX = "/admin/vehiculos/1/control-publico/solicitudes"
HEADERS = {
    "Host": "100-30-4-62.nip.io",
    "Origin": "https://yori7v7.github.io",
    "X-Admission-Proxy-Token": PROXY,
    "X-Admission-Client-IP": "8.8.8.8",
    "X-Admission-Scheme": "https",
}
AUTH = {**HEADERS, "X-API-Key": ADMIN}


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def tick(self, seconds):
        self.value += seconds


def new_ledger(path, clock, epoch=1):
    fence = KQRestartFence(path)
    assert fence.start() == epoch
    ledger = KRTicketLedger(fence, epoch, ADMIN, clock=clock)
    ledger.prepare()
    return fence, ledger


@pytest.mark.parametrize("duration", [120, 300, 600, 1200])
def test_timed_lease_expires_at_its_absolute_deadline(tmp_path, duration):
    clock = Clock()
    fence, ledger = new_ledger(tmp_path / "timed.sqlite", clock)
    ticket = ledger.request("client-" + str(duration))
    ledger.supervise(ADMIN)
    assert ledger.approve_virtual(
        ADMIN, ticket["request_id"], mode="timed", seconds=duration
    )["canDrive"] is False

    # Seguir supervisando NO prolonga el vencimiento absoluto.
    elapsed = 0
    while elapsed + 5 < duration:
        clock.tick(5)
        elapsed += 5
        ledger.supervise(ADMIN)
    assert ledger.status(ticket["browser_secret"])["estado"] == "autorizado_virtual"
    clock.tick(duration - elapsed)
    assert ledger.status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    with pytest.raises(KRTicketDenied):
        ledger.verify_virtual_action(ticket["browser_secret"])
    fence.close()


def test_supervised_lease_renews_but_never_survives_lost_heartbeat(tmp_path):
    clock = Clock()
    fence, ledger = new_ledger(tmp_path / "indef.sqlite", clock)
    ticket = ledger.request("profesor")
    ledger.supervise(ADMIN)
    assert ledger.approve_virtual(
        ADMIN, ticket["request_id"], mode="supervised", seconds=None
    )["canDrive"] is False

    for _ in range(250):  # Mas de 20 min, solo mientras hay supervisión.
        clock.tick(5)
        ledger.supervise(ADMIN)
    assert ledger.status(ticket["browser_secret"])["estado"] == "autorizado_virtual"
    assert ledger.verify_virtual_action(ticket["browser_secret"]) is True

    clock.tick(15)
    assert ledger.status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    ledger.supervise(ADMIN)  # Un heartbeat tardío NO lo reanima.
    assert ledger.status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    fence.close()


def test_supervised_revoke_is_final_and_other_guest_waits(tmp_path):
    clock = Clock()
    fence, ledger = new_ledger(tmp_path / "revoke.sqlite", clock)
    a = ledger.request("A")
    b = ledger.request("B")
    ledger.supervise(ADMIN)
    ledger.approve_virtual(ADMIN, a["request_id"], mode="supervised", seconds=None)
    with pytest.raises(KRTicketDenied):
        ledger.approve_virtual(ADMIN, b["request_id"], seconds=300)
    ledger.revoke(ADMIN)
    ledger.supervise(ADMIN)
    assert ledger.status(a["browser_secret"])["estado"] == "revocado_o_caducado"
    assert ledger.status(b["browser_secret"])["estado"] == "revocado_o_caducado"
    with pytest.raises(KRTicketDenied):  # Revocar cancela también las pendientes.
        ledger.approve_virtual(ADMIN, b["request_id"], seconds=300)
    fresh = ledger.request("C")
    ledger.approve_virtual(ADMIN, fresh["request_id"], seconds=300)
    assert ledger.status(fresh["browser_secret"])["estado"] == "autorizado_virtual"
    fence.close()


def test_legacy_sqlite_mode_column_migrates_without_resurrecting_turn(tmp_path):
    path = tmp_path / "migration.sqlite"
    clock = Clock()
    one, ledger = new_ledger(path, clock)
    ticket = ledger.request("viejo")
    ledger.supervise(ADMIN)
    ledger.approve_virtual(ADMIN, ticket["request_id"], seconds=120)
    one.close()
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE kr_ticket DROP COLUMN approval_mode")
        db.commit()
    two, restarted = new_ledger(path, clock, epoch=2)
    with sqlite3.connect(path) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(kr_ticket)")}
        assert "approval_mode" in columns
        stale = db.execute(
            "SELECT state, virtual_until FROM kr_ticket WHERE request_id=?",
            (ticket["request_id"],),
        ).fetchone()
        assert stale == ("revoked", None)
    with pytest.raises(KRTicketDenied):
        restarted.status(ticket["browser_secret"])
    two.close()


def test_http_contract_rejects_inconsistent_modes_and_never_drives(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    clock = Clock()
    app = create_kv_virtual_app(
        tmp_path / "api.sqlite", ADMIN, PROXY, clock=clock,
    )
    import secrets
    with TestClient(app, base_url=BASE, client=("127.0.0.1", 51200)) as client:
        headers = {
            **HEADERS,
            "Idempotency-Key": secrets.token_urlsafe(32),
            "X-Browser-Proposal": secrets.token_urlsafe(32),
        }
        ticket = client.post(GUEST, headers=headers)
        assert ticket.status_code == 201
        row = ticket.json()
        endpoint = INBOX + "/" + row["request_id"] + "/aprobar"
        assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200

        for invalid in (
            {"modo": "timed", "segundos": 1201},
            {"modo": "timed", "segundos": 0},
            {"modo": "timed"},
            {"modo": "supervised", "segundos": 120},
            {"modo": "supervised", "segundos": None},
            {"modo": "indefinite"},
            {"modo": "timed", "segundos": True},
            {"modo": "timed", "segundos": "600"},
        ):
            result = client.post(endpoint, headers=AUTH, json=invalid)
            assert result.status_code == 422, (invalid, result.status_code)

        ok = client.post(endpoint, headers=AUTH, json={"modo": "supervised"})
        assert ok.status_code == 200
        assert ok.json()["canDrive"] is False
        secret = {**HEADERS, "X-Browser-Session": row["browser_secret"]}
        assert client.get(GUEST + "/estado", headers=secret).json()["estado"] == "autorizado"
        clock.tick(16)
        assert client.get(GUEST + "/estado", headers=secret).json()["estado"] == "revocado_o_caducado"
        assert client.post(INBOX + "/supervision", headers=AUTH).status_code == 200
        assert client.get(GUEST + "/estado", headers=secret).json()["estado"] == "revocado_o_caducado"
