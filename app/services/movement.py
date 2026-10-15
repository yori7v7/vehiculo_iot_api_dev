"""Movimiento individual con actualización de estado e historial atómicos."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.models.movement import MovementRequest, MovementResponse
from app.repositories.commands import CommandRepository
from app.repositories.history import HistoryRepository
from app.repositories.state import StateRepository
from app.repositories.vehicles import VehicleRepository


class MovementService:
    """Validar y registrar una orden sin afirmar una conexión física del vehículo."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    def execute(self, vehicle_id: int, data: MovementRequest) -> MovementResponse:
        """Confirmar estado e historial juntos antes de devolver una respuesta exitosa."""

        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            vehicle = VehicleRepository(executor).get(vehicle_id)
            if vehicle is None:
                raise ResourceNotFoundError("El vehículo no existe.")
            if vehicle.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            if not vehicle.activo:
                raise ResourceConflictError("El vehículo está inactivo.")

            commands = CommandRepository(executor).list_for_vehicle(vehicle_id)
            command = next(
                (
                    value
                    for value in commands
                    if value.id_comando == data.id_comando
                    and value.id_vehiculo == vehicle_id
                ),
                None,
            )
            if command is None:
                raise ResourceNotFoundError("El comando no existe para este vehículo.")
            if not command.activo:
                raise ResourceConflictError("El comando está inactivo.")

            state_repository = StateRepository(executor)
            current_state = state_repository.get(vehicle_id)
            if current_state is not None and current_state.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            # Un POST recibido no demuestra conectividad del hardware. Mantener
            # el valor conocido; el primer estado usa el default conservador.
            connected = current_state.conectado if current_state is not None else False
            state_repository.update(vehicle_id, command.id_comando, connected)
            HistoryRepository(executor).register(vehicle_id, command.id_comando, "API")

            written_state = state_repository.get(vehicle_id)
            if (
                written_state is None
                or written_state.id_vehiculo != vehicle_id
                or written_state.id_comando != command.id_comando
                or written_state.comando != command.nombre
                or written_state.codigo != command.codigo
                or written_state.conectado != connected
            ):
                raise DatabaseResultError()

            response = MovementResponse(
                resultado="ok",
                id_vehiculo=vehicle_id,
                id_comando=command.id_comando,
                comando=written_state.comando,
                codigo=written_state.codigo,
                fecha_actualizacion=written_state.fecha_actualizacion,
                conectado=written_state.conectado,
                origen="API",
            )

        # El contexto ejecutó el commit y cerró la conexión; un fallo de commit
        # propaga su excepción sin devolver el objeto construido arriba.
        return response
