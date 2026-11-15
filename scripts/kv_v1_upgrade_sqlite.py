"""Offline backup and read-only verification of the dedicated K-V V1 journal."""

from contextlib import closing, contextmanager
from hashlib import sha256
from math import isfinite
import os
from pathlib import Path
import sqlite3
import stat
import sys


APPLICATION_ID = 0x43504954
SCHEMA_VERSION = 1
BLOCKED = "kq_virtual_sin_traspaso_fisico"
MAX_COUNTER = 2**63 - 2
# Fingerprints of the schema in the approved original and its sole additive
# migration. Constraint declarations, partial indexes and unexpected objects
# are included. Whitespace from SQLite's DDL serialization is immaterial.
LEGACY = "541e9802c8c8056ce782159506c0c3dc147188bb2e941a5614ef5af93ae36a1f"
MIGRATED = "fc85088df7fe4ae5fc031228f37bc4e73badadc23706ee368aeb4b53693c2045"


class JournalRejected(RuntimeError):
    """The upgrade cannot proceed safely with this journal."""


def require(valid: bool, reason: str) -> None:
    if not valid:
        raise JournalRejected(reason)


def regular_info(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    linked = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    valid_type = (stat.S_ISDIR(info.st_mode) if directory
                  else stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    require(valid_type and not linked, "RUTA O ARCHIVO INSEGURO")
    return info


def local_path(value: str, *, existing: bool = True) -> Path:
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and path.name != "", "RUTA NO ABSOLUTA")
    if os.name == "nt":
        require(
            len(path.drive) == 2 and path.drive[0].isascii() and path.drive[0].isalpha()
            and path.drive[1] == ":" and all(":" not in part and not part.endswith((".", " "))
                                            for part in path.parts[1:]),
            "RUTA NO LOCAL O AMBIGUA",
        )
    for parent in reversed(path.parents):
        regular_info(parent, directory=True)
    if existing:
        regular_info(path)
    return path


def open_sqlite(path: Path, mode: str) -> sqlite3.Connection:
    db = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, isolation_level=None, timeout=2)
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        if mode == "ro":
            db.execute("PRAGMA query_only=ON")
        return db
    except BaseException:
        db.close()
        raise


@contextmanager
def offline_guard(path: Path):
    """Recheck the same coordinator byte lock used by K-Q, without creating it."""
    lock_path = path.with_name(path.name + ".lock")
    identity = regular_info(lock_path)
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags)
    try:
        require(os.path.samestat(identity, os.fstat(fd)), "BLOQUEO CAMBIO")
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(os.path.samestat(identity, regular_info(lock_path)), "BLOQUEO CAMBIO")
        for suffix in ("-journal", "-wal", "-shm"):
            require(not os.path.lexists(str(path) + suffix), "ARCHIVO AUXILIAR SQLITE PRESENTE")
        # EXCLUSIVE proves the database has no active reader/writer. A separate
        # reserved writer slot then prevents writes during the backup API's read.
        with closing(open_sqlite(path, "rw")) as guard:
            guard.execute("BEGIN EXCLUSIVE")
            guard.execute("ROLLBACK")
            guard.execute("BEGIN IMMEDIATE")
            yield
    finally:
        os.close(fd)


def fingerprint(db: sqlite3.Connection) -> str:
    rows = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY name").fetchall()
    ddl = "\n".join("|".join((*row[:3], " ".join((row[3] or "").split()))) for row in rows)
    return sha256(ddl.encode("utf-8")).hexdigest()


