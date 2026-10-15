"""Consulta HTTP del estado persistido del vehículo."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.common import EntityId, ErrorResponse
from app.models.state import StateResponse
from app.services.state import StateService


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/estado", tags=["Estado"])


def get_state_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> StateService:
    return StateService(database)


@router.get(
    "",
    response_model=StateResponse | None,
    summary="Consultar estado persistido del vehículo",
    description=(
        "Comprueba el vehículo con sp_obtener_vehiculo(id_vehiculo) y consulta "
        "sp_obtener_estado(id_vehiculo) en una misma transacción READ ONLY. "
        "No ejecuta escrituras ni envía instrucciones a hardware. Un vehículo "
        "existente sin fila de estado devuelve 200 con JSON null. Un vehículo "
        "inexistente devuelve 404; los vehículos inactivos también se pueden consultar. "
        "El comando, código y fecha admiten NULL según el SELECT del SP."
    ),
    responses={
        200: {"description": "Estado almacenado o null si todavía no existe una fila de estado."},
        404: {"model": ErrorResponse, "description": "El vehículo no existe."},
        500: {"model": ErrorResponse, "description": "El SP falló o devolvió datos inesperados."},
        503: {"model": ErrorResponse, "description": "La base de datos no está disponible o configurada."},
    },
)
def get_state(
    id_vehiculo: EntityId,
    service: Annotated[StateService, Depends(get_state_service)],
) -> StateResponse | None:
    return service.get(id_vehiculo)
