"""Consulta de estado sin escrituras ni suposiciones sobre hardware físico."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.state import StateResponse
from app.repositories.state import StateRepository
from app.repositories.vehicles import VehicleRepository


class StateService:
    """Comprobar el padre y leer su estado en una única transacción READ ONLY."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    def get(self, vehicle_id: int) -> StateResponse | None:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            vehicle = VehicleRepository(executor).get(vehicle_id)
            if vehicle is None:
                raise ResourceNotFoundError("El vehículo no existe.")
            if vehicle.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            state = StateRepository(executor).get(vehicle_id)
            if state is not None and state.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            return state
