"""Consulta HTTP de los últimos registros del historial del vehículo."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.common import EntityId, ErrorResponse
from app.models.history import HistoryResponse
from app.services.history import HistoryService


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/historial", tags=["Historial"])


def get_history_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> HistoryService:
    return HistoryService(database)


@router.get(
    "",
    response_model=list[HistoryResponse],
    summary="Consultar hasta diez registros recientes del historial",
    description=(
        "Comprueba el padre con sp_obtener_vehiculo(id_vehiculo) y lee "
        "sp_obtener_historial(id_vehiculo) en una misma transacción READ ONLY. "
        "Devuelve como máximo diez registros existentes, conservando el orden "
        "del SP: fecha_hora DESC, id_historial DESC. No filtra por origen: "
        "incluye WORKBENCH y cualquier otro origen almacenado. La columna "
        "origen es VARCHAR y no un enum. "
        "Sin historial devuelve 200 con []; sin vehículo devuelve 404. "
        "Admite vehículos inactivos y campos comando, código y fecha NULL. "
        "No escribe ni borra historial."
    ),
    responses={
        200: {"description": "Hasta diez registros existentes, o una lista vacía."},
        404: {"model": ErrorResponse, "description": "El vehículo no existe."},
        500: {"model": ErrorResponse, "description": "El SP falló o devolvió datos inesperados."},
        503: {"model": ErrorResponse, "description": "La base de datos no está disponible o configurada."},
    },
)
def list_history(
    id_vehiculo: EntityId,
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> list[HistoryResponse]:
    return service.list_for_vehicle(id_vehiculo)
