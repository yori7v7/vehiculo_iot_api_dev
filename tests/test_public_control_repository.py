"""Garantías del almacén y del propietario de despacho, con archivos temporales."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

from app.public_control import local_files, repository
from app.public_control.ownership import CoordinatorOwnership, CoordinatorUnavailable
from app.public_control.repository import PublicControlRepository, StoreUnavailable
from app.public_control.schema import APPLICATION_ID, SCHEMA_VERSION


def add_turn(connection, turn, digest, vehicle=1):
    connection.execute(
        """INSERT INTO control_turn
        (turn_id, vehicle_id, token_digest, generation, granted_at, absolute_expires, idle_expires)
        VALUES (?, ?, ?, 1, 100, 220, 120)""",
        (turn, vehicle, digest),
    )


def add_move(connection, operation, request, *, vehicle=1, sequence=1, code=1):
    connection.execute(
        """INSERT INTO control_operation
        (operation_id, vehicle_id, turn_id, generation, epoch, kind, request_id,
            sequence, code, duration_ms, created_at, deadline, status)
        VALUES (?, ?, 'turno-a', 1, 0, 'move', ?, ?, ?, 100, 100, 1.1, 'aceptada')""",
        (operation, vehicle, request, sequence, code),
    )


def test_initial_migration_is_idempotent_and_persists_commits(tmp_path):
    path = tmp_path / "control.sqlite3"
    repo = PublicControlRepository(path)
    with pytest.raises(StoreUnavailable):
        with repo.transaction():
            pytest.fail("No debe abrirse antes de migrar")
    repo.initialize()
    with repo.transaction() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        connection.execute("INSERT INTO control_vehicle (vehicle_id) VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")

    restarted = PublicControlRepository(path)
    restarted.initialize()
    with restarted.transaction() as connection:
        row = connection.execute("SELECT * FROM control_vehicle").fetchone()
        assert row["vehicle_id"] == 1
        assert row["revision"] == row["generation"] == row["epoch"] == 0


def test_transaction_rolls_back_business_error_and_bounds_writer_wait(tmp_path):
    path = tmp_path / "control.sqlite3"
    repo = PublicControlRepository(path, timeout=0.02)
    repo.initialize()
    with pytest.raises(ValueError, match="error de prueba"):
        with repo.transaction() as connection:
            connection.execute("INSERT INTO control_vehicle (vehicle_id) VALUES (1)")
            with pytest.raises(StoreUnavailable, match="no está disponible"):
                with repo.transaction():
                    pytest.fail("No puede haber dos escritores")
            raise ValueError("error de prueba")
    with repo.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM control_vehicle").fetchone()[0] == 0


def test_single_turn_is_enforced_between_connections(tmp_path):
    repo = PublicControlRepository(tmp_path / "control.sqlite3", timeout=2)
    repo.initialize()
    with repo.transaction() as connection:
        connection.execute("INSERT INTO control_vehicle (vehicle_id) VALUES (1)")
    start = Barrier(2, timeout=5)

    def compete(index):
        start.wait()
        try:
            with repo.transaction() as connection:
                add_turn(connection, f"turno-{index}", bytes([index]) * 32)
        except sqlite3.IntegrityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(compete, [1, 2])) == [False, True]
    with repo.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM control_turn WHERE active=1").fetchone()[0] == 1
        connection.execute("UPDATE control_turn SET active=0")
        add_turn(connection, "turno-a", b"\x03" * 32)


def test_schema_rejects_invalid_digest_code_scope_and_reused_sequence(tmp_path):
    repo = PublicControlRepository(tmp_path / "control.sqlite3")
    repo.initialize()
    with repo.transaction() as connection:
        connection.executemany("INSERT INTO control_vehicle (vehicle_id) VALUES (?)", [(1,), (2,)])
        with pytest.raises(sqlite3.IntegrityError):
            add_turn(connection, "digest-invalido", b"corto")
        add_turn(connection, "turno-a", b"\x01" * 32)
        add_move(connection, "movimiento-a", "solicitud-a")
        for kwargs in ({"vehicle": 2}, {"code": 16}, {"sequence": 0}, {}):
            with pytest.raises(sqlite3.IntegrityError):
                add_move(connection, "movimiento-b", "solicitud-b", **kwargs)
        with pytest.raises(sqlite3.IntegrityError):
            add_move(connection, "movimiento-b", "solicitud-a", sequence=2)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO control_stop_request VALUES (2, 'admin', 'paro', 'movimiento-a')",
            )


def test_missing_replaced_or_unknown_store_fails_closed(tmp_path):
    path = tmp_path / "control.sqlite3"
    repo = PublicControlRepository(path)
    repo.initialize()
    with repo.transaction() as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(StoreUnavailable, match="no es compatible"):
        repo.initialize()
    with pytest.raises(StoreUnavailable):
        with repo.transaction():
            pytest.fail("Una versión desconocida no habilita transacciones")

    restored = tmp_path / "restaurado.sqlite3"
    repo = PublicControlRepository(restored)
    repo.initialize()
    restored.unlink()
    with pytest.raises(StoreUnavailable):
        with repo.transaction():
            pytest.fail("La pérdida del archivo no debe crear una base vacía")
    assert not restored.exists()
    replacement = tmp_path / "reemplazo.sqlite3"
    PublicControlRepository(replacement).initialize()
    os.replace(replacement, restored)
    with pytest.raises(StoreUnavailable, match="cambió"):
        with repo.transaction():
            pytest.fail("Un archivo nuevo no puede sustituir al coordinador activo")


def test_initial_migration_rolls_back_ddl_and_preserves_foreign_database(tmp_path, monkeypatch):
    path = tmp_path / "control.sqlite3"
    repo = PublicControlRepository(path)
    with monkeypatch.context() as patch:
        patch.setattr(repository, "INITIAL_SCHEMA", (*repository.INITIAL_SCHEMA, "ERROR DE MIGRACIÓN"))
        with pytest.raises(StoreUnavailable):
            repo.initialize()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
        connection.execute("CREATE TABLE datos_ajenos (value TEXT)")
        connection.commit()
    with pytest.raises(StoreUnavailable, match="otro almacén"):
        repo.initialize()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == [("datos_ajenos",)]


def test_refuses_repository_paths_and_hardlinks_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(local_files, "PROJECT_ROOT", tmp_path)
    protected = tmp_path / "prohibido.sqlite3"
    with pytest.raises(StoreUnavailable):
        PublicControlRepository(protected).initialize()
    with pytest.raises(CoordinatorUnavailable):
        CoordinatorOwnership(protected).acquire()
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setattr(local_files, "PROJECT_ROOT", tmp_path / "otro-directorio")
    real = tmp_path / "original.sqlite3"
    real.touch(mode=0o600)
    linked = tmp_path / "alias.sqlite3"
    os.link(real, linked)
    with pytest.raises(StoreUnavailable):
        PublicControlRepository(linked).initialize()
    assert real.stat().st_size == 0


def test_process_lock_is_exclusive_and_released_after_process_exit(tmp_path):
    path = tmp_path / "control.sqlite3"
    code = """
import os
import sys
from app.public_control.ownership import CoordinatorOwnership, CoordinatorUnavailable

lock = CoordinatorOwnership(sys.argv[1])
try:
    lock.acquire()
except CoordinatorUnavailable:
    os._exit(12)
os._exit(0)
"""

    def launch():
        return subprocess.run(
            [sys.executable, "-c", code, str(path)],
            cwd=Path(__file__).resolve().parents[1],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, timeout=5, check=False,
        )

    with CoordinatorOwnership(path):
        assert launch().returncode == 12
    assert launch().returncode == 0
    with CoordinatorOwnership(path):
        assert path.with_name("control.sqlite3.lock").is_file()
