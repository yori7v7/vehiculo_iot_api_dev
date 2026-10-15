"""Conexiones MySQL independientes y transacciones administradas por contexto."""

from collections.abc import Iterator
from contextlib import contextmanager
import ssl

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.config.settings import PROJECT_ROOT, Settings
from app.errors.database import (
    DatabaseConfigurationError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
)


class MySQLDatabase:
    """Fábrica de conexiones; nunca comparte una conexión entre solicitudes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _connect(self) -> Connection:
        """Validar la configuración y abrir una conexión sin autocommit."""

        settings = self._settings
        if not all(
            (
                settings.db_host.strip(),
                settings.db_name.strip(),
                settings.db_user.strip(),
                settings.db_password.get_secret_value(),
            )
        ):
            raise DatabaseConfigurationError()

        ca_path = settings.db_ssl_ca
        if not ca_path.is_absolute():
            ca_path = PROJECT_ROOT / ca_path
        try:
            tls_context = ssl.create_default_context(cafile=str(ca_path))
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            tls_context.verify_mode = ssl.CERT_REQUIRED
            tls_context.check_hostname = True
        except (OSError, ValueError):
            raise DatabaseConfigurationError() from None

        try:
            return pymysql.connect(
                host=settings.db_host,
                port=settings.db_port,
                database=settings.db_name,
                user=settings.db_user,
                password=settings.db_password.get_secret_value(),
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=False,
                connect_timeout=settings.db_connect_timeout,
                read_timeout=settings.db_read_timeout,
                write_timeout=settings.db_write_timeout,
                local_infile=False,
                # El contexto ya exige certificado e identidad. Mezclarlo con
                # ssl_verify_* hace que PyMySQL lo sustituya y pierda esta CA.
                ssl=tls_context,
            )
        except (pymysql.MySQLError, OSError, ValueError):
            raise DatabaseUnavailableError() from None

    @contextmanager
    def transaction(self, *, read_only: bool = False) -> Iterator[Connection]:
        """Compartir una conexión hasta confirmar o revertir la operación completa.

        Lectura: START TRANSACTION READ ONLY y rollback al terminar.
        Escritura: commit único al salir sin errores; rollback ante un fallo.
        El consumidor no debe confirmar, revertir ni cerrar esta conexión.
        """

        connection = self._connect()
        try:
            try:
                if read_only:
                    with connection.cursor() as cursor:
                        cursor.execute("START TRANSACTION READ ONLY")
                else:
                    connection.begin()

                yield connection

                if read_only:
                    connection.rollback()
                else:
                    connection.commit()
            except BaseException as error:
                # Un rollback fallido no debe ocultar el error original.
                self._rollback_safely(connection)
                if isinstance(error, (pymysql.MySQLError, OSError)):
                    raise DatabaseTransactionError() from None
                raise
        finally:
            self._close_safely(connection)

    @staticmethod
    def _rollback_safely(connection: Connection) -> None:
        try:
            connection.rollback()
        except (pymysql.MySQLError, OSError):
            pass

    @staticmethod
    def _close_safely(connection: Connection) -> None:
        try:
            connection.close()
        except (pymysql.MySQLError, OSError):
            # No convertir un commit confirmado en un falso fallo por el cierre.
            pass
