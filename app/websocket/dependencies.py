"""Dependencia del administrador WebSocket compartido por la aplicación."""

from starlette.requests import HTTPConnection

from app.websocket.manager import WebSocketManager


async def get_websocket_manager(connection: HTTPConnection) -> WebSocketManager:
    """Reutilizar el manager de lifespan o crearlo para una aplicación aislada."""

    manager = getattr(connection.app.state, "websocket_manager", None)
    if manager is None:
        # No hay await entre comprobar y asignar: las solicitudes del mismo
        # event loop obtienen una única instancia, sin abrir conexiones MySQL.
        manager = WebSocketManager()
        connection.app.state.websocket_manager = manager
    return manager
