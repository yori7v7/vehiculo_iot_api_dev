"""Punto de entrada y registro de routers de la API local."""

from fastapi import FastAPI

from app.config.settings import get_settings
from app.errors.handlers import register_exception_handlers
from app.routers.commands import router as commands_router
from app.routers.health import router as health_router
from app.routers.history import router as history_router
from app.routers.movement import router as movement_router
from app.routers.state import router as state_router
from app.routers.vehicles import router as vehicles_router


def create_app() -> FastAPI:
    """Construir la aplicación sin abrir conexiones a RDS."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.4.0",
        description=(
            "API local para la práctica 2.5. Etapa 4: estado, historial y movimiento individual atómico."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "Salud", "description": "Salud HTTP y diagnóstico de RDS MySQL."},
            {"name": "Vehículos", "description": "Creación, consulta, actualización y eliminación de vehículos."},
            {"name": "Comandos", "description": "Catálogo de comandos pertenecientes a cada vehículo."},
            {"name": "Estado", "description": "Consulta del estado persistido del vehículo."},
            {"name": "Historial", "description": "Hasta diez registros recientes, sin filtrar por origen."},
            {"name": "Movimientos", "description": "Movimiento individual con estado e historial en una transacción."},
        ],
    )
    application.include_router(health_router)
    application.include_router(vehicles_router)
    application.include_router(commands_router)
    application.include_router(state_router)
    application.include_router(history_router)
    application.include_router(movement_router)
    register_exception_handlers(application)
    return application


app = create_app()
