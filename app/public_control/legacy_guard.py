"""Impedir saltos del coordinador cuando otra autoridad posee el canal de control.

Esto no conecta Swagger a la nueva autoridad: bloquea de forma conservadora
movimientos y DEMO heredados cuando se active el coordinador exclusivo.
"""

from fastapi import HTTPException
from starlette.requests import HTTPConnection


async def require_legacy_dispatch(connection: HTTPConnection) -> None:
    state = connection.app.state
    if getattr(state, "exclusive_device_control_enabled", False) or getattr(state, "public_control_simulation", False):
        raise HTTPException(
            status_code=503,
            detail="El despacho existente está aislado mientras opera otro coordinador de control.",
        )
