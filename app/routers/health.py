"""Salud del proceso HTTP y diagnóstico independiente de RDS."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config.settings import Settings, get_settings
from app.database.connection import MySQLDatabase
from app.errors.database import DatabaseError
from app.models.health import (
    DatabaseHealthErrorResponse,
    DatabaseHealthResponse,
    HealthResponse,
)
from app.services.database_health import DatabaseHealthService


router = APIRouter(tags=["Salud"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Comprobar que FastAPI está funcionando",
    description=(
        "Verifica que la API local responde. No recibe parámetros ni cuerpo, "
        "no consulta RDS y no ejecuta Stored Procedures. "
        "No comprueba la conexión de un vehículo físico."
    ),
    responses={200: {"description": "El proceso HTTP está disponible."}},
)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Responder sin realizar operaciones sobre datos."""

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
    )


def get_database_health_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DatabaseHealthService:
    """Crear el servicio sin compartir sockets ni abrir conexiones todavía."""

    return DatabaseHealthService(MySQLDatabase(settings))


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    summary="Comprobar conexión Python → RDS y lectura de un SP",
    description=(
        "Abre una conexión con la configuración local y ejecuta "
        "sp_obtener_vehiculos(), sin parámetros, dentro de una transacción "
        "READ ONLY. Consume todos los resultados y termina con rollback. "
        "No modifica datos ni devuelve registros, credenciales o ubicación de RDS. "
        "No requiere parámetros ni cuerpo. Una colección vacía también es éxito."
    ),
    responses={
        200: {"description": "Conexión y Stored Procedure de lectura disponibles."},
        503: {
            "description": "No fue posible completar el diagnóstico de lectura.",
            "model": DatabaseHealthErrorResponse,
        },
    },
)
def database_health(
    service: Annotated[DatabaseHealthService, Depends(get_database_health_service)],
) -> DatabaseHealthResponse:
    """Ejecutar el driver síncrono en el pool de hilos de FastAPI."""

    try:
        service.check()
    except DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible completar la comprobación de lectura de la base de datos.",
        ) from None
    return DatabaseHealthResponse()
