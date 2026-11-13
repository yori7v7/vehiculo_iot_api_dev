"""K-F: instalar la puerta HTTP solo DESPUES del traspaso seguro.

Sin ruta de activacion publica. El controlador DEBE ser exactamente el mismo
objeto en memoria que recibe el WSS autenticado del ESP8266. Solo laboratorio.
"""
from __future__ import annotations

from fastapi import FastAPI
from app.public_control.exclusive_transition_lab import prepare_exclusive_for_lab
from app.public_control.kf_bridge import KFBridge


async def attach_verified_kf_bridge(app: FastAPI, controller, admin_token: str) -> None:
    """El callback valida neutro LOGICO firmado; no acredita parada mecanica."""
    settings = getattr(app.state, "public_control_settings", None)
    if (settings is None or settings.app_env != "development"
            or getattr(settings, "control_publico_simulation", False)
            or getattr(settings, "device_lab_enabled", False)
            or getattr(app.state, "kf_bridge", None) is not None
            or getattr(app.state, "kf_wss_controller", None) is not controller
            or not getattr(controller, "connected", False)):
        raise RuntimeError(
            "K-F requiere desarrollo local y la misma instancia WSS autenticada"
        )

    bridge = KFBridge(controller, admin_token)

    async def signed_stop_verified_by_transport() -> bool:
        async with controller.lock:
            if not controller.connected:
                return False
            # En K-C, dispatch solo retorna tras dos ACK HMAC validados.
            await controller.dispatch(0)
            return bool(controller.connected and controller.last_neutral_virtual)

    await prepare_exclusive_for_lab(
        app, signed_stop_ack=signed_stop_verified_by_transport, timeout_s=10,
    )
    app.state.kf_bridge = bridge
    app.state.exclusive_device_control_enabled = True
