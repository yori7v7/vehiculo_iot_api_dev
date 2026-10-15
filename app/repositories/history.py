"""Acceso al historial mediante los SP del script, sin filtrar ni limitar."""

from app.database.procedures import StoredProcedureExecutor
from app.models.history import HistoryResponse
from app.repositories.base import parse_model


class HistoryRepository:
    """El repositorio conserva todos los orígenes y el orden que entrega el SP."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def list_for_vehicle(self, vehicle_id: int) -> list[HistoryResponse]:
        """sp_obtener_historial(id_vehiculo), con todas sus filas y orígenes."""
        result = self._executor.execute("sp_obtener_historial", (vehicle_id,))
        return [parse_model(HistoryResponse, row) for row in result.fetch_all()]

    def register(self, vehicle_id: int, command_id: int | None, origin: str) -> None:
        """sp_registrar_historial(id_vehiculo, id_comando, origen)."""
        self._executor.execute(
            "sp_registrar_historial", (vehicle_id, command_id, origin)
        )
