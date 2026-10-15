"""Historial reciente sin alterar ni clasificar los registros almacenados."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.history import HistoryResponse
from app.repositories.history import HistoryRepository
from app.repositories.vehicles import VehicleRepository


class HistoryService:
    """Devolver hasta diez registros en el orden recibido del SP."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    def list_for_vehicle(self, vehicle_id: int) -> list[HistoryResponse]:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            vehicle = VehicleRepository(executor).get(vehicle_id)
            if vehicle is None:
                raise ResourceNotFoundError("El vehículo no existe.")
            if vehicle.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            history = HistoryRepository(executor).list_for_vehicle(vehicle_id)
            if any(item.id_vehiculo != vehicle_id for item in history):
                raise DatabaseResultError()
            return history[:10]
