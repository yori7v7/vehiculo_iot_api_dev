from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.public_control.kq_restart_fence import KQRestartFence
from app.public_control.kr_ticket_ledger import KRTicketLedger
from scripts import kv_v1_upgrade_sqlite as upgrade


SCRIPT = Path(upgrade.__file__)
ADMIN = "fixture-key-" + "A" * 40
SAMPLE = "opaque-fixture-not-for-output"


def runtime(path: Path):
    fence = KQRestartFence(path)
    epoch = fence.start()
    ledger = KRTicketLedger(fence, epoch, ADMIN, clock=lambda: 1000.0)
    ledger.prepare()
    return fence, ledger


def legacy_database(path: Path):
    fence, ledger = runtime(path)
    ticket = ledger.request(SAMPLE)
    ledger.supervise(ADMIN)
    ledger.approve_virtual(ADMIN, ticket["request_id"])
    ledger.close()
    fence.close()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE kr_ticket DROP COLUMN approval_mode")
    return ticket


def cli(action: str, *paths: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", "-I", "-S", str(SCRIPT), action, *(str(path) for path in paths)],
        capture_output=True, text=True, timeout=10, check=False,
    )


def assert_safe_output(result: subprocess.CompletedProcess, path: Path) -> None:
    assert result.stderr == ""
    assert str(path) not in result.stdout
    assert ADMIN not in result.stdout
    assert SAMPLE not in result.stdout


def test_upgrade_uses_real_snapshot_migration_and_code_only_rollback(tmp_path):
    source = tmp_path / "live.sqlite"
    backup = tmp_path / "snapshot.sqlite"
    ticket = legacy_database(source)

    result = cli("backup", source, backup)
    assert result.returncode == 0, result.stdout
    assert_safe_output(result, tmp_path)
    with closing(sqlite3.connect(backup)) as saved:
        assert saved.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert saved.execute("SELECT state FROM kr_ticket WHERE request_id=?",
                             (ticket["request_id"],)).fetchone() == ("approved_virtual",)
    old_bytes = backup.read_bytes()
    # A previously reserved backup path is never overwritten.
    assert cli("backup", source, backup).returncode == 2
    assert backup.read_bytes() == old_bytes
    assert cli("verify-migrated", source, backup).returncode == 2

    fence, ledger = runtime(source)
    try:
        result = cli("verify-migrated", source, backup)
        assert result.returncode == 0, result.stdout
        assert_safe_output(result, tmp_path)
        fresh = ledger.request("fresh-demo")
        ledger.supervise(ADMIN)
        ledger.approve_virtual(ADMIN, fresh["request_id"], mode="supervised", seconds=None)
        assert cli("verify-rollback", source).returncode == 2  # K-Q still owns the journal.
    finally:
        ledger.close()
        fence.close()

    migrated_bytes = source.read_bytes()
    result = cli("verify-rollback", source)
    assert result.returncode == 0, result.stdout
    assert source.read_bytes() == migrated_bytes
    assert backup.read_bytes() == old_bytes
    with closing(sqlite3.connect(source)) as db, db:
        after, new_turn = db.execute(
            "SELECT state, virtual_until, approval_mode FROM kr_ticket ORDER BY epoch",
        ).fetchall()
        assert after == ("revoked", None, "timed")
        assert new_turn == ("approved_virtual", 1015.0, "supervised")
        # Legacy INSERT names every old column and the migrated default covers
        # approval_mode without removing or changing newer history.
        db.execute(
            "INSERT INTO kr_ticket(request_id, epoch, browser_hash, client_digest, display_code,"
            " created_at, expires_at, state) VALUES ('legacy-fresh', 2, ?, ?, 'A', 1000, 1001, 'waiting')",
            (bytes(32), bytes(32)),
        )
        assert db.execute("SELECT approval_mode FROM kr_ticket WHERE request_id='legacy-fresh'").fetchone() == ("timed",)


def test_rollback_accepts_interrupted_restart_but_leaves_db_untouched(tmp_path):
    path = tmp_path / "interrupted.sqlite"
    legacy_database(path)
    fence = KQRestartFence(path)
    assert fence.start() == 2
    fence.close()  # Process went away after K-Q had committed, before K-R prepare.
    before = path.read_bytes()
    result = cli("verify-rollback", path)
    assert result.returncode == 0, result.stdout
    assert path.read_bytes() == before
    fence, ledger = runtime(path)
    try:
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT epoch FROM kr_meta").fetchone() == (3,)
            assert db.execute("SELECT state FROM kr_ticket").fetchone() == ("revoked",)
    finally:
        ledger.close()
        fence.close()


@pytest.mark.parametrize("anomaly", ["missing-lock", "sidecar", "third-party-schema", "sealed", "corrupt"])
def test_offline_backup_refuses_uncertainty_without_leaving_destination(tmp_path, anomaly):
    source = tmp_path / "private database.sqlite"
    backup = tmp_path / "snapshot.sqlite"
    legacy_database(source)
    if anomaly == "missing-lock":
        Path(str(source) + ".lock").unlink()
    elif anomaly == "sidecar":
        Path(str(source) + "-journal").write_bytes(b"incomplete")
    elif anomaly == "corrupt":
        source.write_bytes(b"not a SQLite database")
    else:
        with closing(sqlite3.connect(source)) as db, db:
            if anomaly == "third-party-schema":
                db.execute("CREATE TABLE not_kv(key TEXT)")
            else:
                db.execute("UPDATE kr_meta SET sealed=1")

    result = cli("backup", source, backup)
    assert result.returncode == 2
    assert result.stdout.startswith("NO-GO: ")
    assert not backup.exists()
    assert_safe_output(result, source)


def test_migrated_verifier_rejects_unrelated_sqlite_lineage(tmp_path):
    source = tmp_path / "unrelated.sqlite"
    other = tmp_path / "old.sqlite"
    backup = tmp_path / "before.sqlite"
    legacy_database(other)
    result = cli("backup", other, backup)
    assert result.returncode == 0, result.stdout
    # Give the unrelated database the correct expected epoch and full schema.
    for _ in range(2):
        fence, ledger = runtime(source)
        ledger.close()
        fence.close()
    assert cli("verify-migrated", source, backup).returncode == 2


def test_rollback_refuses_approval_mode_without_constrained_default(tmp_path):
    source = tmp_path / "weak-schema.sqlite"
    legacy_database(source)
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("ALTER TABLE kr_ticket ADD COLUMN approval_mode TEXT")
    before = source.read_bytes()
    result = cli("verify-rollback", source)
    assert result.returncode == 2
    assert "ESQUEMA SQLITE INCOMPATIBLE" in result.stdout
    assert source.read_bytes() == before
