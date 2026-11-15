"""Transacciones SQLite separadas de las tablas académicas de MySQL."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3

from app.public_control.local_files import check_private, open_private, private_parent
from app.public_control.schema import APPLICATION_ID, INITIAL_SCHEMA, SCHEMA_VERSION


class StoreUnavailable(RuntimeError):
    """El almacén local no puede garantizar una operación."""


class PublicControlRepository:
    def __init__(self, path: Path | str, *, timeout: float = 0.25):
        self._path = Path(path)
        self._timeout = timeout
        self._identity: os.stat_result | None = None
        self._identity_ctime_ns: int | None = None

    def initialize(self) -> None:
        """Crear o migrar el esquema en una sola transacción exclusiva."""
        self._identity = None
        self._identity_ctime_ns = None
        try:
            path = private_parent(self._path)
            self._check_sidecars(path)
            fd = open_private(path)
            try:
                identity = os.fstat(fd)
            finally:
                os.close(fd)
            with closing(self._connect(path)) as connection:
                if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise StoreUnavailable("No se pudo configurar el almacén local.")
                connection.execute("BEGIN EXCLUSIVE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                application_id = connection.execute("PRAGMA application_id").fetchone()[0]
                if version == 0 and application_id == 0:
                    if connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
                        raise StoreUnavailable("El archivo ya pertenece a otro almacén.")
                    for statement in INITIAL_SCHEMA:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version != SCHEMA_VERSION or application_id != APPLICATION_ID:
                    raise StoreUnavailable("La versión del almacén local no es compatible.")
                connection.execute("COMMIT")
            current = check_private(path)
            if not os.path.samestat(identity, current):
                raise StoreUnavailable("El archivo de coordinación cambió.")
        except (OSError, sqlite3.Error):
            raise StoreUnavailable("No se pudo preparar el almacén local.") from None
        self._path = path
        self._identity = current
        # st_ino/st_dev no bastan: tras unlink+replace Linux puede reciclar
        # inmediatamente el mismo inode. ctime_ns es la marca de identidad.
        self._identity_ctime_ns = current.st_ctime_ns

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Reservar el escritor al principio y confirmar solo al completar la unidad."""
        if self._identity is None:
            raise StoreUnavailable("El almacén local no está inicializado.")
        try:
            path = private_parent(self._path)
            current = check_private(path)
            if (not os.path.samestat(self._identity, current)
                    or current.st_ctime_ns != self._identity_ctime_ns):
                raise StoreUnavailable("El archivo de coordinación cambió.")
            self._check_sidecars(path)
            with closing(self._connect(path)) as connection:
                if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise StoreUnavailable("El almacén local no está en el modo esperado.")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if (
                        connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
                        or connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                    ):
                        raise StoreUnavailable("La versión del almacén local no es compatible.")
                    yield connection
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
                    # Una escritura SQLite legítima cambia ctime_ns en POSIX.
                    # Actualizarla solo después del commit y verificar la
                    # identidad anterior para no aceptar un reemplazo externo.
                    fresh = check_private(path)
                    if not os.path.samestat(self._identity, fresh):
                        raise StoreUnavailable("El archivo de coordinación cambió.")
                    self._identity = fresh
                    self._identity_ctime_ns = fresh.st_ctime_ns
        except sqlite3.IntegrityError:
            # El coordinador puede distinguir una colisión prevista del almacén caído.
            raise
        except (OSError, sqlite3.Error):
            raise StoreUnavailable("El almacén local no está disponible.") from None

    def _connect(self, path: Path) -> sqlite3.Connection:
        # mode=rw impide recrear silenciosamente el archivo si desaparece.
        connection = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, timeout=self._timeout, isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    @staticmethod
    def _check_sidecars(path: Path) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                check_private(path.with_name(path.name + suffix))
            except FileNotFoundError:
                continue
