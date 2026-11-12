"""Impedir que una instancia de simulación envíe órdenes por las rutas reales."""

from fastapi import HTTPException
from starlette.requests import HTTPConnection


async def require_legacy_dispatch(connection: HTTPConnection) -> None:
    if getattr(connection.app.state, "public_control_simulation", False):
        raise HTTPException(
            status_code=503,
            detail="El despacho existente está aislado durante la simulación de control público.",
        )
