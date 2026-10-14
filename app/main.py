"""Punto de entrada y registro de routers de la API local."""

from fastapi import FastAPI

from app.config.settings import get_settings
from app.routers.health import router as health_router


def create_app() -> FastAPI:
    """Construir la aplicación sin abrir conexiones a RDS."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API local para la práctica 2.5. Etapa 1: salud y configuración.",
        docs_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "Salud", "description": "Disponibilidad del proceso HTTP local."}
        ],
    )
    application.include_router(health_router)
    return application


app = create_app()
