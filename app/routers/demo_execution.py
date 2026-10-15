"""Inicio y cancelación lógica de DEMOS; la secuencia vive en el manager."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.execution.dependencies import get_demo_execution_manager
from app.execution.manager import DemoExecutionManager
from app.models.common import EntityId, ErrorResponse
from app.models.demo_execution import DemoExecutionResponse
from app.services.demo_execution import DemoExecutionService
from app.security.api_key import SECURITY_RESPONSES, require_api_key


router = APIRouter(prefix="/vehiculos/{id_vehiculo}/demos/{id_demo}", tags=["DEMO"])


def get_demo_execution_service(
    database: Annotated[MySQLDatabase, Depends(get_database)],
) -> DemoExecutionService:
    return DemoExecutionService(database)


@router.post(
    "/ejecutar", status_code=202, response_model=DemoExecutionResponse,
    dependencies=[Depends(require_api_key)],
    summary="Iniciar DEMO en segundo plano",
    description=(
        "Sin cuerpo. Comprueba vehículo activo mediante sp_obtener_vehiculo y DEMO "
        "activa/propia con sp_obtener_demos. Obtiene N movimientos dinámicamente de "
        "sp_obtener_movimientos_demo, en su orden, y valida sus comandos con "
        "sp_obtener_comandos_vehiculo. No hay secuencia hardcodeada. Tras validar "
        "responde 202 y ejecuta la secuencia en segundo plano. Por paso consulta "
        "sp_obtener_estado, conserva conectado y ejecuta sp_actualizar_estado con "
        "relectura y commit antes del evento demo_movimiento por WebSocket. "
        "Respeta duracion_ms y pausa_ms, incluida la pausa final, con esperas asíncronas. "
        "Nunca llama sp_registrar_historial: DEMO no se guarda en historial. "
        "Una ejecución por vehículo; distintos vehículos pueden coexistir. "
        "Todavía no controla hardware físico."
    ),
    responses={
        202: {"description": "Validación completada y tarea iniciada."},
        404: {"model": ErrorResponse, "description": "Vehículo o DEMO propia inexistente."},
        409: {"model": ErrorResponse, "description": "Recurso inactivo, comando no disponible, secuencia vacía/incoherente o vehículo ocupado."},
        500: {"model": ErrorResponse, "description": "Datos o procedimiento inesperados."},
        503: {"model": ErrorResponse, "description": "Base de datos no disponible."},
        **SECURITY_RESPONSES,
    },
)
async def execute_demo(
    id_vehiculo: EntityId, id_demo: EntityId,
    service: Annotated[DemoExecutionService, Depends(get_demo_execution_service)],
    manager: Annotated[DemoExecutionManager, Depends(get_demo_execution_manager)],
) -> DemoExecutionResponse:
    return await manager.start(id_vehiculo, id_demo, service)


@router.post(
    "/cancelar", response_model=DemoExecutionResponse,
    dependencies=[Depends(require_api_key)],
    summary="Cancelar la DEMO activa del vehículo",
    description=(
        "Sin cuerpo ni SP propio. Interrumpe inmediatamente las esperas de duración "
        "o pausa y evita nuevos pasos y eventos de movimiento. Si hay una operación "
        "MySQL en curso, solicita rollback antes del commit cuando aún es posible y "
        "espera a su cierre antes de liberar el vehículo. No inventa un comando DETENER, "
        "no registra historial y emite demo_cancelada. La cancelación es lógica."
    ),
    responses={
        200: {"description": "Ejecución recogida y vehículo liberado."},
        404: {"model": ErrorResponse, "description": "No hay ejecución activa de esa DEMO para ese vehículo."},
        500: {"model": ErrorResponse, "description": "No fue posible procesar la cancelación."},
        **SECURITY_RESPONSES,
    },
)
async def cancel_demo(
    id_vehiculo: EntityId, id_demo: EntityId,
    manager: Annotated[DemoExecutionManager, Depends(get_demo_execution_manager)],
) -> DemoExecutionResponse:
    return await manager.cancel(id_vehiculo, id_demo)
