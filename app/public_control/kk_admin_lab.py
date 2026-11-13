"""5.5-K-K: panel admin HTTPS sobre el mismo controlador K-C (LAB ONLY).

NO se activa en AWS ni en app.main. Todas las respuestas son VIRTUALES.
El navegador del profesor no posee estas rutas. Los cambios de turno
pertenecen a KCController y nunca se despachan motores por este router.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.public_control.http import PAGES_ORIGIN, reject_admin_bearer
from app.public_control.kf_bridge import KFBridge, _local
from app.public_control.single_link_admission_lab import AdmissionDenied
from app.security.api_key import require_api_key


router = APIRouter(
    prefix="/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes",
    include_in_schema=False,
    dependencies=[Depends(require_api_key), Depends(reject_admin_bearer)],
)


class ApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    modo: Literal["supervised", "timed"] = "supervised"
    segundos: int | None = Field(default=None, strict=True, ge=30, le=300)


def _bridge(request: Request, vehicle_id: int) -> KFBridge:
    """No permitir HTTP LAN ajeno, proxies ni uso sin handover verificado."""
    # El navegador real Pages usa Origin externo; la IP de transporte DEBE
    # seguir siendo la de la propia laptop en laboratorio.
    _local(request)
    settings = getattr(request.app.state, "public_control_settings", None)
    state = request.app.state
    bridge = getattr(state, "kf_bridge", None)
    handover = getattr(state, "legacy_handover", None)
    host = getattr(state, "kj_expected_host", None)

    if (request.url.scheme != "https"
            or type(host) is not str or request.headers.getlist("host") != [host]
            or request.headers.getlist("origin") != [PAGES_ORIGIN]
            or request.headers.getlist("cookie")
            or request.headers.getlist("x-browser-session")
            or request.query_params):
        raise HTTPException(403, "Acceso administrativo no autorizado")

    if (settings is None or getattr(settings, "app_env", None) != "development"
            or getattr(state, "kj_lab_enabled", False) is not True
            or getattr(state, "kg_lab_mode", False) is not True
            or vehicle_id != 1
            or type(bridge) is not KFBridge
            or getattr(state, "kf_wss_controller", None) is not bridge.controller
            or handover is None or handover.phase != "exclusive"
            or getattr(state, "exclusive_device_control_enabled", False) is not True
            or not bridge.controller.connected):
        raise HTTPException(503, "Autorizaciones administrativas no disponibles")
    return bridge


def _virtual(**values) -> dict:
    return {**values, "simulado": True, "control_fisico": False}


@router.get("")
async def pending(id_vehiculo: int, request: Request):
    bridge = _bridge(request, id_vehiculo)
    async with bridge.controller.lock:
        try:
            rows = bridge.gate_pending()
            active = bridge.controller.gate.snapshot()["guest_active"]
        except (AdmissionDenied, KeyError):
            raise HTTPException(503, "Estado de turnos no verificable") from None
    return _virtual(solicitudes=rows, turno_activo=bool(active))


@router.post("/supervision")
async def heartbeat(id_vehiculo: int, request: Request):
    bridge = _bridge(request, id_vehiculo)
    # KCController internamente verifica su propio token de supervisor.
    result = await bridge.controller.supervisor_pulse()
    if (result.get("supervision") is not True or
            result.get("vigencia_s") != 15 or result.get("control_fisico") is not False):
        raise HTTPException(503, "Supervisión no confirmada")
    return _virtual(supervision=True, vigencia_s=15)


@router.post("/{request_id}/aprobar")
async def approve(id_vehiculo: int, request_id: UUID, data: ApprovalPayload, request: Request):
    bridge = _bridge(request, id_vehiculo)
    if ((data.modo == "timed" and data.segundos is None) or
            (data.modo == "supervised" and data.segundos is not None)):
        raise HTTPException(422, "Duración incompatible con la modalidad")
    async with bridge.controller.lock:
        try:
            supervisor = bridge.controller.gate.snapshot().get("supervisor_active") is True
            pending_ids = {ticket["request_id"] for ticket in bridge.gate_pending()}
        except AdmissionDenied:
            raise HTTPException(503, "No se pudo verificar la supervisión") from None
        if not supervisor or str(request_id) not in pending_ids:
            raise HTTPException(409, "Solicitud no vigente o sin supervisor")
    # No mantener el lock externo: KCController.approve_ticket vuelve a
    # validarlo dentro de su propia transacción y verifica STOP firmado.
    result = await bridge.controller.approve_ticket(
        str(request_id), mode=data.modo, seconds=data.segundos
    )
    if result.get("aprobada") is not True or result.get("control_fisico") is not False:
        raise HTTPException(503, "Aprobación no confirmada")
    return _virtual(aprobada=True)


@router.post("/{request_id}/rechazar")
async def reject(id_vehiculo: int, request_id: UUID, request: Request):
    bridge = _bridge(request, id_vehiculo)
    async with bridge.controller.lock:
        try:
            bridge.gate_reject(str(request_id))
        except AdmissionDenied:
            raise HTTPException(409, "Solicitud inexistente o ya resuelta") from None
    return _virtual(rechazada=True)


@router.post("/revocar")
async def revoke(id_vehiculo: int, request: Request):
    bridge = _bridge(request, id_vehiculo)
    # Revocar es del único controlador; NO se toma su lock aquí.
    # Una confirmación lógica NO equivale a parada mecánica.
    result = await bridge.controller.revoke_all()
    if (result.get("detener") is not True or
            result.get("neutral_virtual") is not True or
            result.get("parada_fisica_verificada") is not False):
        raise HTTPException(503, "Revocación o STOP virtual no confirmado")
    return _virtual(revocado=True)
