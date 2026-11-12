"""Ciclo de vida del coordinador local y de sus vencimientos."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timezone
import logging
from time import monotonic

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.public_control.domain import PublicControlError
from app.public_control.ownership import CoordinatorOwnership, CoordinatorUnavailable
from app.public_control.repository import PublicControlRepository, StoreUnavailable
from app.public_control.service import PublicControlService
from app.public_control.simulator import SimulatedVehicleDispatcher


logger = logging.getLogger(__name__)
SWEEP_INTERVAL = 0.05


async def _sweep(
    application: FastAPI, service: PublicControlService,
    dispatcher: SimulatedVehicleDispatcher, closing: asyncio.Event,
) -> None:
    while not closing.is_set():
        try:
            await asyncio.wait_for(closing.wait(), timeout=SWEEP_INTERVAL)
        except TimeoutError:
            try:
                await run_in_threadpool(service.tick)
            except Exception:
                dispatcher.interlock()
                application.state.public_control = None
                application.state.public_control_unavailable = True
                logger.error("Coordinación de control simulado bloqueada.")
                return


@asynccontextmanager
async def public_control_runtime(application: FastAPI) -> AsyncIterator[None]:
    settings = application.state.public_control_settings
    if not application.state.public_control_simulation:
        yield
        return
    path = settings.control_publico_sqlite_path
    if not (
        settings.control_publico_enabled and settings.control_publico_simulation
        and settings.app_env == "development" and path is not None
    ):
        application.state.public_control_unavailable = True
        yield
        return

    dispatcher = SimulatedVehicleDispatcher()
    with ExitStack() as resources:
        try:
            resources.enter_context(CoordinatorOwnership(path))
            repository = PublicControlRepository(path)
            await run_in_threadpool(repository.initialize)
            service = PublicControlService(
                repository, dispatcher, now=lambda: datetime.now(timezone.utc), monotonic=monotonic,
                vehicle_ids=settings.control_publico_vehicle_ids,
                turn_seconds=settings.control_publico_turn_seconds,
                inactivity_seconds=settings.control_publico_inactivity_seconds,
                rate_per_second=settings.control_publico_rate_per_second,
            )
            await run_in_threadpool(service.recover)
        except (CoordinatorUnavailable, StoreUnavailable, PublicControlError):
            dispatcher.interlock()
            resources.close()
            application.state.public_control_unavailable = True
            logger.error("Control simulado no disponible al iniciar.")
            yield
            return

        application.state.public_control = service
        application.state.public_control_unavailable = False
        closing = asyncio.Event()
        sweeper = asyncio.create_task(_sweep(application, service, dispatcher, closing))
        try:
            yield
        finally:
            closing.set()
            await sweeper
            dispatcher.interlock()
            application.state.public_control = None
