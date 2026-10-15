"""Preparar una DEMO y aplicar cada paso en una transacción independiente."""

from collections.abc import Callable

from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.models.commands import CommandResponse
from app.models.demo_execution import DemoExecutionPlan
from app.models.demos import DemoMovementResponse, DemoResponse
from app.models.state import StateResponse
from app.repositories.commands import CommandRepository
from app.repositories.demos import DemoMovementRepository, DemoRepository
from app.repositories.state import StateRepository
from app.repositories.vehicles import VehicleRepository


class DemoExecutionCancelled(Exception):
    """Señal interna de cancelación cooperativa: salir del contexto con rollback."""


class DemoExecutionService:
    """No registra historial; sus resultados sólo se entregan tras el commit."""

    def __init__(self, database: MySQLDatabase) -> None:
        self._database = database

    @staticmethod
    def _require_vehicle(executor: StoredProcedureExecutor, vehicle_id: int) -> None:
        vehicle = VehicleRepository(executor).get(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("El vehículo no existe.")
        if vehicle.id_vehiculo != vehicle_id:
            raise DatabaseResultError()
        if not vehicle.activo:
            raise ResourceConflictError("El vehículo está inactivo.")

    @staticmethod
    def _require_demo(
        executor: StoredProcedureExecutor, vehicle_id: int, demo_id: int
    ) -> DemoResponse:
        demo = next(
            (
                value for value in DemoRepository(executor).list_for_vehicle(vehicle_id)
                if value.id_demo == demo_id and value.id_vehiculo == vehicle_id
            ),
            None,
        )
        if demo is None:
            raise ResourceNotFoundError("La demo no existe para este vehículo.")
        if not demo.activo:
            raise ResourceConflictError("La demo está inactiva.")
        return demo

    @staticmethod
    def _require_command(
        commands: list[CommandResponse], vehicle_id: int, movement: DemoMovementResponse
    ) -> None:
        command = next(
            (
                value for value in commands
                if value.id_comando == movement.id_comando and value.id_vehiculo == vehicle_id
            ),
            None,
        )
        if command is None or not command.activo:
            raise ResourceConflictError("Un comando de la demo no está disponible para este vehículo.")
        if command.nombre != movement.comando or command.codigo != movement.codigo:
            raise ResourceConflictError("Los datos de un comando de la demo cambiaron.")

    @staticmethod
    def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel is not None and should_cancel():
            raise DemoExecutionCancelled()

    def prepare(self, vehicle_id: int, demo_id: int) -> DemoExecutionPlan:
        with self._database.transaction(read_only=True) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(executor, vehicle_id)
            demo = self._require_demo(executor, vehicle_id, demo_id)
            movements = DemoMovementRepository(executor).list_for_demo(demo_id)
            if not movements:
                raise ResourceConflictError("La demo no tiene movimientos.")
            previous_order = 0
            movement_ids: set[int] = set()
            for movement in movements:
                if movement.orden <= previous_order or movement.id_demo_movimiento in movement_ids:
                    raise ResourceConflictError("La secuencia de movimientos de la demo no es válida.")
                previous_order = movement.orden
                movement_ids.add(movement.id_demo_movimiento)
            commands = CommandRepository(executor).list_for_vehicle(vehicle_id)
            for movement in movements:
                self._require_command(commands, vehicle_id, movement)
            return DemoExecutionPlan(demo=demo, movimientos=tuple(movements))

    def apply_step(
        self,
        plan: DemoExecutionPlan,
        movement: DemoMovementResponse,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> StateResponse:
        if movement not in plan.movimientos:
            raise ResourceConflictError("El movimiento no pertenece al plan preparado.")
        vehicle_id = plan.demo.id_vehiculo
        with self._database.transaction(read_only=False) as connection:
            executor = StoredProcedureExecutor(connection)
            self._require_vehicle(executor, vehicle_id)
            self._require_demo(executor, vehicle_id, plan.demo.id_demo)
            commands = CommandRepository(executor).list_for_vehicle(vehicle_id)
            self._require_command(commands, vehicle_id, movement)
            repository = StateRepository(executor)
            current_state = repository.get(vehicle_id)
            if current_state is not None and current_state.id_vehiculo != vehicle_id:
                raise DatabaseResultError()
            connected = current_state.conectado if current_state is not None else False
            self._check_cancelled(should_cancel)
            repository.update(vehicle_id, movement.id_comando, connected)
            state = repository.get(vehicle_id)
            if (
                state is None
                or state.id_vehiculo != vehicle_id
                or state.id_comando != movement.id_comando
                or state.comando != movement.comando
                or state.codigo != movement.codigo
                or state.conectado != connected
            ):
                raise DatabaseResultError()
            self._check_cancelled(should_cancel)
        return state
