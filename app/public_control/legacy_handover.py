"""K-E: barrera de transicion fail-closed, sin control de hardware.

Unica instancia ASGI de laboratorio: no sincroniza Uvicorn workers ni reinicios.
No activar un control fisico solo porque phase == 'exclusive'.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import HTTPException

Phase = Literal["legacy", "draining", "exclusive", "blocked"]


class HandoverRefused(RuntimeError):
    """No se demostro que la transicion haya terminado en neutro logico."""


class LegacyHandoverGate:
    """Cierra entradas legacy, drena requests y recoge DEMO antes de exclusividad.

    No registra ninguna ruta HTTP de activacion. La autoridad confiable debe
    aportar close_demos() y signed_stop_ack(), NO un booleano de navegador.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._phase: Phase = "legacy"
        self._active_requests = 0

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def in_flight(self) -> int:
        return self._active_requests

    @asynccontextmanager
    async def legacy_request(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._phase != "legacy":
                raise HTTPException(503, "El despacho legacy está aislado por un coordinador exclusivo.")
            self._active_requests += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_requests -= 1
                self._condition.notify_all()

    async def prepare_exclusive(
        self,
        *,
        close_demos: Callable[[], Awaitable[None]],
        signed_stop_ack: Callable[[], Awaitable[bool]],
        timeout_s: float = 10.0,
    ) -> None:
        """Exige drenaje + cancelacion DEMO + ACK firmado comprobado externamente.

        En cualquier fallo mantiene bloqueadas las escrituras legacy. El
        parametro signed_stop_ack debe ser callback de transporte seguro;
        no conectar a HTTP ni usar un callback de prueba para produccion.
        """
        if not callable(close_demos) or not callable(signed_stop_ack) or not 0 < timeout_s <= 60:
            raise ValueError("Configuracion de transferencia invalida.")
        async with self._condition:
            if self._phase != "legacy":
                raise HandoverRefused("Transferencia ya iniciada o sistema bloqueado.")
            self._phase = "draining"  # Denegar nuevas entradas antes del primer await externo.
        try:
            async with asyncio.timeout(timeout_s):
                async with self._condition:
                    await self._condition.wait_for(lambda: self._active_requests == 0)
                # Una DEMO puede vivir mas que su POST que la inicio.
                await close_demos()
                if await signed_stop_ack() is not True:
                    raise HandoverRefused("El transporte no confirmo un ACK STOP firmado.")
        except BaseException:
            async with self._condition:
                self._phase = "blocked"  # No desbloquear por timeout, excepcion o cancelacion.
            raise
        async with self._condition:
            self._phase = "exclusive"
