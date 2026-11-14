"""5.5-K-B: HTTP adapter for anonymous visitor approval, loopback lab ONLY.

DO NOT import in app.main, expose 8767 to LAN/Internet, or attach to motor/WSS.
This is not the production API or the official GitHub Pages application.
"""
from __future__ import annotations

import asyncio
from hmac import compare_digest
from ipaddress import ip_address
from time import monotonic
from typing import Callable, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, UUID4

from app.public_control.single_link_admission_lab import AdmissionDenied, SingleLinkAdmissionLab


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Approval(StrictBody):
    request_id: UUID4
    modo: Literal["supervised", "timed"] = "supervised"
    segundos: int | None = Field(default=None, strict=True, ge=1, le=300)


class Rejection(StrictBody):
    request_id: UUID4


def _loopback(value: str) -> bool:
    try:
        address = ip_address(value)
        address = getattr(address, "ipv4_mapped", None) or address
        return address.is_loopback
    except ValueError:
        return value == "localhost"


def create_portal_http_lab_app(admin_token: str, *, clock: Callable[[], float] = monotonic) -> FastAPI:
    """Single-process, local-only API with serialized state changes and no actuation."""
    if type(admin_token) is not str or len(admin_token) < 32:
        raise ValueError("Se requiere credencial administrativa de laboratorio >=32 caracteres.")
    gate = SingleLinkAdmissionLab(admin_token, clock=clock)
    lock = asyncio.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        client = request.client.host if request.client else ""
        host = request.url.hostname or ""
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        forwarded = ("forwarded", "x-forwarded-for", "x-real-ip", "via")
        fetch_site = request.headers.get("sec-fetch-site")
        # Do not enable public CORS, LAN bindings, or reverse proxies.
        if (not _loopback(client) or not _loopback(host) or request.url.port != 8767 or
                request.headers.getlist("host") != [request.url.netloc] or
                any(request.headers.get(h) for h in forwarded) or
                (origin is not None and origin != expected) or
                fetch_site not in (None, "same-origin", "none")):
            response = JSONResponse({"detail": "Laboratorio exclusivamente local"}, status_code=403)
        elif (request.headers.get("content-length") and
              (not request.headers["content-length"].isdecimal() or
               int(request.headers["content-length"]) > 1024)):
            response = JSONResponse({"detail": "Solicitud demasiado grande"}, status_code=413)
        elif request.method in ("POST", "PUT", "PATCH") and request.headers.get("content-type", "").split(";")[0].strip() not in ("", "application/json"):
            response = JSONResponse({"detail": "Se requiere JSON"}, status_code=415)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    def require_admin(header: str | None) -> None:
        if type(header) is not str or not compare_digest(header, admin_token):
            raise HTTPException(401, "Sesión administrativa requerida")

    def deny(_error: AdmissionDenied) -> None:
        raise HTTPException(409, "Solicitud caducada, ocupada o no autorizada") from None

    @app.post("/api/k/solicitud", status_code=201)
    async def visitor_arrives():
        async with lock:
            try:
                return {**gate.arrive(), "simulado": True, "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.get("/api/k/solicitud/estado")
    async def visitor_status(x_browser_session: str | None = Header(default=None)):
        if not x_browser_session:
            raise HTTPException(401, "Sesión de navegador requerida")
        async with lock:
            try:
                return {**gate.visitor_status(x_browser_session), "simulado": True}
            except AdmissionDenied:
                raise HTTPException(401, "Sesión de navegador inválida") from None

    @app.post("/api/k/admin/supervision")
    async def supervisor_heartbeat(x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                gate.supervisor_heartbeat(admin_token)
                return {"supervision": True, "vigencia_s": 15,
                        "simulado": True, "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.get("/api/k/admin/pendientes")
    async def pending(x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                return {"solicitudes": gate.pending(admin_token), "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.get("/api/k/admin/estado")
    async def administrator_status(x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                return {"etapa": "5.5-K-B", "solo_laboratorio": True, **gate.snapshot()}
            except AdmissionDenied as error:
                deny(error)

    @app.post("/api/k/admin/aprobar")
    async def approve(data: Approval, x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                gate.approve(admin_token, str(data.request_id), mode=data.modo,
                             turn_seconds=data.segundos)
                return {"aprobada": True, "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.post("/api/k/admin/rechazar")
    async def reject(data: Rejection, x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                gate.reject(admin_token, str(data.request_id))
                return {"rechazada": True, "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.post("/api/k/admin/revocar")
    async def revoke(x_lab_admin: str | None = Header(default=None)):
        require_admin(x_lab_admin)
        async with lock:
            try:
                gate.revoke(admin_token)
                return {"revocado": True, "parada_logica_pendiente": True,
                        "control_fisico": False}
            except AdmissionDenied as error:
                deny(error)

    @app.post("/api/k/accion")
    async def never_move():
        raise HTTPException(403, "Solo permisos; WSS y actuadores inhabilitados")

    @app.get("/api/k/ping")
    async def ping():
        return {"etapa": "5.5-K-B", "simulado": True, "control_fisico": False,
                "aws": False, "wss": False}

    app.state.portal_lab = gate
    return app
