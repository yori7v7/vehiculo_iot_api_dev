"""CRUD de DEMO y movimientos con pertenencia y transacciones compartidas."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.models.commands import CommandResponse
from app.models.demos import (
    DemoCreate,
    DemoMovementCreate,
    DemoMovementResponse,
    DemoMovementUpdate,
    DemoResponse,
    DemoUpdate,
)
from app.repositories.commands import CommandRepository
from app.repositories.demos import DemoMovementRepository, DemoRepository
from app.repositories.vehicles import VehicleRepository


def _require_vehicle(executor: StoredProcedureExecutor, vehicle_id: int) -> None:
    vehicle = VehicleRepository(executor).get(vehicle_id)
    if vehicle is None:
        raise ResourceNotFoundError("El vehículo no existe.")
    if vehicle.id_vehiculo != vehicle_id:
        raise DatabaseResultError()


def _find_demo(
    values: list[DemoResponse], vehicle_id: int, demo_id: int
) -> DemoResponse | None:
    return next(
        (value for value in values if value.id_demo == demo_id and value.id_vehiculo == vehicle_id),
        None,
    )


def _require_demo(
    repository: DemoRepository, vehicle_id: int, demo_id: int
) -> DemoResponse:
    demo = _find_demo(repository.list_for_vehicle(vehicle_id), vehicle_id, demo_id)
    if demo is None:
        raise ResourceNotFoundError("La DEMO no existe para este vehículo.")
    return demo


def _require_command(
    executor: StoredProcedureExecutor, vehicle_id: int, command_id: int
) -> CommandResponse:
    command = next(
        (
            value for value in CommandRepository(executor).list_for_vehicle(vehicle_id)
            if value.id_comando == command_id and value.id_vehiculo == vehicle_id
        ),
        None,
    )
    if command is None:
        raise ResourceNotFoundError("El comando no existe para este vehículo.")
    if not command.activo:
        raise ResourceConflictError("El comando está inactivo.")
    return command


class DemoService:
    """Editar el catálogo incluso si el vehículo o la DEMO están inactivos."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    @staticmethod
    def _read_written_demo(
        repository: DemoRepository, vehicle_id: int, demo_id: int,
        data: DemoCreate | DemoUpdate,
    ) -> DemoResponse:
        demo = _find_demo(repository.list_for_vehicle(vehicle_id), vehicle_id, demo_id)
        if (
            demo is None or demo.nombre != data.nombre or demo.descripcion != data.descripcion
            or (isinstance(data, DemoUpdate) and demo.activo != data.activo)
        ):
            raise DatabaseResultError()
        return demo

    def create(self, vehicle_id: int, data: DemoCreate) -> DemoResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            repository = DemoRepository(executor)
            demo_id = repository.create(vehicle_id, data)
            response = self._read_written_demo(repository, vehicle_id, demo_id, data)
        return response

    def list_for_vehicle(self, vehicle_id: int) -> list[DemoResponse]:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            response = DemoRepository(executor).list_for_vehicle(vehicle_id)
            if any(demo.id_vehiculo != vehicle_id for demo in response):
                raise DatabaseResultError()
        return response

    def update(self, vehicle_id: int, demo_id: int, data: DemoUpdate) -> DemoResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            repository = DemoRepository(executor)
            _require_demo(repository, vehicle_id, demo_id)
            repository.update(demo_id, data)
            response = self._read_written_demo(repository, vehicle_id, demo_id, data)
        return response

    def delete(self, vehicle_id: int, demo_id: int) -> None:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            repository = DemoRepository(executor)
            _require_demo(repository, vehicle_id, demo_id)
            repository.delete(demo_id)
            if _find_demo(repository.list_for_vehicle(vehicle_id), vehicle_id, demo_id) is not None:
                raise DatabaseResultError()


class DemoMovementService:
    """Editar pasos sin ejecutar estado, historial ni comandos en hardware."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    @staticmethod
    def _require_movement(
        values: list[DemoMovementResponse], movement_id: int
    ) -> DemoMovementResponse:
        movement = next((value for value in values if value.id_demo_movimiento == movement_id), None)
        if movement is None:
            raise ResourceNotFoundError("El movimiento no existe para esta DEMO.")
        return movement

    @staticmethod
    def _validate_written_movement(
        movement: DemoMovementResponse, command: CommandResponse,
        data: DemoMovementCreate | DemoMovementUpdate,
    ) -> DemoMovementResponse:
        if (
            movement.id_comando != data.id_comando or movement.orden != data.orden
            or movement.duracion_ms != data.duracion_ms or movement.pausa_ms != data.pausa_ms
            or movement.comando != command.nombre or movement.codigo != command.codigo
        ):
            raise DatabaseResultError()
        return movement

    def create(
        self, vehicle_id: int, demo_id: int, data: DemoMovementCreate
    ) -> DemoMovementResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            _require_demo(DemoRepository(executor), vehicle_id, demo_id)
            command = _require_command(executor, vehicle_id, data.id_comando)
            repository = DemoMovementRepository(executor)
            previous_ids = {value.id_demo_movimiento for value in repository.list_for_demo(demo_id)}
            repository.create(demo_id, data)
            candidates = [
                value for value in repository.list_for_demo(demo_id)
                if value.id_demo_movimiento not in previous_ids and value.orden == data.orden
            ]
            # El SP no devuelve ID: usar el orden único y una fila nueva leída
            # en la misma transacción, nunca un supuesto LAST_INSERT_ID externo.
            if len(candidates) != 1:
                raise DatabaseResultError()
            response = self._validate_written_movement(candidates[0], command, data)
        return response

    def list_for_demo(self, vehicle_id: int, demo_id: int) -> list[DemoMovementResponse]:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            _require_demo(DemoRepository(executor), vehicle_id, demo_id)
            response = DemoMovementRepository(executor).list_for_demo(demo_id)
        return response

    def update(
        self, vehicle_id: int, demo_id: int, movement_id: int, data: DemoMovementUpdate
    ) -> DemoMovementResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            _require_demo(DemoRepository(executor), vehicle_id, demo_id)
            repository = DemoMovementRepository(executor)
            self._require_movement(repository.list_for_demo(demo_id), movement_id)
            command = _require_command(executor, vehicle_id, data.id_comando)
            repository.update(movement_id, data)
            movement = next(
                (value for value in repository.list_for_demo(demo_id) if value.id_demo_movimiento == movement_id),
                None,
            )
            if movement is None:
                raise DatabaseResultError()
            response = self._validate_written_movement(movement, command, data)
        return response

    def delete(self, vehicle_id: int, demo_id: int, movement_id: int) -> None:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            _require_vehicle(executor, vehicle_id)
            _require_demo(DemoRepository(executor), vehicle_id, demo_id)
            repository = DemoMovementRepository(executor)
            self._require_movement(repository.list_for_demo(demo_id), movement_id)
            repository.delete(movement_id)
            if any(value.id_demo_movimiento == movement_id for value in repository.list_for_demo(demo_id)):
                raise DatabaseResultError()
