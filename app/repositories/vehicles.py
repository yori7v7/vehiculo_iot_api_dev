"""Acceso a vehículos exclusivamente mediante los cinco SP del script SQL."""

from app.database.procedures import StoredProcedureExecutor
from app.models.vehicles import VehicleCreate, VehicleResponse, VehicleUpdate
from app.repositories.base import created_id, parse_model


class VehicleRepository:
    """Usar la conexión del servicio sin confirmar, revertir ni cerrarla."""

    def __init__(self, executor: StoredProcedureExecutor) -> None:
        self._executor = executor

    def create(self, data: VehicleCreate) -> int:
        """sp_crear_vehiculo(nombre, modelo, descripcion, microcontrolador)."""
        result = self._executor.execute(
            "sp_crear_vehiculo",
            (data.nombre, data.modelo, data.descripcion, data.microcontrolador),
        )
        return created_id(result, "id_vehiculo")

    def list(self) -> list[VehicleResponse]:
        """sp_obtener_vehiculos(), incluidos los inactivos, en orden de ID."""
        result = self._executor.execute("sp_obtener_vehiculos")
        return [parse_model(VehicleResponse, row) for row in result.fetch_all()]

    def get(self, vehicle_id: int) -> VehicleResponse | None:
        """sp_obtener_vehiculo(id_vehiculo); una ausencia no es error del driver."""
        row = self._executor.execute("sp_obtener_vehiculo", (vehicle_id,)).fetch_one()
        return parse_model(VehicleResponse, row) if row is not None else None

    def update(self, vehicle_id: int, data: VehicleUpdate) -> None:
        """sp_actualizar_vehiculo(id, nombre, modelo, descripción, MCU, activo)."""
        self._executor.execute(
            "sp_actualizar_vehiculo",
            (
                vehicle_id,
                data.nombre,
                data.modelo,
                data.descripcion,
                data.microcontrolador,
                data.activo,
            ),
        )

    def delete(self, vehicle_id: int) -> None:
        """sp_eliminar_vehiculo(id_vehiculo), con sus cascadas definidas en SQL."""
        self._executor.execute("sp_eliminar_vehiculo", (vehicle_id,))
