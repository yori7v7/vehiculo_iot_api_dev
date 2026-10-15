"""Una tarea DEMO por vehículo; PyMySQL y su transacción quedan en un hilo."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from threading import Event
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.models.demo_execution import DemoExecutionPlan, DemoExecutionResponse
from app.services.demo_execution import DemoExecutionCancelled, DemoExecutionService
from app.websocket.demo_events import DemoEvent
from app.websocket.manager import WebSocketManager


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Execution:
    vehicle_id: int
    demo_id: int
    service: DemoExecutionService
    stop: Event = field(default_factory=Event)
    stop_async: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    plan: DemoExecutionPlan | None = None
    task: asyncio.Task[None] | None = None
    terminal: str | None = None


class DemoExecutionManager:
    """Reservar, ejecutar, cancelar y recoger tareas dentro de una aplicación."""

    def __init__(
        self,
        websocket_manager: WebSocketManager,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._websocket = websocket_manager
        self._sleep = sleep
        self._runs: dict[int, _Execution] = {}
        self._lock = asyncio.Lock()
        self._closing = False

    @property
    def active_count(self) -> int:
        return len(self._runs)

    @staticmethod
    def _stop(run: _Execution) -> None:
        run.stop.set()
        run.stop_async.set()

    @staticmethod
    async def _finish_cleanup(operation: Awaitable[Any]) -> Any:
        pending = asyncio.ensure_future(operation)
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(pending)
                break
            except asyncio.CancelledError:
                if pending.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError()
        return result

    async def _database_call(self, run: _Execution, function: Callable, *args, **kwargs):
        # Cancelar un await no detiene un driver síncrono. Retener y recoger su
        # tarea asegura que el vehículo no se libere con una transacción viva.
        pending = asyncio.create_task(run_in_threadpool(function, *args, **kwargs))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            self._stop(run)
            try:
                await self._finish_cleanup(pending)
            except (Exception, asyncio.CancelledError):
                pass
            raise

    async def _remove(self, run: _Execution) -> None:
        async with self._lock:
            if self._runs.get(run.vehicle_id) is run:
                del self._runs[run.vehicle_id]
            run.done.set()

    async def start(
        self, vehicle_id: int, demo_id: int, service: DemoExecutionService
    ) -> DemoExecutionResponse:
        async with self._lock:
            if self._closing or vehicle_id in self._runs:
                raise ResourceConflictError("Ya existe una DEMO activa o el servicio se está cerrando.")
            run = _Execution(vehicle_id, demo_id, service)
            self._runs[vehicle_id] = run
        try:
            run.plan = await self._database_call(run, service.prepare, vehicle_id, demo_id)
            if run.stop.is_set():
                await self._terminal(run, "demo_cancelada")
                raise ResourceConflictError("El inicio de la DEMO fue cancelado.")
            run.task = asyncio.create_task(
                self._run(run), name=f"demo:{vehicle_id}:{demo_id}"
            )
        except BaseException:
            try:
                # Si ya se aceptó cancelar una reserva, comunicar ese resultado
                # aunque la lectura de preparación termine fallando.
                if run.stop.is_set():
                    await self._terminal(run, "demo_cancelada")
            finally:
                await self._finish_cleanup(self._remove(run))
            raise
        return DemoExecutionResponse(id_vehiculo=vehicle_id, id_demo=demo_id, estado="iniciada")

    async def _broadcast(
        self, event: DemoEvent, *, should_send: Callable[[], bool] | None = None
    ) -> None:
        try:
            if should_send is None:
                await self._websocket.broadcast(event.id_vehiculo, event.model_dump(mode="json"))
            else:
                await self._websocket.broadcast(
                    event.id_vehiculo, event.model_dump(mode="json"), should_send=should_send
                )
        except Exception:
            logger.warning("No fue posible completar una notificación WebSocket de DEMO.")

    def _event(self, run: _Execution, kind: str, **fields) -> DemoEvent:
        return DemoEvent(
            tipo_evento=kind,
            id_vehiculo=run.vehicle_id,
            id_demo=run.demo_id,
            nombre_demo=run.plan.demo.nombre if run.plan is not None else None,
            timestamp=fields.pop("timestamp", datetime.now(timezone.utc)),
            **fields,
        )

    async def _emit(self, run: _Execution, kind: str, **fields) -> None:
        guard = (lambda: not run.stop.is_set()) if kind in ("demo_inicio", "demo_movimiento") else None
        await self._broadcast(self._event(run, kind, **fields), should_send=guard)

    async def _terminal(self, run: _Execution, kind: str, **fields) -> None:
        # Elegir el resultado sin await evita fin+cancelada si ambas solicitudes
        # coinciden al terminar el último paso.
        if run.terminal is None:
            run.terminal = kind
            await self._finish_cleanup(self._emit(run, kind, **fields))

    async def _until_stopped(self, run: _Execution, operation: Awaitable[Any]) -> Any:
        work = asyncio.ensure_future(operation)
        stopped = asyncio.create_task(run.stop_async.wait())
        try:
            await asyncio.wait((work, stopped), return_when=asyncio.FIRST_COMPLETED)
            if run.stop.is_set():
                raise DemoExecutionCancelled()
            return await work
        finally:
            for task in (work, stopped):
                if not task.done():
                    task.cancel()
            await self._finish_cleanup(asyncio.gather(work, stopped, return_exceptions=True))

    async def _run(self, run: _Execution) -> None:
        try:
            if run.stop.is_set():
                raise DemoExecutionCancelled()
            await self._until_stopped(run, self._emit(run, "demo_inicio"))
            assert run.plan is not None
            for movement in run.plan.movimientos:
                if run.stop.is_set():
                    raise DemoExecutionCancelled()
                state = await self._database_call(
                    run, run.service.apply_step, run.plan, movement, should_cancel=run.stop.is_set
                )
                if run.stop.is_set():
                    raise DemoExecutionCancelled()
                await self._until_stopped(run, self._emit(
                    run, "demo_movimiento", id_demo_movimiento=movement.id_demo_movimiento,
                    id_comando=state.id_comando, comando=state.comando, codigo=state.codigo,
                    orden=movement.orden, duracion_ms=movement.duracion_ms,
                    pausa_ms=movement.pausa_ms, conectado=state.conectado,
                    timestamp=state.fecha_actualizacion,
                ))
                await self._until_stopped(run, self._sleep(movement.duracion_ms / 1000))
                await self._until_stopped(run, self._sleep(movement.pausa_ms / 1000))
            if run.stop.is_set():
                raise DemoExecutionCancelled()
            await self._terminal(run, "demo_fin")
        except (DemoExecutionCancelled, asyncio.CancelledError):
            self._stop(run)
            await self._terminal(run, "demo_cancelada")
        except Exception:
            await self._terminal(run, "demo_error", mensaje="No fue posible completar la DEMO.")
        finally:
            await self._finish_cleanup(self._remove(run))

    async def cancel(self, vehicle_id: int, demo_id: int) -> DemoExecutionResponse:
        async with self._lock:
            run = self._runs.get(vehicle_id)
            if run is None or run.demo_id != demo_id or run.terminal is not None:
                raise ResourceNotFoundError("No hay una ejecución activa de esa DEMO para el vehículo.")
            self._stop(run)
        await self._finish_cleanup(run.done.wait())
        if run.task is not None:
            await self._finish_cleanup(run.task)
        return DemoExecutionResponse(id_vehiculo=vehicle_id, id_demo=demo_id, estado="cancelada")

    async def close_all(self) -> None:
        async with self._lock:
            self._closing = True
            runs = tuple(self._runs.values())
            for run in runs:
                self._stop(run)
        try:
            await self._finish_cleanup(asyncio.gather(*(run.done.wait() for run in runs)))
            await self._finish_cleanup(asyncio.gather(*(
                run.task for run in runs if run.task is not None
            )))
        finally:
            self._closing = False
