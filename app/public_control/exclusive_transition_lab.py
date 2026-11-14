"""K-E: puente para el gestor DEMO existente; NO es endpoint HTTP.

El futuro despachador WSS confiable debe implementar signed_stop_ack.
No invocar mientras transporte y autoridad no estén integrados.
"""
from collections.abc import Awaitable, Callable

from fastapi import FastAPI

from app.public_control.legacy_handover import HandoverRefused, LegacyHandoverGate


async def prepare_exclusive_for_lab(
    app: FastAPI, *, signed_stop_ack: Callable[[], Awaitable[bool]], timeout_s: float = 10.0
) -> None:
    """Cerrar nuevas entradas legacy, drenar operaciones y recoger DEMO.

    Un ACK firmado representa neutro *logico*; no acredita parada mecanica.
    Esta funcion no dispone de ruta de activacion en produccion.
    """
    gate = getattr(app.state, "legacy_handover", None)
    manager = getattr(app.state, "demo_execution_manager", None)
    if not isinstance(gate, LegacyHandoverGate) or manager is None or not callable(getattr(manager, "close_all", None)):
        raise HandoverRefused("Coordinador o gestor DEMO no inicializado.")
    await gate.prepare_exclusive(
        close_demos=manager.close_all,
        signed_stop_ack=signed_stop_ack,
        timeout_s=timeout_s,
    )
