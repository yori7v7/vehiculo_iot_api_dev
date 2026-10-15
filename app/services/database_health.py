"""Comprobación de RDS mediante un procedimiento existente de sólo lectura."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor


class DatabaseHealthService:
    """Verificar conexión y ejecución de SP sin devolver registros de vehículos."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    def check(self) -> None:
        """Consumir la respuesta de sp_obtener_vehiculos sin modificar datos."""

        with self._database.transaction(read_only=True) as connection:
            StoredProcedureExecutor(connection).execute("sp_obtener_vehiculos")
