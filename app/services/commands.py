"""Operaciones de comandos y comprobación de su vehículo en una transacción."""

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.commands import CommandCreate, CommandResponse, CommandUpdate
from app.repositories.commands import CommandRepository
from app.repositories.vehicles import VehicleRepository


class CommandService:
    """Comprobar padre y pertenencia antes de escribir, sin filtrar inactivos."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    @staticmethod
    def _require_vehicle(repository: VehicleRepository, vehicle_id: int) -> None:
        vehicle = repository.get(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("El vehículo no existe.")
        if vehicle.id_vehiculo != vehicle_id:
            raise DatabaseResultError()

    @staticmethod
    def _find_command(
        commands: list[CommandResponse], vehicle_id: int, command_id: int
    ) -> CommandResponse | None:
        # No hay SP de consulta individual: se reutiliza el listado del padre.
        return next(
            (
                command
                for command in commands
                if command.id_comando == command_id
                and command.id_vehiculo == vehicle_id
            ),
            None,
        )

    @classmethod
    def _require_command(
        cls, repository: CommandRepository, vehicle_id: int, command_id: int
    ) -> CommandResponse:
        command = cls._find_command(
            repository.list_for_vehicle(vehicle_id), vehicle_id, command_id
        )
        if command is None:
            raise ResourceNotFoundError("El comando no existe para este vehículo.")
        return command

    @classmethod
    def _read_written_command(
        cls, repository: CommandRepository, vehicle_id: int, command_id: int
    ) -> CommandResponse:
        command = cls._find_command(
            repository.list_for_vehicle(vehicle_id), vehicle_id, command_id
        )
        if command is None:
            # Una escritura sin representación válida no se debe confirmar.
            raise DatabaseResultError()
        return command

    def create(self, vehicle_id: int, data: CommandCreate) -> CommandResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(VehicleRepository(executor), vehicle_id)
            repository = CommandRepository(executor)
            command_id = repository.create(vehicle_id, data)
            return self._read_written_command(repository, vehicle_id, command_id)

    def list_for_vehicle(self, vehicle_id: int) -> list[CommandResponse]:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(VehicleRepository(executor), vehicle_id)
            commands = CommandRepository(executor).list_for_vehicle(vehicle_id)
            if any(command.id_vehiculo != vehicle_id for command in commands):
                raise DatabaseResultError()
            return commands

    def update(
        self, vehicle_id: int, command_id: int, data: CommandUpdate
    ) -> CommandResponse:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(VehicleRepository(executor), vehicle_id)
            repository = CommandRepository(executor)
            self._require_command(repository, vehicle_id, command_id)
            repository.update(command_id, data)
            return self._read_written_command(repository, vehicle_id, command_id)

    def delete(self, vehicle_id: int, command_id: int) -> None:
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(VehicleRepository(executor), vehicle_id)
            repository = CommandRepository(executor)
            self._require_command(repository, vehicle_id, command_id)
            repository.delete(command_id)
