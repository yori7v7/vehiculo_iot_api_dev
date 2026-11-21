"""Punto de entrada y registro de routers de la API de vehículos IoT."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.database.connection import MySQLDatabase
from app.errors.handlers import register_exception_handlers
from app.execution.manager import DemoExecutionManager
from app.legacy_boundary import LegacySchemaBoundary
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

    maintenance = None
    if application.state.platform_mode:
        from app.platform43.guests import maintenance as maintain
        maintenance = asyncio.create_task(maintain(application.state, application.state.platform_database))
    try:
        yield
    finally:
        if maintenance:
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance
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
        ],
    )
    mode = settings.platform43_enabled
    origins = ["https://yori7v7.github.io"]
    if mode and settings.app_env == "development":
        origins += ["http://127.0.0.1:4173", "http://localhost:4173"]
    if not mode:
        application.add_middleware(LegacySchemaBoundary, database=MySQLDatabase(settings))
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"] if mode else ["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"] if mode else ["Content-Type", "X-API-Key"],
    )

    application.state.platform_mode = mode
    application.include_router(health_router)
    if mode:
        from app.platform43 import admin, auth, demos, guests, operations, sockets

        @application.middleware("http")
        async def protect_platform_cache(request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/plataforma/"):
                response.headers["Cache-Control"] = "no-store"
            return response

        application.version = "4.3.0"
        application.description = "Plataforma IoT con autenticación individual, reservas exclusivas y autorización por unidad."
        application.state.platform_origins = origins
        application.state.platform_lock = asyncio.Lock()
        application.state.platform_database = MySQLDatabase(settings)
        application.state.websocket_manager = sockets.PlatformEvents(
            dispatch=settings.platform43_dispatch and settings.app_env == "production",
            device_connections=settings.app_env == "production",
        )
        for module in (auth, admin, demos, guests, operations, sockets):
            application.include_router(module.router)
    else:
        application.state.websocket_manager = WebSocketManager()
        for router in (vehicles_router, commands_router, state_router, history_router, movement_router,
                       demos_router, demo_execution_router, websocket_router):
            application.include_router(router)
    application.state.demo_execution_manager = DemoExecutionManager(application.state.websocket_manager)

    @application.exception_handler(RequestValidationError)
    async def validation(request: Request, error: RequestValidationError):
        if mode and request.url.path.startswith("/plataforma/"):
            return JSONResponse(status_code=422, content={"detail": [
                {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                for item in error.errors()
            ]})
        return await request_validation_exception_handler(request, error)
    register_exception_handlers(application)
    return application


app = create_app()
