"""Coordinador de DEMO para ASGI virtual 55-K, no producci?n."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hmac import compare_digest

from fastapi import HTTPException

from app.public_control.control_evidence_55k import (
    can_dispatch_virtual_55k,
)
from app.public_control.control_permissions_55k import ADMIN, GUEST
from app.public_control.demo_programada_55k import (
    ejecutar_demo_virtual,
    validar_plan,
)


@dataclass
class DemoRun55K:
    role: str
    credential: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "ejecutando"
    chunks: int = 0
    task: asyncio.Task | None = None


class DemoCoordinator55K:
    """Una DEMO por aplicaci?n y reserva del control manual."""

    def __init__(self, authority, ledger_plan=None, cycles=1):
        if ledger_plan is not None:
            validar_plan(ledger_plan, cycles)

        self.authority = authority
        self.hub = authority.hub
        self.plan = ledger_plan
        self.cycles = cycles
        self._active = None
        self._last = None

    @property
    def active(self):
        return self._active is not None

    def _authorized(self, ledger, role, credential):
        return can_dispatch_virtual_55k(
            ledger,
            server_role=role,
            credential=credential,
            action="demo_programada",
            authenticated_device=self.hub.ready,
        )

    @staticmethod
    def _owns(run, role, credential):
        return (
            run.role == role
            and type(credential) is str
            and compare_digest(run.credential, credential)
        )

    async def start(self, ledger, role, credential):
        async with self.authority.lock:
            if not self._authorized(ledger, role, credential):
                raise HTTPException(403, "Turno no autorizado")

            if self.plan is None:
                raise HTTPException(503, "Plan servidor no disponible")

            if self.active:
                raise HTTPException(409, "DEMO ya en ejecucion")

            run = DemoRun55K(role, credential)
            self._active = run
            self._last = None
            self.authority.demo_busy = True

            run.task = asyncio.create_task(
                self._run(ledger, run)
            )

        return self._reply("iniciada", 0)

    def _reply(self, status, chunks):
        return {
            "estado": status,
            "tramos": chunks,
            "simulado": True,
            "control_fisico": False,
            "canDrive": False,
            "stop_fisico_confirmado": False,
        }

    async def _run(self, ledger, run):
        status = "error_virtual"

        def authorized():
            return self._authorized(
                ledger, run.role, run.credential
            )

        async def send(code, duration):
            if run.cancel.is_set():
                raise HTTPException(409, "DEMO cancelada")

            async with self.authority.lock:
                if run.cancel.is_set() or not authorized():
                    raise HTTPException(409, "Turno cancelado")

                if run.role == ADMIN:
                    await self.hub.execute_admin_virtual(
                        ledger, run.credential, code, duration
                    )
                else:
                    await self.hub.execute_virtual(
                        ledger, run.credential, code, duration
                    )

                run.chunks += 1

        try:
            status = await ejecutar_demo_virtual(
                self.plan,
                self.cycles,
                enviar=send,
                autorizado=authorized,
                cancelar=run.cancel,
            )
        except HTTPException as exc:
            status = (
                "cancelada"
                if exc.status_code in (403, 409)
                else "error_virtual"
            )
        except asyncio.CancelledError:
            status = "cancelada"
        except Exception:
            status = "error_virtual"
        finally:
            run.status = status

            async with self.authority.lock:
                if self._active is run:
                    self._active = None
                    self.authority.demo_busy = False

                self._last = run

            run.done.set()

    async def cancel(self, role, credential):
        run = self._active

        if run is None:
            raise HTTPException(404, "No existe DEMO activa")

        if not self._owns(run, role, credential):
            raise HTTPException(403, "DEMO de otro controlador")

        # Se interrumpe cooperativamente. K-X debe completar su
        # STOP firmado para el tramo en curso antes de liberar.
        run.cancel.set()
        await run.done.wait()

        return self._reply(run.status, run.chunks)

    def status(self, role, credential):
        run = self._active or self._last

        if run is None or not self._owns(
            run, role, credential
        ):
            return self._reply("sin_demo", 0)

        return self._reply(run.status, run.chunks)

    def request_cancel(self):
        if self._active is not None:
            self._active.cancel.set()

    async def close(self):
        run = self._active
        self.request_cancel()

        if run is not None:
            await run.done.wait()
