"""Persistencia de comandos exclusivamente mediante los cuatro SP existentes."""

from app.database.procedures import StoredProcedureExecutor
from app.models.commands import CommandCreate, CommandResponse, CommandUpdate
from app.repositories.base import created_id, parse_model


class CommandRepository:
    """Usar el ejecutor y la conexión de la transacción que controla el servicio."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def create(self, vehicle_id: int, data: CommandCreate) -> int:
        result = self._executor.execute(
            "sp_crear_comando",
            (vehicle_id, data.nombre, data.codigo, data.descripcion),
        )
        return created_id(result, "id_comando")

    def list_for_vehicle(self, vehicle_id: int) -> list[CommandResponse]:
        result = self._executor.execute(
            "sp_obtener_comandos_vehiculo", (vehicle_id,)
        )
        return [parse_model(CommandResponse, row) for row in result.fetch_all()]

    def update(self, command_id: int, data: CommandUpdate) -> None:
        self._executor.execute(
            "sp_actualizar_comando",
            (command_id, data.nombre, data.codigo, data.descripcion, data.activo),
        )

    def delete(self, command_id: int) -> None:
        self._executor.execute("sp_eliminar_comando", (command_id,))