def inspect(
    db: sqlite3.Connection, allowed: set[str], *, allow_interrupted_start: bool = False,
) -> tuple[int, int, int, float, bytes]:
    require(db.execute("PRAGMA journal_mode").fetchone() == ("delete",), "JOURNAL SQLITE INCOMPATIBLE")
    require(db.execute("PRAGMA application_id").fetchone() == (APPLICATION_ID,)
            and db.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,),
            "IDENTIDAD SQLITE INCOMPATIBLE")
    require(fingerprint(db) in allowed, "ESQUEMA SQLITE INCOMPATIBLE")
    require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            and db.execute("PRAGMA foreign_key_check").fetchone() is None, "INTEGRIDAD SQLITE")

    vehicles = db.execute(
        "SELECT vehicle_id, epoch, generation, revision, blocked_reason,"
        " window_started, window_expires, window_request, stop_id FROM control_vehicle"
    ).fetchall()
    require(len(vehicles) == 1, "VEHICULO VIRTUAL INCOMPATIBLE")
    vehicle, epoch, generation, revision, blocked, *physical_fields = vehicles[0]
    require(vehicle == 1 and blocked == BLOCKED and physical_fields == [None] * 4
            and all(type(n) is int and 0 < n < MAX_COUNTER for n in (epoch, generation, revision))
            and db.execute("SELECT 1 FROM control_turn WHERE active=1 LIMIT 1").fetchone() is None,
            "BARRERA VIRTUAL NO VERIFICADA")

    ledger = db.execute(
        "SELECT version, epoch, last_wall, sealed, client_salt FROM kr_meta WHERE id=1",
    ).fetchone()
    require(ledger is not None, "JOURNAL DE TICKETS AUSENTE")
    version, ledger_epoch, last_wall, sealed, salt = ledger
    epoch_matches = ledger_epoch == epoch or (allow_interrupted_start and 0 < ledger_epoch < epoch)
    require(version == 1 and epoch_matches and sealed == 0 and isfinite(last_wall) and last_wall >= 0
            and isinstance(salt, bytes) and len(salt) == 32,
            "JOURNAL DE TICKETS NO VERIFICADO")
    require(db.execute(
        "SELECT 1 FROM kr_ticket WHERE epoch > ?"
        " OR (epoch <> ? AND state IN ('waiting','approved_virtual')) LIMIT 1", (ledger_epoch, ledger_epoch),
    ).fetchone() is None, "TICKETS DE OTRA EPOCA")
    return epoch, generation, revision, last_wall, salt


def backup_database(source: Path, destination: Path) -> None:
    def check_progress(status: int, _remaining: int, _total: int) -> None:
        require(status in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE), "RESPALDO SQLITE INTERRUMPIDO")

    with offline_guard(source), closing(open_sqlite(source, "ro")) as db:
        db.execute("BEGIN")
        expected = inspect(db, {LEGACY})
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            identity = os.fstat(fd)
        finally:
            os.close(fd)
        require(os.path.samestat(identity, regular_info(destination)), "DESTINO DE RESPALDO CAMBIO")
        with closing(open_sqlite(destination, "rw")) as copy:
            db.backup(copy, pages=128, progress=check_progress, sleep=0)
            require(inspect(copy, {LEGACY}) == expected, "RESPALDO SQLITE DISCREPANTE")
        with destination.open("r+b") as saved:
            require(os.path.samestat(identity, os.fstat(saved.fileno())), "RESPALDO SQLITE CAMBIO")
            os.fsync(saved.fileno())


def verify_migration(source: Path, backup: Path) -> None:
    with closing(open_sqlite(backup, "ro")) as saved, closing(open_sqlite(source, "ro")) as current:
        saved.execute("BEGIN")
        current.execute("BEGIN")
        old = inspect(saved, {LEGACY})
        after = inspect(current, {MIGRATED})
        require(after[:3] == tuple(n + 1 for n in old[:3]) and after[3] >= old[3] and after[4] == old[4],
                "EPOCA O LINAJE SQLITE NO VERIFICADOS")


def verify_rollback(source: Path) -> None:
    # The old INSERTs name all columns. The additive column's checked default
    # makes both known schemas compatible, so no snapshot restore is required.
    with offline_guard(source), closing(open_sqlite(source, "ro")) as current:
        current.execute("BEGIN")
        # A crash between K-Q rotation and K-R preparation can leave K-R one
        # or more epochs behind. Old startup revokes those tickets before it
        # can serve a request. A sealed ledger still requires manual recovery.
        inspect(current, {LEGACY, MIGRATED}, allow_interrupted_start=True)


def main(argv: list[str]) -> int:
    try:
        require(bool(argv) and argv[0] in {"backup", "verify-migrated", "verify-rollback"},
                "OPERACION SQLITE NO SOPORTADA")
        op = argv[0]
        require(len(argv) == (2 if op == "verify-rollback" else 3), "ARGUMENTOS SQLITE INVALIDOS")
        source = local_path(argv[1])
        if op == "verify-rollback":
            verify_rollback(source)
        else:
            other = local_path(argv[2], existing=op == "verify-migrated")
            if op == "backup":
                backup_database(source, other)
            else:
                verify_migration(source, other)
    except JournalRejected as error:
        print("NO-GO: " + str(error))
        return 2
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        # Exceptions from the OS and sqlite can contain private paths or data.
        print("NO-GO: SQLITE NO ACCESIBLE DE FORMA VERIFICABLE")
        return 2
    print("OK: SQLITE " + op.upper())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
