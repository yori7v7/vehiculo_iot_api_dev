"""5.5-K-I — Contrato HTTPS de admisión desde una sola URL (NO productivo).

El router NO se habilita al registrarse. La autoridad debe ser EXACTAMENTE el
controlador WSS compartido con la API; no hay comandos, STOP ni aprobación aquí.
No usar el adaptador en memoria como arquitectura de producción.
"""
from __future__ import annotations

import re
from ipaddress import ip_address
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from app.public_control.single_link_admission_lab import AdmissionDenied
from app.public_control.kg_liveness import signed_transport_recent

PAGES_ORIGIN = "https://yori7v7.github.io"
VISITOR_SECRET = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
router = APIRouter(prefix="/publico/vehiculos/{id_vehiculo}/solicitudes", include_in_schema=False)


class GuestIngressLab:
    """Sin segundo estado: usa el gate y lock del controlador WSS K-C."""

    def __init__(self, controller: Any):
        if not all(hasattr(controller, name) for name in ("lock", "gate", "connected")):
            raise TypeError("Se requiere la autoridad WSS compartida.")
        self.controller = controller

    async def request(self, *, idempotency_key: str, browser_secret: str,
                      client_identity: str) -> dict:
        async with self.controller.lock:
            if not self.controller.connected:
                raise HTTPException(503, "Dispositivo desconectado")
            try:
                row = self.controller.gate.arrive_idempotent(
                    idempotency_key=idempotency_key,
                    browser_secret=browser_secret,
                    client_identity=client_identity,
                )
            except AdmissionDenied:
                raise HTTPException(409, "Solicitud no disponible o reintento invalido") from None
        return {**row, "simulado": True, "control_fisico": False, "canDrive": False}

    async def status(self, browser_secret: str) -> dict:
        async with self.controller.lock:
            if not self.controller.connected:
                raise HTTPException(503, "Dispositivo desconectado")
            try:
                row = self.controller.gate.visitor_status(browser_secret)
            except AdmissionDenied:
                raise HTTPException(401, "Sesión de navegador no válida") from None
        # Nunca devolver el bearer de movimiento emitido internamente.
        return {"estado": row["estado"], "display_code": row["display_code"],
                "simulado": True, "control_fisico": False, "canDrive": False}


def _request_context(request: Request) -> None:
    # K-I se prueba con HTTPS virtual. No usar el laboratorio LAN HTTP/WSS como
    # origen público ni confiar ciegamente en X-Forwarded-*.
    host = getattr(request.app.state, "ki_expected_host", None)
    if (type(host) is not str or not host or request.url.scheme != "https"
            or request.headers.getlist("host") != [host]
            or request.headers.getlist("origin") != [PAGES_ORIGIN]
            or request.headers.get("sec-fetch-site") not in (None, "cross-site")
            or any(request.headers.getlist(h) for h in
                   ("authorization", "x-api-key", "cookie", "forwarded",
                    "x-forwarded-for", "x-real-ip", "via"))
            or request.query_params):
        raise HTTPException(403, "Solicitud pública no autorizada")


def _ingress(request: Request, vehicle_id: int) -> GuestIngressLab:
    settings = getattr(request.app.state, "public_control_settings", None)
    # K-L: cuando K-G habilita el router, la admision solo proviene del
    # mismo PC administrador. Otros equipos LAN y el ESP quedan excluidos.
    if getattr(request.app.state, "kg_lab_mode", False) is True:
        raw_client = request.client.host if request.client else ""
        own_ip = getattr(request.app.state, "kg_lab_local_ip", None)
        try:
            address = ip_address(raw_client)
            address = getattr(address, "ipv4_mapped", None) or address
            local_client = address.is_loopback or (type(own_ip) is str and str(address) == own_ip)
        except ValueError:
            local_client = False
        if not local_client or request.headers.getlist("x-forwarded-host"):
            raise HTTPException(403, "Solo la laptop del laboratorio K-G")
    adapter = getattr(request.app.state, "ki_ingress", None)
    controller = getattr(request.app.state, "kf_wss_controller", None)
    barrier = getattr(request.app.state, "legacy_handover", None)
    if (settings is None or getattr(settings, "app_env", None) != "development"
            or getattr(request.app.state, "ki_contract_test_enabled", False) is not True
            or (getattr(request.app.state, "kg_lab_mode", False) is True
                and not signed_transport_recent(request.app.state))
            or getattr(request.app.state, "exclusive_device_control_enabled", False) is not True
            or adapter is None or type(adapter) is not GuestIngressLab
            or controller is None or adapter.controller is not controller
            or barrier is None or getattr(barrier, "phase", None) != "exclusive"
            or not controller.connected
            or vehicle_id != 1):
        raise HTTPException(503, "Admisión pública aún no disponible")
    return adapter


@router.post("", status_code=201)
async def request_access(id_vehiculo: int, request: Request, response: Response) -> dict:
    _request_context(request)
    ingress = _ingress(request, id_vehiculo)
    if (request.headers.get("content-length") not in (None, "0")
            or request.headers.get("transfer-encoding") is not None
            or await request.body()):
        raise HTTPException(400, "No enviar contenido")
    if request.headers.getlist("x-browser-session"):
        raise HTTPException(403, "No reutilizar una sesión existente")
    keys = request.headers.getlist("idempotency-key")
    proposals = request.headers.getlist("x-browser-proposal")
    if (len(keys) != 1 or len(proposals) != 1 or
            VISITOR_SECRET.fullmatch(keys[0]) is None or
            VISITOR_SECRET.fullmatch(proposals[0]) is None or
            keys[0] == proposals[0]):
        raise HTTPException(428, "Claves opacas de reintento obligatorias")
    identity = request.client.host if request.client else ""
    row = await ingress.request(idempotency_key=keys[0],
                                browser_secret=proposals[0],
                                client_identity=identity)
    response.status_code = 200 if row["idempotent_replay"] else 201
    return row


@router.get("/estado")
async def check_access(id_vehiculo: int, request: Request) -> dict:
    _request_context(request)
    ingress = _ingress(request, id_vehiculo)
    credentials = request.headers.getlist("x-browser-session")
    if len(credentials) != 1 or VISITOR_SECRET.fullmatch(credentials[0]) is None:
        raise HTTPException(401, "Sesión de navegador requerida")
    return await ingress.status(credentials[0])
