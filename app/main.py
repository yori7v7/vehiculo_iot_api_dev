"""Punto de entrada y registro de routers de la API de vehículos IoT."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config.settings import get_settings
from app.device_channel.ws_lab import DeviceLabRegistry, router as device_lab_router
from app.errors.handlers import register_exception_handlers
from app.execution.manager import DemoExecutionManager
from app.public_control.http import ScopedControlMiddleware, router as public_control_router
from app.public_control.runtime import public_control_runtime
from app.routers.commands import router as commands_router
from app.routers.demos import router as demos_router
from app.routers.demo_execution import router as demo_execution_router
from app.routers.health import router as health_router
from app.routers.history import router as history_router
from app.routers.movement import router as movement_router
from app.routers.state import router as state_router
from app.routers.vehicles import router as vehicles_router
from app.websocket.manager import WebSocketManager
from app.websocket.router import router as websocket_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Cerrar las suscripciones locales al detener o recargar el proceso."""

    try:
        async with public_control_runtime(application):
            yield
    finally:
        try:
            await application.state.demo_execution_manager.close_all()
        finally:
            await application.state.websocket_manager.close_all()


def create_app() -> FastAPI:
    """Construir la aplicación sin abrir conexiones a RDS."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.7.0",
        description=(
            "API de vehículos IoT para desarrollo y producción. Escrituras administrativas y de "
            "control protegidas mediante X-API-Key. Consultar README para WebSocket y pruebas funcionales."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "Salud", "description": "Salud HTTP y diagnóstico de RDS MySQL."},
            {"name": "Vehículos", "description": "Creación, consulta, actualización y eliminación de vehículos."},
            {"name": "Comandos", "description": "Catálogo de comandos pertenecientes a cada vehículo."},
            {"name": "Estado", "description": "Consulta del estado persistido del vehículo."},
            {"name": "Historial", "description": "Hasta diez registros recientes, sin filtrar por origen."},
            {"name": "Movimientos", "description": "Movimiento individual con estado e historial en una transacción."},
            {"name": "DEMO", "description": "Configuración, ejecución asíncrona y cancelación lógica por vehículo."},
            {"name": "Administración de control simulado", "description": "Ventanas y auditoría de simulación local."},
            {"name": "Control público simulado", "description": "Turnos exclusivos y órdenes de simulación local."},
        ],
    )
    application.add_middleware(ScopedControlMiddleware)

    application.state.public_control_settings = settings
    application.state.public_control_simulation = (
        settings.control_publico_enabled or settings.control_publico_simulation
    )
    application.state.public_control = None
    application.state.public_control_unavailable = False
    application.state.device_lab_settings = settings
    application.state.device_lab_registry = DeviceLabRegistry()
    application.state.websocket_manager = WebSocketManager()
    application.state.demo_execution_manager = DemoExecutionManager(application.state.websocket_manager)
    application.include_router(health_router)
    application.include_router(vehicles_router)
    application.include_router(commands_router)
    application.include_router(state_router)
    application.include_router(history_router)
    application.include_router(movement_router)
    application.include_router(demos_router)
    application.include_router(demo_execution_router)
    application.include_router(public_control_router)
    application.include_router(websocket_router)
    # WSS de laboratorio aislado, sin capacidad de actuación física.
    application.include_router(device_lab_router)
    register_exception_handlers(application)
    return application


app = create_app()
