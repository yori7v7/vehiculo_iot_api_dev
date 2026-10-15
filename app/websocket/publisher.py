"""Publicar movimientos confirmados sin acoplar WebSocket a la transacción."""

import logging
from typing import Annotated

from fastapi import Depends

from app.models.movement import MovementResponse
from app.websocket.dependencies import get_websocket_manager
from app.websocket.events import MovementEvent
from app.websocket.manager import WebSocketManager


logger = logging.getLogger(__name__)


class MovementEventPublisher:
    """Notificación en memoria: un fallo de entrega no revierte un commit."""

    def __init__(self, manager: WebSocketManager) -> None:
        self.manager = manager

    async def publish(self, movement: MovementResponse) -> None:
        try:
            event = MovementEvent.from_movement(movement).model_dump(mode="json")
            await self.manager.broadcast(movement.id_vehiculo, event)
        except Exception:
            # No propagar un fallo de transporte como fallo de la escritura ya
            # confirmada, ni registrar detalles internos o reintentar el POST.
            logger.warning("No fue posible completar la notificación WebSocket del movimiento confirmado.")


async def get_movement_publisher(
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> MovementEventPublisher:
    return MovementEventPublisher(manager)
