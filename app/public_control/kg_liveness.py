"""K-O: vigencia del acuse HMAC en el ASGI de laboratorio K-G.

No prueba neutro mecánico. Se usa exclusivamente con GPIO inhibidos y
despacho legacy cerrado. El ACK lo valida el transporte K-C (dispatch(0)).
"""
from __future__ import annotations

from math import isfinite
from time import monotonic
from typing import Any

# Debe ser menor que los 15 s de la prueba de desconexión manual.
ACK_LEASE_SECONDS = 8.0


def signed_transport_recent(state: Any) -> bool:
    """Permitir solo una autoridad vigente y NO bloqueada permanentemente."""
    if getattr(state, "kg_lab_mode", False) is not True:
        return False
    if getattr(state, "kg_transport_fenced", True) is not False:
        return False
    last = getattr(state, "kg_last_signed_stop_at", None)
    if type(last) is not float or not isfinite(last):
        return False
    now = monotonic()
    return last <= now < last + ACK_LEASE_SECONDS


def acknowledge_signed_stop(state: Any) -> None:
    """Solo llamar después de dispatch(0) con dos ACK HMAC validados."""
    if getattr(state, "kg_transport_fenced", True):
        raise RuntimeError("Una barrera bloqueada no puede reabrirse")
    state.kg_last_signed_stop_at = float(monotonic())


def close_lab_access(state: Any) -> None:
    """Cerrar todas las entradas HTTP sin aguardar tareas de transporte."""
    state.kg_transport_fenced = True
    state.kg_last_signed_stop_at = None
    state.kj_lab_enabled = False
    state.ki_contract_test_enabled = False
    state.ki_ingress = None
    state.kf_bridge = None
