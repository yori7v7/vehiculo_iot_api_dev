"""Claves independientes para administración y control directo del vehículo 1."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.requests import HTTPConnection

from app.config.settings import Settings, get_settings
from app.models.common import ErrorResponse


api_key_header = APIKeyHeader(
    name="X-API-Key", scheme_name="LocalApiKey",
    description=(
        "API_KEY autoriza administración y control. API_KEY_OPERATOR sólo autoriza "
        "movimiento e inicio/cancelación de DEMO del vehículo 1."
    ),
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


OPERATOR_ROUTES = frozenset({
    "/vehiculos/{id_vehiculo}/movimientos",
    "/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar",
    "/vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar",
})


def usable_key(value: str) -> bool:
    """No aceptar marcadores públicos ni valores ambiguos en un header."""
    return (
        bool(value)
        and not any(char.isspace() for char in value)
        and "," not in value
        and value.casefold() not in {
            "change-me", "changeme", "replace-me", "your-api-key", "your-operator-key", "default",
        }
    )


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
    operator = settings.api_key_operator.get_secret_value()
    # Una misma clave no puede identificar dos privilegios distintos.
    if expected and expected == operator:
        raise HTTPException(status_code=503, detail="El servicio de autorización no está disponible.")
    # Bytes permiten headers no ASCII sin TypeError ni reflejar su contenido.
    if usable_key(expected) and compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return
    route = connection.scope.get("route")
    operator_allowed = (
        connection.scope.get("method") == "POST"
        and getattr(route, "path", None) in OPERATOR_ROUTES
        and str(connection.path_params.get("id_vehiculo")) == "1"
        and usable_key(operator)
    )
    if operator_allowed and compare_digest(supplied.encode("utf-8"), operator.encode("utf-8")):
        return
    if not usable_key(expected) and not operator_allowed:
        raise HTTPException(status_code=503, detail="El servicio de autorización no está disponible.")
    raise HTTPException(status_code=403, detail="La credencial no está autorizada.")
