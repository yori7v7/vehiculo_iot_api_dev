"""Persistencia de DEMO exclusivamente mediante los ocho SP existentes."""

from app.database.procedures import StoredProcedureExecutor
from app.models.demos import (
    DemoCreate,
    DemoMovementCreate,
    DemoMovementResponse,
    DemoMovementUpdate,
    DemoResponse,
    DemoUpdate,
)
from app.repositories.base import created_id, parse_model


class DemoRepository:
    """La conexión y su transacción pertenecen al servicio llamante."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def create(self, vehicle_id: int, data: DemoCreate) -> int:
        result = self._executor.execute(
            "sp_crear_demo", (vehicle_id, data.nombre, data.descripcion)
        )
        return created_id(result, "id_demo")

    def list_for_vehicle(self, vehicle_id: int) -> list[DemoResponse]:
        result = self._executor.execute("sp_obtener_demos", (vehicle_id,))
        return [parse_model(DemoResponse, row) for row in result.fetch_all()]

    def update(self, demo_id: int, data: DemoUpdate) -> None:
        self._executor.execute(
            "sp_actualizar_demo", (demo_id, data.nombre, data.descripcion, data.activo)
        )

    def delete(self, demo_id: int) -> None:
        self._executor.execute("sp_eliminar_demo", (demo_id,))


class DemoMovementRepository:
    """No inventar un ID de alta: sp_agregar_movimiento_demo no hace SELECT."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def create(self, demo_id: int, data: DemoMovementCreate) -> None:
        self._executor.execute(
            "sp_agregar_movimiento_demo",
            (demo_id, data.id_comando, data.orden, data.duracion_ms, data.pausa_ms),
        )

    def list_for_demo(self, demo_id: int) -> list[DemoMovementResponse]:
        result = self._executor.execute("sp_obtener_movimientos_demo", (demo_id,))
        return [parse_model(DemoMovementResponse, row) for row in result.fetch_all()]

    def update(self, movement_id: int, data: DemoMovementUpdate) -> None:
        self._executor.execute(
            "sp_actualizar_movimiento_demo",
            (movement_id, data.id_comando, data.orden, data.duracion_ms, data.pausa_ms),
        )

    def delete(self, movement_id: int) -> None:
        self._executor.execute("sp_eliminar_movimiento_demo", (movement_id,))
