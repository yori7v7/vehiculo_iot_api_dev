"""Cerrar las escrituras historicas al activar la autoridad exclusiva."""
from collections.abc import AsyncIterator

from fastapi import HTTPException
from starlette.requests import HTTPConnection


async def require_legacy_dispatch(connection: HTTPConnection) -> AsyncIterator[None]:
    state = connection.app.state
    if getattr(state, "exclusive_device_control_enabled", False) or getattr(state, "public_control_simulation", False):
        raise HTTPException(
            status_code=503,
            detail="El despacho existente está aislado mientras opera otro coordinador de control.",
        )
    gate = getattr(state, "legacy_handover", None)
    if gate is None:
        yield
    else:
        async with gate.legacy_request():
            yield
