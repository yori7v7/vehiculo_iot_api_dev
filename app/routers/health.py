"""Ruta de salud independiente de la base de datos."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config.settings import Settings, get_settings
from app.models.health import HealthResponse


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
