"""5.5-K-G: FastAPI principal + K-C WSS en un UNICO ASGI, SOLO laboratorio.

El modulo no importa servidor_55kc en la API normal y no habilita motores.
Requiere firmware 55-H con GPIO diagnosticamente inhibido.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from time import monotonic

from fastapi import FastAPI
from starlette.routing import WebSocketRoute

from app.public_control.kf_attach import attach_verified_kf_bridge
from app.public_control.ki_ingress import GuestIngressLab
from app.public_control.kg_liveness import (
    acknowledge_signed_stop, close_lab_access, signed_transport_recent,
)

LOG = logging.getLogger(__name__)
WSS_PATH = "/ws/dispositivos-lab/1/contrato"

# Cada comprobación demanda dos ACK HMAC nuevos del ESP. Ninguna operación
# en estos timers puede actuar físicamente en el firmware diagnóstico.
KG_PROBE_INTERVAL_S = 2.0
KG_PROBE_TIMEOUT_S = 2.5


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
    application.state.kg_transport_fenced = False
    application.state.kg_last_signed_stop_at = None
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
            if app.state.kg_transport_fenced:
                return
            barrier = app.state.legacy_handover
            # Una perdida WSS cierra ambas puertas; no auto-reabrir.
            if not controller.connected:
                app.state.kj_lab_enabled = False
                app.state.ki_contract_test_enabled = False
                app.state.ki_ingress = None
                if barrier.phase == "exclusive":
                    close_lab_access(app.state)
                    try:
                        controller.gate.device_lost()
                    except Exception:
                        pass
                    return
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
                            and barrier.phase == "exclusive"
                            and app.state.kg_transport_fenced is False):
                        # attach_verified_kf_bridge verificó STOP con ACK HMAC.
                        acknowledge_signed_stop(app.state)
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
                close_lab_access(app.state)
                LOG.warning("[K-G] Barrera bloqueada tras fallo; no se permite movimiento")
                return
            try:
                await asyncio.wait_for(stopping.wait(), timeout=0.1)
            except TimeoutError:
                continue

    async def monitor_authenticated_wss(app: FastAPI, controller, stopping) -> None:
        """Probar VIDA del ESP con STOP 0 + dos ACK HMAC, no solo TCP abierto.

        Si un USB se desconecta sin FIN/RST inmediato, controller.connected
        puede continuar True. Un envío STOP firmado debe fallar por timeout;
        las rutas se cierran *antes* de intentar reparar el socket.
        """
        success_count = 0
        while not stopping.is_set() and not app.state.kg_transport_fenced:
            if app.state.legacy_handover.phase == "exclusive":
                probe_started = monotonic()
                ack_before = getattr(app.state, "kg_last_signed_stop_at", None)
                try:
                    async with asyncio.timeout(KG_PROBE_TIMEOUT_S):
                        async with controller.lock:
                            if not controller.connected:
                                raise ConnectionError("ESP sin canal WSS")
                            # Nunca reutilizar un neutro confirmado ANTES
                            # de este desafío autenticado.
                            controller.last_neutral_virtual = False
                            await controller.dispatch(0)
                            if not controller.connected or controller.last_neutral_virtual is not True:
                                raise ConnectionError("Sin acuse STOP HMAC nuevo")
                    acknowledge_signed_stop(app.state)
                    success_count += 1
                    if success_count == 1 or success_count % 10 == 0:
                        LOG.warning("[K-O] STOP HMAC fresco confirmado; sondeos=%d; duracion_ms=%d",
                                    success_count, int((monotonic() - probe_started) * 1000))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Fallo irreversible de esta sesión, aunque el socket
                    # siga reportando connected=True por TCP obsoleto.
                    close_lab_access(app.state)
                    try:
                        controller.gate.device_lost()
                    except Exception:
                        pass
                    age = (monotonic() - ack_before) if type(ack_before) is float else None
                    LOG.error(
                        "[K-O] WSS sin STOP HMAC vigente: bloqueado (%s); "
                        "sondeos_ok=%d duracion_ms=%d ultimo_ack_edad_s=%s "
                        "conectado=%s neutral_virtual=%s",
                        type(error).__name__, success_count,
                        int((monotonic() - probe_started) * 1000),
                        "sin_dato" if age is None else round(age, 2),
                        bool(getattr(controller, "connected", False)),
                        bool(getattr(controller, "last_neutral_virtual", False)),
                    )
                    try:
                        await asyncio.wait_for(controller.close_on_fault(), timeout=2.0)
                    except Exception:
                        LOG.error("[K-O] El cierre del canal no pudo confirmarse")
                    return
            try:
                await asyncio.wait_for(stopping.wait(), timeout=KG_PROBE_INTERVAL_S)
            except TimeoutError:
                pass

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
            signed_probe = asyncio.create_task(monitor_authenticated_wss(
                app, controller, stopping))
            try:
                yield
            finally:
                stopping.set()
                await asyncio.gather(watcher, bootstrap, signed_probe, return_exceptions=True)
                close_lab_access(app.state)
                app.state.ki_expected_host = None
                app.state.exclusive_device_control_enabled = True
                await controller.close_on_fault()

    application.router.lifespan_context = combined_lifespan
    return application
