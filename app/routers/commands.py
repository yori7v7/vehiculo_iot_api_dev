"""Rutas HTTP de comandos; la persistencia pertenece al servicio y repositorio."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.commands import CommandCreate, CommandResponse, CommandUpdate
from app.models.common import ErrorResponse, INT_MAX
from app.services.commands import CommandService


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/comandos", tags=["Comandos"])

VehiclePath = Annotated[
    int,
    Path(gt=0, le=INT_MAX, description="Identificador positivo del vehículo padre."),
]
CommandPath = Annotated[
    int,
    Path(gt=0, le=INT_MAX, description="Identificador del comando de este vehículo."),
]

READ_ERRORS = {
    404: {"model": ErrorResponse, "description": "El vehículo no existe."},
    500: {"model": ErrorResponse, "description": "No fue posible procesar los datos."},
    503: {"model": ErrorResponse, "description": "La base de datos no está disponible."},
}
WRITE_ERRORS = {
    **READ_ERRORS,
    404: {
        "model": ErrorResponse,
        "description": "El vehículo o el comando de ese vehículo no existe.",
    },
    409: {
        "model": ErrorResponse,
        "description": "Conflicto con una restricción de unicidad o referencia.",
    },
}


def get_command_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> CommandService:
    """Crear el servicio por solicitud sin abrir conexiones aquí."""

    return CommandService(database)


CommandServiceDependency = Annotated[CommandService, Depends(get_command_service)]


@router.post(
    "",
    response_model=CommandResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un comando del vehículo",
    description=(
        "Comprueba el vehículo mediante sp_obtener_vehiculo(p_id_vehiculo), "
        "crea con sp_crear_comando(p_id_vehiculo, p_nombre, p_codigo, p_descripcion) "
        "y obtiene la respuesta mediante sp_obtener_comandos_vehiculo(p_id_vehiculo). "
        "Todo ocurre en una misma transacción. El cuerpo contiene nombre, código "
        "y descripción opcional. MySQL comprueba nombre y código únicos por vehículo."
    ),
    responses={
        **WRITE_ERRORS,
        201: {"description": "Comando creado con su representación completa."},
        404: {"model": ErrorResponse, "description": "El vehículo no existe."},
    },
)
def create_command(
    id_vehiculo: VehiclePath,
    data: CommandCreate,
    service: CommandServiceDependency,
) -> CommandResponse:
    return service.create(id_vehiculo, data)


@router.get(
    "",
    response_model=list[CommandResponse],
    summary="Listar los comandos de un vehículo",
    description=(
        "Comprueba el padre con sp_obtener_vehiculo(p_id_vehiculo) y consulta "
        "sp_obtener_comandos_vehiculo(p_id_vehiculo) en una transacción READ ONLY. "
        "Devuelve los comandos activos e inactivos, ordenados por código. "
        "Un vehículo existente sin comandos produce 200 con una lista vacía."
    ),
    responses={
        **READ_ERRORS,
        200: {"description": "Lista de comandos, posiblemente vacía."},
    },
)
def list_commands(
    id_vehiculo: VehiclePath, service: CommandServiceDependency
) -> list[CommandResponse]:
    return service.list_for_vehicle(id_vehiculo)


@router.put(
    "/{id_comando}",
    response_model=CommandResponse,
    summary="Actualizar un comando del vehículo",
    description=(
        "Comprueba el vehículo con sp_obtener_vehiculo(p_id_vehiculo) y la pertenencia "
        "del comando mediante sp_obtener_comandos_vehiculo(p_id_vehiculo). Ejecuta "
        "sp_actualizar_comando(p_id_comando, p_nombre, p_codigo, p_descripcion, p_activo) "
        "y relee el listado para responder, dentro de una transacción. PUT reemplaza "
        "los campos editables: nombre, código y activo son obligatorios; omitir "
        "descripción equivale a null. El vehículo propietario no cambia."
    ),
    responses={
        **WRITE_ERRORS,
        200: {"description": "Representación completa del comando actualizado."},
    },
)
def update_command(
    id_vehiculo: VehiclePath,
    id_comando: CommandPath,
    data: CommandUpdate,
    service: CommandServiceDependency,
) -> CommandResponse:
    return service.update(id_vehiculo, id_comando, data)


@router.delete(
    "/{id_comando}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Eliminar un comando del vehículo",
    description=(
        "Comprueba el padre con sp_obtener_vehiculo(p_id_vehiculo), verifica la "
        "pertenencia con sp_obtener_comandos_vehiculo(p_id_vehiculo) y ejecuta "
        "sp_eliminar_comando(p_id_comando) en una misma transacción. La eliminación "
        "es física. Una referencia que impide eliminarlo produce 409. "
        "No recibe cuerpo; una eliminación exitosa devuelve 204 sin contenido."
    ),
    responses={
        **WRITE_ERRORS,
        204: {"description": "Comando eliminado; respuesta sin contenido."},
    },
)
def delete_command(
    id_vehiculo: VehiclePath,
    id_comando: CommandPath,
    service: CommandServiceDependency,
) -> Response:
    service.delete(id_vehiculo, id_comando)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
