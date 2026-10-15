"""Lectura y actualización del estado mediante los dos SP existentes."""

from app.database.procedures import StoredProcedureExecutor
from app.models.state import StateResponse
from app.repositories.base import parse_model


class StateRepository:
    """Usar la conexión recibida; el servicio controla la transacción."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def get(self, vehicle_id: int) -> StateResponse | None:
        """sp_obtener_estado(id_vehiculo), sin inventar una fila inicial."""
        row = self._executor.execute("sp_obtener_estado", (vehicle_id,)).fetch_one()
        return parse_model(StateResponse, row) if row is not None else None

    def update(self, vehicle_id: int, command_id: int | None, connected: bool) -> None:
        """sp_actualizar_estado(id_vehiculo, id_comando, conectado)."""
        self._executor.execute(
            "sp_actualizar_estado", (vehicle_id, command_id, connected)
        )
