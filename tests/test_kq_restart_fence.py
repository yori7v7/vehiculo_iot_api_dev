"""K-Q: journal durable de epocas SIN rutas HTTP ni motor."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.public_control.kq_restart_fence import (
    BLOCKED, VEHICLE_ID, FenceRejected, KQRestartFence,
)
from app.public_control.ownership import CoordinatorUnavailable
from app.public_control.repository import PublicControlRepository, StoreUnavailable


def test_kq_new_start_creates_blocked_epoch_and_never_opens_window(tmp_path):
    path = tmp_path / "kq-test.sqlite3"
    with KQRestartFence(path) as fence:
        fence.assert_current(1)
        for invalid in (0, 2, True, 1.0, None, "1"):
            with pytest.raises(FenceRejected):
                fence.assert_current(invalid)
        repo = PublicControlRepository(path)
        repo.initialize()
        with repo.transaction() as db:
            row = db.execute(
                "SELECT * FROM control_vehicle WHERE vehicle_id=?", (VEHICLE_ID,)
            ).fetchone()
            assert row["epoch"] == 1
            assert row["generation"] == 1
            assert row["blocked_reason"] == BLOCKED
            assert row["window_expires"] is None
            assert row["stop_id"] is None
    with pytest.raises(FenceRejected):
        fence.assert_current(1)


def test_kq_restart_revokes_epoch_and_will_not_reauthorize_old_generation(tmp_path):
    path = tmp_path / "kq-restart.sqlite3"
    first = KQRestartFence(path)
    assert first.start() == 1
    first.assert_current(1)
    first.close()

    second = KQRestartFence(path)
    assert second.start() == 2
    with pytest.raises(FenceRejected):
        second.assert_current(1)
    second.assert_current(2)
    second.close()

    third = KQRestartFence(path)
    assert third.start() == 3
    with pytest.raises(FenceRejected):
        third.assert_current(2)
    third.close()


def test_kq_two_owners_same_file_denied_no_counter_increment(tmp_path):
    path = tmp_path / "kq-exclusive.sqlite3"
    owner = KQRestartFence(path)
    assert owner.start() == 1
    with pytest.raises(CoordinatorUnavailable):
        KQRestartFence(path).start()
    owner.assert_current(1)
    owner.close()
    with KQRestartFence(path) as second:
        second.assert_current(2)


def test_kq_invalidate_is_irreversible_in_same_process(tmp_path):
    path = tmp_path / "kq-invalidate.sqlite3"
    owner = KQRestartFence(path)
    assert owner.start() == 1
    assert owner.invalidate() == 2
    for epoch in (1, 2):
        with pytest.raises(FenceRejected):
            owner.assert_current(epoch)
    with pytest.raises(FenceRejected):
        owner.invalidate()
    with pytest.raises(FenceRejected):
        owner.start()
    owner.close()
    with KQRestartFence(path) as restarted:
        restarted.assert_current(3)


def test_kq_atomic_recovery_produces_stale_operations_but_never_verified_stop(tmp_path):
    path = tmp_path / "kq-recover.sqlite3"
    with KQRestartFence(path):
        repo = PublicControlRepository(path)
        repo.initialize()
        with repo.transaction() as db:
            db.execute(
                "UPDATE control_vehicle SET window_started=100, window_expires=130, "
                "window_request='antigua', blocked_reason=NULL WHERE vehicle_id=1"
            )
            db.execute(
                "INSERT INTO control_turn(turn_id,vehicle_id,token_digest,generation,"
                "absolute_expires,idle_expires,granted_at) "
                "VALUES('sesion-antigua',1,?,1,130,120,100)", (b"a" * 32,)
            )
            db.execute(
                "INSERT INTO control_operation(operation_id,vehicle_id,turn_id,"
                "generation,epoch,kind,request_id,sequence,code,duration_ms,created_at,"
                "deadline,status) VALUES('movimiento-antiguo',1,'sesion-antigua',"
                "1,1,'move','id-antiguo',1,1,300,100,100.3,'despachada')"
            )
            db.execute(
                "INSERT INTO control_operation(operation_id,vehicle_id,"
                "generation,epoch,kind,code,duration_ms,created_at,status) "
                "VALUES('stop-antiguo',1,1,1,'stop',0,0,100,'pendiente')"
            )
    with KQRestartFence(path) as owner:
        owner.assert_current(2)
        repo = PublicControlRepository(path)
        repo.initialize()
        with repo.transaction() as db:
            row = db.execute("SELECT * FROM control_vehicle WHERE vehicle_id=1").fetchone()
            assert row["window_started"] is None
            assert row["window_expires"] is None
            assert row["blocked_reason"] == BLOCKED
            assert row["epoch"] == row["generation"] == 2
            assert db.execute(
                "SELECT active FROM control_turn WHERE turn_id='sesion-antigua'"
            ).fetchone()["active"] == 0
            for name in ("movimiento-antiguo", "stop-antiguo"):
                assert db.execute(
                    "SELECT status FROM control_operation WHERE operation_id=?", (name,)
                ).fetchone()["status"] == "incierta"


def test_kq_disk_replacement_fails_closed_without_fallback(tmp_path):
    path = tmp_path / "kq-removed.sqlite3"
    fence = KQRestartFence(path)
    assert fence.start() == 1
    # No recrear otro archivo con la misma ruta en caliente.
    path.unlink()
    with pytest.raises(StoreUnavailable):
        fence.assert_current(1)
    with pytest.raises(StoreUnavailable):
        fence.invalidate()
    with pytest.raises(FenceRejected):
        fence.assert_current(1)
    fence.close()


def test_kq_parallel_invalidates_only_one_epoch_and_both_close(tmp_path):
    path = tmp_path / "kq-race.sqlite3"
    fence = KQRestartFence(path)
    assert fence.start() == 1
    def race(_):
        try:
            return fence.invalidate()
        except FenceRejected:
            return "denegado"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(race, [0, 1]))
    assert result.count(2) == 1
    assert result.count("denegado") == 1
    with pytest.raises(FenceRejected):
        fence.assert_current(2)
    fence.close()
