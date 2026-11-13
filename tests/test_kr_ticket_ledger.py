"""K-R: tickets durables, secretos opacos y sesiones de solo laboratorio."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest

from app.public_control.kq_restart_fence import KQRestartFence, FenceRejected
from app.public_control.kr_ticket_ledger import KRTicketLedger, KRTicketDenied
from app.public_control.repository import StoreUnavailable


ADMIN = "administrador-ficticio-kr-" + "X" * 40


class Clock:
    def __init__(self, when=1000):
        self.now = float(when)

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def create(path, *, epoch=1, clock=None, **kwargs):
    fence = KQRestartFence(path)
    assert fence.start() == epoch
    timer = clock or Clock()
    ledger = KRTicketLedger(fence, epoch, ADMIN, clock=timer, **kwargs)
    ledger.prepare()
    return fence, ledger, timer


def test_kr_request_persists_only_secret_hash_and_never_bearer(tmp_path):
    path = tmp_path / "kr.sqlite3"
    fence, ledger, clock = create(path)
    ticket = ledger.request("visitante-uno")
    assert ticket["estado"] == "esperando_autorizacion"
    assert ticket["simulado"] and not ticket["control_fisico"]
    assert ticket["canDrive"] is False
    assert len(ticket["browser_secret"]) == 43
    assert ledger.status(ticket["browser_secret"])["estado"] == "esperando_autorizacion"
    with pytest.raises(KRTicketDenied):
        ledger.status("secreto-incorrecto")
    assert len(ledger.snapshot(ADMIN)["solicitudes"]) == 1
    assert ticket["browser_secret"] not in str(ledger.snapshot(ADMIN))
    with sqlite3.connect(path) as db:
        values = db.execute("SELECT browser_hash, client_digest FROM kr_ticket").fetchone()
        assert values[0] == sha256(ticket["browser_secret"].encode()).digest()
        assert len(values[0]) == len(values[1]) == 32
        assert ticket["browser_secret"].encode() not in path.read_bytes()
        assert b"visitante-uno" not in path.read_bytes()
    fence.close()


def test_kr_rejects_duplicate_virtual_approval_and_expires_by_supervisor(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr2.sqlite3")
    a, b = ledger.request("cliente-a"), ledger.request("cliente-b")
    with pytest.raises(KRTicketDenied):
        ledger.approve_virtual(ADMIN, a["request_id"])
    ledger.supervise(ADMIN)
    assert ledger.approve_virtual(ADMIN, a["request_id"])["aprobada_virtual"]
    assert ledger.status(a["browser_secret"])["estado"] == "autorizado_virtual"
    assert ledger.status(a["browser_secret"])["canDrive"] is False
    with pytest.raises(KRTicketDenied):
        ledger.approve_virtual(ADMIN, b["request_id"])
    clock.tick(15)
    assert ledger.status(a["browser_secret"])["estado"] == "revocado_o_caducado"
    ledger.supervise(ADMIN)
    assert ledger.approve_virtual(ADMIN, b["request_id"])["aprobada_virtual"]
    ledger.revoke(ADMIN)
    assert ledger.status(b["browser_secret"])["estado"] == "revocado_o_caducado"
    assert ledger.snapshot(ADMIN)["turno_virtual_activo"] is False
    fence.close()


def test_kr_request_expiry_and_deny_do_not_return_old_permission(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr3.sqlite3", pending_ttl=30)
    a = ledger.request("persona")
    ledger.reject(ADMIN, a["request_id"])
    assert ledger.status(a["browser_secret"])["estado"] == "revocado_o_caducado"
    b = ledger.request("persona")
    clock.tick(30)
    assert ledger.status(b["browser_secret"])["estado"] == "revocado_o_caducado"
    ledger.supervise(ADMIN)
    with pytest.raises(KRTicketDenied):
        ledger.approve_virtual(ADMIN, b["request_id"])
    fence.close()


def test_kr_limits_by_client_and_global_are_enforced_transactionally(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr4.sqlite3", max_pending=5,
                                  max_per_client=2, max_per_window=3)
    ledger.request("A")
    ledger.request("A")
    with pytest.raises(KRTicketDenied, match="Limite"):
        ledger.request("A")
    ledger.request("B")
    with pytest.raises(KRTicketDenied, match="Limite"):
        ledger.request("C")
    assert len(ledger.snapshot(ADMIN)["solicitudes"]) == 3
    clock.tick(301)
    assert ledger.snapshot(ADMIN)["solicitudes"] == []
    assert ledger.request("A")["estado"] == "esperando_autorizacion"
    fence.close()


def test_kr_restart_persists_audit_but_invalidates_old_ticket_and_virtual_turn(tmp_path):
    path, clock = tmp_path / "kr5.sqlite3", Clock()
    first, ledger, _ = create(path, clock=clock)
    ticket = ledger.request("cliente")
    ledger.supervise(ADMIN)
    ledger.approve_virtual(ADMIN, ticket["request_id"], seconds=120)
    assert ledger.status(ticket["browser_secret"])["estado"] == "autorizado_virtual"
    first.close()
    with pytest.raises(FenceRejected):
        ledger.status(ticket["browser_secret"])
    second, restarted, _ = create(path, epoch=2, clock=clock)
    with pytest.raises(KRTicketDenied):
        restarted.status(ticket["browser_secret"])
    assert restarted.snapshot(ADMIN)["turno_virtual_activo"] is False
    with sqlite3.connect(path) as db:
        stale = db.execute("SELECT state, virtual_until FROM kr_ticket WHERE request_id=?",
                           (ticket["request_id"],)).fetchone()
        assert stale == ("revoked", None)
        assert db.execute("SELECT epoch FROM kr_meta").fetchone()[0] == 2
    assert restarted.request("cliente-nuevo")["estado"] == "esperando_autorizacion"
    second.close()


def test_kr_restart_does_not_reset_ip_request_budget(tmp_path):
    path, clock = tmp_path / "kr6.sqlite3", Clock()
    one, ledger, _ = create(path, clock=clock, max_per_client=1)
    ledger.request("client-real")
    one.close()
    two, restarted, _ = create(path, epoch=2, clock=clock, max_per_client=1)
    with pytest.raises(KRTicketDenied, match="Limite"):
        restarted.request("client-real")
    assert restarted.request("client-new")["canDrive"] is False
    two.close()


def test_kr_clock_rollback_poison_is_committed_and_blocks_future_start(tmp_path):
    path, clock = tmp_path / "kr7.sqlite3", Clock()
    fence, ledger, _ = create(path, clock=clock)
    ticket = ledger.request("A")
    clock.tick(-1)
    with pytest.raises(KRTicketDenied, match="selladas"):
        ledger.status(ticket["browser_secret"])
    with pytest.raises(KRTicketDenied):
        ledger.request("B")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT sealed FROM kr_meta").fetchone()[0] == 1
        assert db.execute("SELECT state FROM kr_ticket").fetchone()[0] == "revoked"
    fence.close()
    clock.tick(2)
    second = KQRestartFence(path)
    assert second.start() == 2
    restarted = KRTicketLedger(second, 2, ADMIN, clock=clock)
    with pytest.raises(KRTicketDenied):
        restarted.prepare()
    second.close()


def test_kr_bad_admin_and_bad_secret_cannot_mutate(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr8.sqlite3")
    ticket = ledger.request("A")
    for wrong in ("a", "", 12, None):
        with pytest.raises(KRTicketDenied):
            ledger.supervise(wrong)
        with pytest.raises(KRTicketDenied):
            ledger.approve_virtual(wrong, ticket["request_id"])
        with pytest.raises(KRTicketDenied):
            ledger.reject(wrong, ticket["request_id"])
    with pytest.raises(KRTicketDenied):
        ledger.status("á" * 43)
    with pytest.raises(KRTicketDenied):
        ledger.status("x" * 43)
    assert len(ledger.snapshot(ADMIN)["solicitudes"]) == 1
    fence.close()


def test_kr_single_owner_and_disk_loss_fail_closed(tmp_path):
    path = tmp_path / "kr9.sqlite3"
    fence, ledger, clock = create(path)
    with pytest.raises(Exception):
        KQRestartFence(path).start()
    path.unlink()
    with pytest.raises(StoreUnavailable):
        ledger.request("A")
    ledger.close()
    fence.close()


def test_kr_concurrent_virtual_approvals_never_create_two_active(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr10.sqlite3")
    a, b = ledger.request("A"), ledger.request("B")
    ledger.supervise(ADMIN)

    def attempt(ticket):
        try:
            ledger.approve_virtual(ADMIN, ticket["request_id"])
            return True
        except (KRTicketDenied, StoreUnavailable):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (a, b)))
    assert outcomes.count(True) == 1
    assert ledger.snapshot(ADMIN)["turno_virtual_activo"] is True
    fence.close()


def test_kr_sealed_on_invalidation_and_never_offers_physical_control(tmp_path):
    fence, ledger, clock = create(tmp_path / "kr11.sqlite3")
    a = ledger.request("A")
    epoch = fence.invalidate()
    assert epoch == 2
    with pytest.raises(FenceRejected):
        ledger.snapshot(ADMIN)
    for name in ("move", "dispatch", "stop", "claim_physical", "grant_drive"):
        assert not hasattr(ledger, name)
    with pytest.raises(FenceRejected):
        ledger.status(a["browser_secret"])
    fence.close()
