"""Endpoint del movimiento individual; delegar toda la operación al servicio."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from starlette.concurrency import run_in_threadpool

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.models.common import ErrorResponse, INT_MAX
from app.models.movement import MovementRequest, MovementResponse
from app.public_control.legacy_guard import require_legacy_dispatch
from app.services.movement import MovementService
from app.security.api_key import SECURITY_RESPONSES, require_api_key
from app.websocket.publisher import MovementEventPublisher, get_movement_publisher


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/movimientos", tags=["Movimientos"])


def get_movement_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> MovementService:
    """Construir el servicio sin abrir una conexión en la dependencia."""

    return MovementService(database)


@router.post(
    "",
    response_model=MovementResponse,
    dependencies=[Depends(require_api_key), Depends(require_legacy_dispatch)],
    summary="Registrar un movimiento individual del vehículo",
    description=(
        "Recibe únicamente id_comando de un comando existente del vehículo. Comprueba "
        "existencia, pertenencia y estado activo con sp_obtener_vehiculo(p_id_vehiculo) "
        "y sp_obtener_comandos_vehiculo(p_id_vehiculo). Lee sp_obtener_estado(p_id_vehiculo) "
        "para conservar conectado; si no existe estado usa false. En una misma conexión "
        "y transacción ejecuta sp_actualizar_estado(p_id_vehiculo, p_id_comando, p_conectado) "
        "y después sp_registrar_historial(p_id_vehiculo, p_id_comando, p_origen), con origen "
        "fijo API. Relee sp_obtener_estado para devolver los valores reales y confirma "
        "una sola vez antes de responder. Si falla cualquier paso revierte ambas escrituras. "
        "Sólo después del commit exitoso publica un evento movimiento a los clientes "
        "WebSocket de ese vehículo. La ausencia o fallo de clientes no revierte el commit. "
        "La operación registra la orden en la base de datos; el control y la confirmación "
        "del hardware corresponden a una integración futura."
    ),
    responses={
        200: {"description": "Estado e historial confirmados en una sola transacción."},
        404: {
            "model": ErrorResponse,
            "description": "El vehículo o el comando solicitado de ese vehículo no existe.",
        },
        409: {
            "model": ErrorResponse,
            "description": "Vehículo o comando inactivo, o conflicto de integridad.",
        },
        500: {"model": ErrorResponse, "description": "No fue posible procesar la operación."},
        503: {"model": ErrorResponse, "description": "La base de datos no está disponible."},
        **SECURITY_RESPONSES,
    },
)
async def execute_movement(
    id_vehiculo: Annotated[
        int, Path(gt=0, le=INT_MAX, description="Identificador positivo del vehículo.")
    ],
    data: MovementRequest,
    service: Annotated[MovementService, Depends(get_movement_service)],
    publisher: Annotated[MovementEventPublisher, Depends(get_movement_publisher)],
) -> MovementResponse:
    # El servicio sólo retorna después del commit y del cierre de su conexión.
    response = await run_in_threadpool(service.execute, id_vehiculo, data)
    await publisher.publish(response)
    return response
