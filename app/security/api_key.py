"""Una clave privada autoriza control y eliminación; ninguna credencial se imprime."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.requests import HTTPConnection

from app.config.settings import Settings, get_settings
from app.models.common import ErrorResponse


api_key_header = APIKeyHeader(
    name="X-API-Key", scheme_name="LocalApiKey",
    description="Clave privada configurada mediante API_KEY. Autoriza control y eliminación.",
    auto_error=False,
)

SECURITY_RESPONSES = {
    401: {
        "model": ErrorResponse, "description": "Falta el header X-API-Key.",
        "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
    },
    403: {"model": ErrorResponse, "description": "La credencial proporcionada no está autorizada."},
    503: {"model": ErrorResponse, "description": "Servicio no disponible por configuración o infraestructura."},
}


async def require_api_key(
    connection: HTTPConnection,
    supplied: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Comparar en tiempo constante y rechazar claves ambiguas o no configuradas."""

    headers = connection.headers.getlist("x-api-key")
    if not headers:
        raise HTTPException(
            status_code=401, detail="Se requiere autenticación mediante X-API-Key.",
            headers={"WWW-Authenticate": 'ApiKey realm="vehiculo_iot_api_dev"'},
        )
    if len(headers) != 1 or not supplied:
        raise HTTPException(status_code=403, detail="La credencial no está autorizada.")
    expected = settings.api_key.get_secret_value()
    if not expected.strip() or expected in {"change-me", "changeme"}:
        raise HTTPException(status_code=503, detail="El servicio de autorización no está disponible.")
    # Bytes permiten headers no ASCII sin TypeError ni reflejar su contenido.
    if not compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="La credencial no está autorizada.")
