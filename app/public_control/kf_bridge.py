"""K-F: puerta HTTP *interna* que usa el MISMO controlador WSS K-C.

Inactiva por defecto; solo loopback y desarrollo. Sin despacho de motores,
Swagger publico, CORS externo ni nueva autoridad de turnos.
"""
from __future__ import annotations

from hmac import compare_digest
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from app.public_control.single_link_admission_lab import AdmissionDenied
from app.public_control.kg_liveness import signed_transport_recent


def _cache_control(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(
    prefix="/interno/55kf", include_in_schema=False,
    dependencies=[Depends(_cache_control)], tags=["Laboratorio K-F"],
)


class KFBridge:
    """Pasarela al mismo controlador K-C; no ejecuta movimientos."""
    def __init__(self, controller: Any, admin_token: str):
        if not isinstance(admin_token, str) or len(admin_token) < 32:
            raise ValueError("Token administrativo de laboratorio inválido")
        if not all(hasattr(controller, name) for name in
                   ("lock", "gate", "connected", "approve_ticket",
                    "supervisor_pulse", "revoke_all", "status")):
            raise TypeError("Se requiere el controlador K-C WSS compartido")
        self.controller = controller
        self.__admin_token = admin_token

    def authorize_admin(self, supplied: str | None) -> None:
        if not isinstance(supplied, str) or not compare_digest(
                self.__admin_token.encode(), supplied.encode()):
            raise HTTPException(401, "Sesión administrativa requerida")

    def gate_pending(self) -> list[dict]:
        return self.controller.gate.pending(self.__admin_token)

    def gate_reject(self, request_id: str) -> None:
        self.controller.gate.reject(self.__admin_token, request_id)


def _loopback(raw: str) -> bool:
    try:
        address = ip_address(raw)
        return (getattr(address, "ipv4_mapped", None) or address).is_loopback
    except ValueError:
        return raw == "localhost"


def _local(request: Request) -> None:
    """Solo loopback o IP del MISMO PC configurado por K-G; nunca otra laptop LAN."""
    address = request.client.host if request.client else ""
    hosts = request.headers.getlist("host")
    try:
        host = urlsplit("http://" + hosts[0]).hostname if len(hosts) == 1 else ""
    except ValueError:
        host = ""
    own_ip = getattr(request.app.state, "kg_lab_local_ip", None)
    same_pc = (isinstance(own_ip, str) and bool(own_ip) and
               not _loopback(own_ip) and address == own_ip and host == own_ip)
    loopback = _loopback(address) and bool(host) and _loopback(host)
    origin = request.headers.get("origin")
    own_origin = str(request.base_url).rstrip("/")
    if (not (loopback or same_pc)
            or any(request.headers.get(h) for h in
                   ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip", "via"))
            or (origin is not None and origin != own_origin)
            or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")
            or request.query_params):
        raise HTTPException(403, "Solo laboratorio local")


def _bridge(request: Request) -> KFBridge:
    _local(request)
    settings = getattr(request.app.state, "public_control_settings", None)
    bridge = getattr(request.app.state, "kf_bridge", None)
    handover = getattr(request.app.state, "legacy_handover", None)
    if (settings is None or getattr(settings, "app_env", None) != "development"
            or bridge is None or handover is None or handover.phase != "exclusive"
            or not bridge.controller.connected
            or (getattr(request.app.state, "kg_lab_mode", False) is True
                and not signed_transport_recent(request.app.state))):
        raise HTTPException(503, "Integración K-F cerrada o sin ESP autenticado")
    return bridge


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ApproveBody(StrictBody):
    request_id: UUID = Field(strict=False)
    modo: Literal["supervised", "timed"] = "supervised"
    segundos: int | None = Field(default=None, ge=1, le=30)


class RejectBody(StrictBody):
    request_id: UUID = Field(strict=False)


@router.get("/estado")
async def readiness(request: Request, x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    return {**bridge.controller.status(), "etapa": "5.5-K-F",
            "integracion": "mismo_controlador_wss", "control_fisico": False}


@router.post("/solicitud", status_code=201)
async def arrival(request: Request):
    bridge = _bridge(request)
    async with bridge.controller.lock:
        try:
            row = bridge.controller.gate.arrive()
        except AdmissionDenied:
            raise HTTPException(429, "Cola de solicitudes llena") from None
    return {**row, "simulado": True, "control_fisico": False}


@router.get("/solicitud/estado")
async def browser_status(request: Request, x_browser_session: str | None = Header(default=None)):
    bridge = _bridge(request)
    async with bridge.controller.lock:
        try:
            row = bridge.controller.gate.visitor_status(x_browser_session or "")
        except AdmissionDenied:
            raise HTTPException(401, "Sesión de navegador inválida") from None
    return {k: v for k, v in row.items() if k != "guest_token"} | {"simulado": True}


@router.post("/admin/supervision")
async def heartbeat(request: Request, x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    return await bridge.controller.supervisor_pulse()


@router.get("/admin/pendientes")
async def pending(request: Request, x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    async with bridge.controller.lock:
        return {"solicitudes": bridge.gate_pending(), "control_fisico": False}


@router.post("/admin/aprobar")
async def approve(request: Request, body: ApproveBody,
                  x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    if (body.modo == "timed" and body.segundos is None) or (
            body.modo == "supervised" and body.segundos is not None):
        raise HTTPException(422, "Duración incompatible con modo elegido")
    # Prevalidar ANTES de pedir STOP firmado. El controlador revalida bajo lock.
    if (not bridge.controller.gate.snapshot().get("supervisor_active") or
            str(body.request_id) not in {
                entry["request_id"] for entry in bridge.gate_pending()
            }):
        raise HTTPException(409, "Sin supervisión vigente o solicitud pendiente")
    return await bridge.controller.approve_ticket(
        str(body.request_id), mode=body.modo, seconds=body.segundos)


@router.post("/admin/rechazar")
async def reject(request: Request, body: RejectBody,
                 x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    async with bridge.controller.lock:
        try:
            bridge.gate_reject(str(body.request_id))
        except AdmissionDenied:
            raise HTTPException(409, "La solicitud ya no está pendiente") from None
    return {"rechazada": True, "control_fisico": False}


@router.post("/admin/detener")
async def stop(request: Request, x_kf_admin: str | None = Header(default=None)):
    bridge = _bridge(request)
    bridge.authorize_admin(x_kf_admin)
    return await bridge.controller.revoke_all()


@router.post("/accion")
async def no_motion(request: Request):
    _local(request)
    raise HTTPException(403, "K-F solo valida permisos; el movimiento remoto no está habilitado")
