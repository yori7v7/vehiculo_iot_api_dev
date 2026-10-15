"""Casos de uso de vehículos y límites de sus transacciones."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.vehicles import VehicleCreate, VehicleResponse, VehicleUpdate
from app.repositories.vehicles import VehicleRepository


class VehicleService:
    """Compartir una conexión por operación y validar antes del commit."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    def create(self, data: VehicleCreate) -> VehicleResponse:
        with self._database.transaction(read_only=False) as connection:
            repository = VehicleRepository(StoredProcedureExecutor(connection))
            vehicle_id = repository.create(data)
            vehicle = repository.get(vehicle_id)
            if vehicle is None or vehicle.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            return vehicle

    def list(self) -> list[VehicleResponse]:
        with self._database.transaction(read_only=True) as connection:
            return VehicleRepository(StoredProcedureExecutor(connection)).list()

    def get(self, vehicle_id: int) -> VehicleResponse:
        with self._database.transaction(read_only=True) as connection:
            repository = VehicleRepository(StoredProcedureExecutor(connection))
            return self._require_vehicle(repository, vehicle_id)

    def update(self, vehicle_id: int, data: VehicleUpdate) -> VehicleResponse:
        with self._database.transaction(read_only=False) as connection:
            repository = VehicleRepository(StoredProcedureExecutor(connection))
            self._require_vehicle(repository, vehicle_id)
            repository.update(vehicle_id, data)
            vehicle = repository.get(vehicle_id)
            if vehicle is None or vehicle.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            return vehicle

    def delete(self, vehicle_id: int) -> None:
        with self._database.transaction(read_only=False) as connection:
            repository = VehicleRepository(StoredProcedureExecutor(connection))
            self._require_vehicle(repository, vehicle_id)
            repository.delete(vehicle_id)

    @staticmethod
    def _require_vehicle(
        repository: VehicleRepository, vehicle_id: int
    ) -> VehicleResponse:
        vehicle = repository.get(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("El vehículo no existe.")
        if vehicle.id_vehiculo != vehicle_id:
            raise DatabaseResultError()
        return vehicle
