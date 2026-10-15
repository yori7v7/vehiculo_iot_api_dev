"""Suscripciones WebSocket por vehículo, sin operaciones de escritura."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.errors.database import DatabaseError
from app.errors.domain import ResourceNotFoundError
from app.models.common import INT_MAX
from app.routers.state import get_state_service
from app.services.state import StateService
from app.websocket.dependencies import get_websocket_manager
from app.websocket.events import InitialStateEvent
from app.websocket.manager import WebSocketManager


router = APIRouter()
_CLOSE_TIMEOUT_SECONDS = 5.0


def _vehicle_id(path_value: str) -> int | None:
    """Validar antes de consultar datos y controlar el cierre por ID incorrecto."""

    if (
        not path_value.isascii()
        or not path_value.isdecimal()
        or len(path_value) > 10
    ):
        return None
    value = int(path_value)
    return value if 0 < value <= INT_MAX else None


async def _close_safely(websocket: WebSocket, code: int, reason: str) -> None:
    """Un socket desconectado no debe impedir liberar su suscripción."""

    try:
        await asyncio.wait_for(
            websocket.close(code=code, reason=reason), timeout=_CLOSE_TIMEOUT_SECONDS
        )
    except (TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
        pass


@router.websocket("/ws/vehiculos/{id_vehiculo}")
async def vehicle_websocket(
    websocket: WebSocket,
    id_vehiculo: str,
    service: Annotated[StateService, Depends(get_state_service)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> None:
    """Enviar el estado inicial real y observar la desconexión del cliente.

    El manager carga el estado bajo el lock del vehículo antes de aceptar y
    registrar el socket. Los rechazos previos al handshake usan close 1008
    (ID inválido/vehículo ausente) o 1011 (fallo interno); Uvicorn puede
    representarlos como HTTP 403 porque todavía no hay un WebSocket aceptado.
    Ningún mensaje entrante ejecuta comandos ni cambia el campo conectado.
    """

    vehicle_id = _vehicle_id(id_vehiculo)
    if vehicle_id is None:
        await _close_safely(websocket, 1008, "El identificador del vehículo no es válido.")
        return

    async def initial_event() -> dict:
        state = await run_in_threadpool(service.get, vehicle_id)
        return InitialStateEvent.from_state(vehicle_id, state).model_dump(mode="json")

    try:
        await manager.connect(vehicle_id, websocket, initial_event)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except ResourceNotFoundError:
        await _close_safely(websocket, 1008, "El vehículo no existe.")
    except DatabaseError:
        await _close_safely(websocket, 1011, "No fue posible consultar el estado del vehículo.")
    except Exception:
        await _close_safely(websocket, 1011, "No fue posible mantener la conexión WebSocket.")
    finally:
        await manager.disconnect(vehicle_id, websocket)
