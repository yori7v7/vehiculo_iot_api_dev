"""Una instancia de ejecuciones por aplicación, compartida con WebSocket."""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from app.execution.manager import DemoExecutionManager
from app.websocket.dependencies import get_websocket_manager
from app.websocket.manager import WebSocketManager


async def get_demo_execution_manager(
    connection: HTTPConnection,
    websocket: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> DemoExecutionManager:
    manager = getattr(connection.app.state, "demo_execution_manager", None)
    if manager is None:
        manager = DemoExecutionManager(websocket)
        connection.app.state.demo_execution_manager = manager
    return manager
