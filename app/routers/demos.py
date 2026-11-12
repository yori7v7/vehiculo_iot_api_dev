"""Catálogo HTTP de DEMO y movimientos; no inicia ejecuciones."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.common import ErrorResponse, INT_MAX
from app.models.demos import (
    DemoCreate,
    DemoMovementCreate,
    DemoMovementResponse,
    DemoMovementUpdate,
    DemoResponse,
    DemoUpdate,
)
from app.services.demos import DemoMovementService, DemoService
from app.security.api_key import SECURITY_RESPONSES, require_api_key


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/demos", tags=["DEMO"])
VehiclePath = Annotated[int, Path(gt=0, le=INT_MAX, description="ID positivo del vehículo padre.")]
DemoPath = Annotated[int, Path(gt=0, le=INT_MAX, description="ID de la DEMO del vehículo.")]
MovementPath = Annotated[int, Path(gt=0, le=INT_MAX, description="ID del movimiento de esta DEMO.")]

READ_ERRORS = {
    404: {"model": ErrorResponse, "description": "El vehículo o la DEMO de ese vehículo no existe."},
    500: {"model": ErrorResponse, "description": "Falló el SP o devolvió datos inesperados."},
    503: {"model": ErrorResponse, "description": "La base de datos no está disponible."},
}
WRITE_ERRORS = {
    **READ_ERRORS,
    409: {"model": ErrorResponse, "description": "Conflicto de integridad al escribir."},
}
MOVEMENT_ERRORS = {
    **WRITE_ERRORS,
    409: {"model": ErrorResponse, "description": "Orden duplicado, conflicto de referencia o comando inactivo."},
    404: {
        "model": ErrorResponse,
        "description": "No existe el vehículo, la DEMO, su movimiento o el comando del vehículo.",
    },
}


def get_demo_service(database: Annotated[MySQLDatabase, Depends(get_database)]) -> DemoService:
    return DemoService(database)


def get_demo_movement_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> DemoMovementService:
    return DemoMovementService(database)


DemoServiceDependency = Annotated[DemoService, Depends(get_demo_service)]
DemoMovementServiceDependency = Annotated[DemoMovementService, Depends(get_demo_movement_service)]


@router.post(
    "", response_model=DemoResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
    summary="Crear una DEMO del vehículo",
    description=(
        "Comprueba el padre con sp_obtener_vehiculo(p_id_vehiculo), crea mediante "
        "sp_crear_demo(p_id_vehiculo, p_nombre, p_descripcion) y relee "
        "sp_obtener_demos(p_id_vehiculo) para responder en la misma transacción. "
        "El cuerpo exige nombre de hasta 80 caracteres; descripción admite null. "
        "MySQL asigna activo=true por defecto. Crear la DEMO no la ejecuta."
    ),
    responses={
        **WRITE_ERRORS,
        201: {"description": "DEMO creada con su representación completa."},
        **SECURITY_RESPONSES,
    },
)
def create_demo(
    id_vehiculo: VehiclePath, data: DemoCreate, service: DemoServiceDependency
) -> DemoResponse:
    return service.create(id_vehiculo, data)


@router.get(
    "", response_model=list[DemoResponse], summary="Listar las DEMO del vehículo",
    description=(
        "Comprueba el vehículo con sp_obtener_vehiculo(p_id_vehiculo) y consulta "
        "sp_obtener_demos(p_id_vehiculo) en una transacción READ ONLY. "
        "Incluye activas e inactivas en el orden de ID del SP. "
        "Un vehículo existente sin DEMO devuelve 200 con lista vacía."
    ),
    responses={**READ_ERRORS, 200: {"description": "Lista de DEMO, posiblemente vacía."}},
)
def list_demos(id_vehiculo: VehiclePath, service: DemoServiceDependency) -> list[DemoResponse]:
    return service.list_for_vehicle(id_vehiculo)


@router.put(
    "/{id_demo}", response_model=DemoResponse, summary="Actualizar una DEMO del vehículo",
    dependencies=[Depends(require_api_key)],
    description=(
        "Comprueba el padre con sp_obtener_vehiculo(p_id_vehiculo) y pertenencia mediante "
        "sp_obtener_demos(p_id_vehiculo). Ejecuta sp_actualizar_demo(p_id_demo, p_nombre, "
        "p_descripcion, p_activo) y relee el listado antes del commit. "
        "PUT exige nombre y activo booleano; omitir descripción la asigna a null. "
        "No cambia propietario ni ejecuta la secuencia."
    ),
    responses={
        **READ_ERRORS,
        200: {"description": "Representación completa de la DEMO actualizada."},
        **SECURITY_RESPONSES,
    },
)
def update_demo(
    id_vehiculo: VehiclePath, id_demo: DemoPath, data: DemoUpdate, service: DemoServiceDependency
) -> DemoResponse:
    return service.update(id_vehiculo, id_demo, data)


@router.delete(
    "/{id_demo}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_api_key)],
    summary="Eliminar una DEMO del vehículo",
    description=(
        "Comprueba el vehículo con sp_obtener_vehiculo(p_id_vehiculo), comprueba la DEMO "
        "y relee su ausencia con sp_obtener_demos(p_id_vehiculo). Elimina mediante "
        "sp_eliminar_demo(p_id_demo) en la misma transacción. La eliminación física "
        "aplica la cascada de movimientos definida por MySQL. No recibe cuerpo."
    ),
    responses={**READ_ERRORS, **SECURITY_RESPONSES, 204: {"description": "DEMO eliminada, sin contenido."}},
)
def delete_demo(
    id_vehiculo: VehiclePath, id_demo: DemoPath, service: DemoServiceDependency
) -> Response:
    service.delete(id_vehiculo, id_demo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{id_demo}/movimientos", response_model=DemoMovementResponse,
    status_code=status.HTTP_201_CREATED, summary="Agregar un movimiento a la DEMO",
    dependencies=[Depends(require_api_key)],
    description=(
        "Comprueba padre y DEMO con sp_obtener_vehiculo(p_id_vehiculo) y "
        "sp_obtener_demos(p_id_vehiculo); valida comando activo del mismo vehículo con "
        "sp_obtener_comandos_vehiculo(p_id_vehiculo). Ejecuta sp_agregar_movimiento_demo("
        "p_id_demo, p_id_comando, p_orden, p_duracion_ms, p_pausa_ms). Consulta "
        "sp_obtener_movimientos_demo(p_id_demo) antes y después para identificar la fila "
        "nueva por su orden único; el SP de alta no devuelve ID. "
        "Orden debe ser positivo; duración y pausa admiten cero y hasta 2147483647 "
        "por las firmas INT del SP. Pausa predeterminada: 0. Orden repetido produce 409. "
        "Todo ocurre en una transacción y no ejecuta el movimiento."
    ),
    responses={
        **MOVEMENT_ERRORS,
        201: {"description": "Movimiento creado y leído desde la misma DEMO."},
        **SECURITY_RESPONSES,
    },
)
def create_demo_movement(
    id_vehiculo: VehiclePath, id_demo: DemoPath, data: DemoMovementCreate,
    service: DemoMovementServiceDependency,
) -> DemoMovementResponse:
    return service.create(id_vehiculo, id_demo, data)


@router.get(
    "/{id_demo}/movimientos", response_model=list[DemoMovementResponse],
    summary="Listar los movimientos de la DEMO",
    description=(
        "Comprueba vehículo y pertenencia de DEMO con sp_obtener_vehiculo(p_id_vehiculo) "
        "y sp_obtener_demos(p_id_vehiculo), y consulta sp_obtener_movimientos_demo(p_id_demo) "
        "en una transacción READ ONLY. Conserva el orden del SP por orden ascendente. "
        "Una DEMO existente vacía devuelve 200 con lista vacía. La respuesta incluye "
        "comando y código del JOIN; el SP no devuelve id_demo. No modifica estado ni historial."
    ),
    responses={**READ_ERRORS, 200: {"description": "Movimientos ordenados, posiblemente ninguno."}},
)
def list_demo_movements(
    id_vehiculo: VehiclePath, id_demo: DemoPath, service: DemoMovementServiceDependency
) -> list[DemoMovementResponse]:
    return service.list_for_demo(id_vehiculo, id_demo)


@router.put(
    "/{id_demo}/movimientos/{id_demo_movimiento}", response_model=DemoMovementResponse,
    dependencies=[Depends(require_api_key)],
    summary="Actualizar un movimiento de la DEMO",
    description=(
        "Comprueba padre y DEMO con sp_obtener_vehiculo(p_id_vehiculo) y "
        "sp_obtener_demos(p_id_vehiculo), pertenencia del movimiento con "
        "sp_obtener_movimientos_demo(p_id_demo), y comando activo del vehículo con "
        "sp_obtener_comandos_vehiculo(p_id_vehiculo). Ejecuta sp_actualizar_movimiento_demo("
        "p_id_demo_movimiento, p_id_comando, p_orden, p_duracion_ms, p_pausa_ms) y relee "
        "el listado antes de confirmar. PUT exige los cuatro campos editables, incluida "
        "pausa_ms. Tiempos entre 0 y 2147483647; orden positivo. "
        "Un orden ya ocupado produce 409. El movimiento conserva su DEMO."
    ),
    responses={
        **MOVEMENT_ERRORS,
        200: {"description": "Movimiento actualizado con su representación completa."},
        **SECURITY_RESPONSES,
    },
)
def update_demo_movement(
    id_vehiculo: VehiclePath, id_demo: DemoPath, id_demo_movimiento: MovementPath,
    data: DemoMovementUpdate, service: DemoMovementServiceDependency,
) -> DemoMovementResponse:
    return service.update(id_vehiculo, id_demo, id_demo_movimiento, data)


@router.delete(
    "/{id_demo}/movimientos/{id_demo_movimiento}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response, summary="Eliminar un movimiento de la DEMO",
    dependencies=[Depends(require_api_key)],
    description=(
        "Comprueba vehículo y DEMO con sp_obtener_vehiculo(p_id_vehiculo) y "
        "sp_obtener_demos(p_id_vehiculo), y pertenencia del movimiento con "
        "sp_obtener_movimientos_demo(p_id_demo). Ejecuta sp_eliminar_movimiento_demo("
        "p_id_demo_movimiento) y relee la ausencia en una misma transacción. "
        "La eliminación es física; responde 204 sin contenido. No ejecuta comandos."
    ),
    responses={**READ_ERRORS, **SECURITY_RESPONSES,
               404: {"model": ErrorResponse, "description": "El vehículo, la DEMO o su movimiento no existe."},
               204: {"description": "Movimiento eliminado, sin contenido."}},
)
def delete_demo_movement(
    id_vehiculo: VehiclePath, id_demo: DemoPath, id_demo_movimiento: MovementPath,
    service: DemoMovementServiceDependency,
) -> Response:
    service.delete(id_vehiculo, id_demo, id_demo_movimiento)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
