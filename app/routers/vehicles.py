"""Endpoints síncronos del catálogo de vehículos."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.common import EntityId, ErrorResponse
from app.models.vehicles import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services.vehicles import VehicleService


router = APIRouter(prefix="/vehiculos", tags=["Vehículos"])

DATABASE_ERRORS = {
    500: {"model": ErrorResponse, "description": "Falló la operación o su resultado SQL no es válido."},
    503: {"model": ErrorResponse, "description": "La base de datos no está disponible o no está configurada."},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "El vehículo no existe."}}
DELETE_ERRORS = {
    **DATABASE_ERRORS,
    409: {"model": ErrorResponse, "description": "La base de datos rechazó la operación por un conflicto de integridad."},
}


def get_vehicle_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> VehicleService:
    return VehicleService(database)


VehicleServiceDependency = Annotated[VehicleService, Depends(get_vehicle_service)]


@router.get(
    "",
    response_model=list[VehicleResponse],
    summary="Listar vehículos",
    description=(
        "Ejecuta sp_obtener_vehiculos() en una transacción READ ONLY. "
        "Incluye vehículos activos e inactivos, ordenados por id_vehiculo; "
        "una colección vacía devuelve []."
    ),
    responses=DATABASE_ERRORS,
)
def list_vehicles(service: VehicleServiceDependency) -> list[VehicleResponse]:
    return service.list()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=VehicleResponse,
    summary="Crear vehículo",
    description=(
        "Ejecuta sp_crear_vehiculo(nombre, modelo, descripcion, microcontrolador) "
        "y sp_obtener_vehiculo(id_vehiculo) en una sola transacción. "
        "Nombre obligatorio, no vacío ni sólo espacios, máximo 80 caracteres. "
        "Modelo admite NULL y hasta 80 caracteres; descripción, 255; "
        "microcontrolador, 50. Los opcionales omitidos se envían como NULL. "
        "MySQL asigna la fecha, el ID y activo=true. No se aceptan campos adicionales. "
        "La respuesta se valida antes de confirmar la transacción."
    ),
    responses=DATABASE_ERRORS,
)
def create_vehicle(data: VehicleCreate, service: VehicleServiceDependency) -> VehicleResponse:
    return service.create(data)


@router.get(
    "/{id_vehiculo}",
    response_model=VehicleResponse,
    summary="Consultar vehículo",
    description=(
        "Ejecuta sp_obtener_vehiculo(id_vehiculo) en READ ONLY. "
        "El ID debe ser positivo y no superar 2147483647. "
        "También permite consultar vehículos inactivos. Devuelve 404 si no existe."
    ),
    responses={**DATABASE_ERRORS, **NOT_FOUND},
)
def get_vehicle(
    id_vehiculo: EntityId, service: VehicleServiceDependency
) -> VehicleResponse:
    return service.get(id_vehiculo)


@router.put(
    "/{id_vehiculo}",
    response_model=VehicleResponse,
    summary="Reemplazar datos de un vehículo",
    description=(
        "Comprueba existencia con sp_obtener_vehiculo(id_vehiculo), ejecuta "
        "sp_actualizar_vehiculo(id_vehiculo, nombre, modelo, descripcion, microcontrolador, activo) "
        "y relee con sp_obtener_vehiculo antes de confirmar una sola transacción. "
        "PUT exige nombre y activo booleano JSON; mantiene los límites del alta. "
        "Modelo, descripción y microcontrolador omitidos se reemplazan por NULL. "
        "ID positivo hasta 2147483647. No se aceptan campos adicionales. "
        "Permite actualizar y reactivar vehículos inactivos; 404 si no existen."
    ),
    responses={**DATABASE_ERRORS, **NOT_FOUND},
)
def update_vehicle(
    id_vehiculo: EntityId, data: VehicleUpdate, service: VehicleServiceDependency
) -> VehicleResponse:
    return service.update(id_vehiculo, data)


@router.delete(
    "/{id_vehiculo}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Eliminar vehículo",
    description=(
        "Comprueba existencia con sp_obtener_vehiculo(id_vehiculo) y ejecuta "
        "sp_eliminar_vehiculo(id_vehiculo) en una sola transacción. "
        "ID positivo hasta 2147483647. La eliminación es física y aplica "
        "las cascadas del esquema SQL; admite vehículos inactivos. "
        "Devuelve 404 si no existe o 204 sin cuerpo al eliminarlo."
    ),
    responses={**DELETE_ERRORS, **NOT_FOUND},
)
def delete_vehicle(id_vehiculo: EntityId, service: VehicleServiceDependency) -> Response:
    service.delete(id_vehiculo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
