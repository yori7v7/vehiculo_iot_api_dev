"""Ejecutor exclusivo para la instancia de pruebas en loopback y build/mysql43."""
from pathlib import Path
import ssl

import pymysql
from pymysql.cursors import DictCursor

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.routers.health import get_database_health_service
from app.services.database_health import DatabaseHealthService

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "build" / "mysql43"


class IsolatedDatabase(MySQLDatabase):
    def __init__(self):
        pass

    def _connect(self):
        tls = ssl.create_default_context(cafile=str(DATA / "ca.pem"))
        # El certificado generado por mysqld no contiene 127.0.0.1;
        # esta excepción queda acotada al CA de esta instancia de pruebas.
        tls.check_hostname = False
        tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
        connection = pymysql.connect(
            host="127.0.0.1", port=33343, user="root", database="vehiculo_iot",
            ssl=tls, autocommit=False, cursorclass=DictCursor, charset="utf8mb4", binary_prefix=True,
            connect_timeout=3, read_timeout=5, write_timeout=5,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT @@datadir AS path")
                if Path(cursor.fetchone()["path"]).resolve() != DATA.resolve():
                    raise RuntimeError("Instancia aislada incorrecta.")
        except BaseException:
            connection.close()
            raise
        return connection


def isolated_app():
    from app.config.settings import get_settings
    from app.main import create_app

    settings = get_settings()
    if not settings.platform43_enabled or settings.app_env != "development" or settings.platform43_dispatch:
        raise RuntimeError("La instancia local requiere 4.3 en desarrollo con despacho inhibido.")
    app = create_app()
    factory = IsolatedDatabase
    app.dependency_overrides[get_database] = factory
    app.dependency_overrides[get_database_health_service] = lambda: DatabaseHealthService(factory())
    app.state.platform_database = factory()
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(isolated_app(), host="127.0.0.1", port=8043)
