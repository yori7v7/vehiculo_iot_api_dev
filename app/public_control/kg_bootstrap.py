"""5.5-K-G: FastAPI principal + K-C WSS en un UNICO ASGI, SOLO laboratorio.

El modulo no importa servidor_55kc en la API normal y no habilita motores.
Requiere firmware 55-H con GPIO diagnosticamente inhibido.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from starlette.routing import WebSocketRoute

from app.public_control.kf_attach import attach_verified_kf_bridge
from app.public_control.ki_ingress import GuestIngressLab

LOG = logging.getLogger(__name__)
WSS_PATH = "/ws/dispositivos-lab/1/contrato"


def create_kg_app(kc_module, *, app_factory=None) -> FastAPI:
    """Reutilizar el KCController que autentica el ESP; nunca crear otro."""
    if app_factory is None:
        from app.main import create_app
        app_factory = create_app
    application = app_factory()
    settings = getattr(application.state, "public_control_settings", None)
    if (settings is None or getattr(settings, "app_env", None) != "development"
            or getattr(settings, "control_publico_simulation", False)
            or getattr(settings, "device_lab_enabled", False)):
        raise RuntimeError("K-G exige desarrollo sin simuladores paralelos")
    if not callable(getattr(kc_module, "KCController", None)) or not callable(
            getattr(kc_module, "device_connection", None)):
        raise TypeError("Falta el servidor K-C autenticado")

    routes = [route for route in kc_module.app.router.routes
              if isinstance(route, WebSocketRoute) and route.path == WSS_PATH
              and route.endpoint is kc_module.device_connection]
    if len(routes) != 1:
        raise RuntimeError("WSS K-C ambiguo")

    # Desde el nacimiento de ASGI, denegar rutas antiguas. Un reinicio nunca
    # habilita el control legacy mientras el dispositivo se reconecta.
    application.state.exclusive_device_control_enabled = True
    application.state.kf_bridge = None
    application.state.kf_wss_controller = None
    application.state.kg_lab_local_ip = None
    application.state.kg_lab_mode = True
    application.state.kj_lab_enabled = False
    application.state.kj_expected_host = None
    # K-L: la admision oficial es inerte hasta el handover de K-G.
    application.state.ki_ingress = None
    application.state.ki_expected_host = None
    application.state.ki_contract_test_enabled = False

    # Esta ruta debe preceder al WSS de diagnostico antiguo, que usa el mismo path.
    # Su ws.app.state apunta a la misma instancia FastAPI principal.
    application.router.routes.insert(0, routes[0])
    original_lifespan = application.router.lifespan_context

    async def attach_when_ready(app: FastAPI, controller, admin_token, stopping):
        while not stopping.is_set():
            barrier = app.state.legacy_handover
            # Una perdida WSS cierra ambas puertas; no auto-reabrir.
            if not controller.connected:
                app.state.kj_lab_enabled = False
                app.state.ki_contract_test_enabled = False
                app.state.ki_ingress = None
            if (barrier.phase == "legacy" and controller.connected
                    and controller.last_neutral_virtual):
                try:
                    await attach_verified_kf_bridge(app, controller, admin_token)
                except Exception as error:
                    app.state.exclusive_device_control_enabled = True
                    LOG.warning("[K-G] Enganche denegado: %s", type(error).__name__)
                else:
                    # K-L habilita el contrato del invitado solo desde la
                    # misma laptop: _ingress() tambien comprueba IP de origen.
                    if (controller.connected
                            and app.state.kf_wss_controller is controller
                            and app.state.kf_bridge.controller is controller
                            and barrier.phase == "exclusive"):
                        app.state.ki_ingress = GuestIngressLab(controller)
                        app.state.ki_expected_host = app.state.kj_expected_host
                        app.state.ki_contract_test_enabled = True
                        app.state.kj_lab_enabled = True
                        LOG.info("[K-L] Admision local habilitada; mismo KCController WSS")
                    else:
                        app.state.ki_ingress = None
                        app.state.ki_contract_test_enabled = False
                        app.state.kj_lab_enabled = False
            if barrier.phase == "blocked":
                LOG.warning("[K-G] Barrera bloqueada tras fallo; no se permite movimiento")
                return
            try:
                await asyncio.wait_for(stopping.wait(), timeout=0.1)
            except TimeoutError:
                continue

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI):
        config, secret = kc_module.old.load_config()
        admin_token = kc_module.old.ensure_token("admin")
        app.state.config = config
        app.state.key = secret
        app.state.admin_token = admin_token
        app.state.kg_lab_local_ip = config["ip"]
        app.state.kj_expected_host = f"{config['ip']}:8443"
        controller = kc_module.KCController(admin_token)
        app.state.control = controller
        app.state.kf_wss_controller = controller
        app.state.kf_bridge = None
        app.state.exclusive_device_control_enabled = True
        stopping = asyncio.Event()
        async with original_lifespan(app):
            watcher = asyncio.create_task(controller.run_supervision_watchdog(stopping))
            bootstrap = asyncio.create_task(attach_when_ready(
                app, controller, admin_token, stopping))
            try:
                yield
            finally:
                stopping.set()
                await asyncio.gather(watcher, bootstrap, return_exceptions=True)
                app.state.kf_bridge = None
                app.state.kj_lab_enabled = False
                app.state.ki_contract_test_enabled = False
                app.state.ki_ingress = None
                app.state.ki_expected_host = None
                app.state.exclusive_device_control_enabled = True
                await controller.close_on_fault()

    application.router.lifespan_context = combined_lifespan
    return application
