"""5.5-K-V — puerta de admision PUBLICA VIRTUAL para futuro staging.

NO cableada a app.main, Caddy, EC2 o K-G. NO ejecutar en Internet sin
auditoria de proxy/firewall. No importa controlador K-C, RDS ni firmware.
Un administrador aprueba SOLO un ticket de observacion: canDrive=False.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address
from pathlib import Path
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.public_control.kq_restart_fence import FenceRejected, KQRestartFence
from app.public_control.kr_ticket_ledger import KRTicketDenied, KRTicketLedger
from app.public_control.repository import StoreUnavailable

PAGES_ORIGIN = "https://yori7v7.github.io"
STAGING_HOST = "100-30-4-62.nip.io"
GUEST = "/publico/vehiculos/{id_vehiculo}/solicitudes"
ADMIN = "/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes"
_KEY = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class KVirtualApproval(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    modo: Literal["timed"]
    segundos: int = Field(ge=1, le=120, strict=True)


def _answer(**data) -> dict:
    return {**data, "simulado": True, "control_fisico": False,
            "canDrive": False}


def _constant_equal(supplied, expected_digest: bytes) -> bool:
    if type(supplied) is not str or len(supplied) > 512:
        return False
    return compare_digest(sha256(supplied.encode("utf-8")).digest(),
                          expected_digest)


def _guard(request: Request, vehicle: int, *, admin: bool):
    state = request.app.state
    headers = request.headers
    host = request.client.host if request.client else ""
    try:
        peer = ip_address(host)
        if peer.version == 6 and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        client_header = headers.getlist("x-admission-client-ip")
        client = ip_address(client_header[0]) if len(client_header) == 1 else None
        if client and client.version == 6 and client.ipv4_mapped:
            client = client.ipv4_mapped
    except ValueError:
        raise HTTPException(403, "Perimetro no verificado") from None
    # Header de cliente inyectado/sobrescrito por el Caddy local. No confiar
    # en X-Forwarded-For/Host/Proto enviados por los visitantes.
    if (not peer.is_loopback or client is None or not client.is_global
            or vehicle != 1 or
            headers.getlist("host") != [STAGING_HOST] or
            headers.getlist("origin") != [PAGES_ORIGIN] or
            headers.getlist("x-admission-scheme") != ["https"] or
            len(headers.getlist("x-admission-proxy-token")) != 1 or
            not _constant_equal(headers["x-admission-proxy-token"],
                                state.kv_proxy_digest) or
            any(headers.getlist(name) for name in (
                "forwarded", "x-forwarded-for", "x-forwarded-host",
                "x-forwarded-proto", "x-real-ip", "cookie",
                "authorization", "proxy-authorization"
            )) or request.query_params):
        raise HTTPException(403, "Perimetro no verificado")
    if (getattr(state, "kv_virtual_only", False) is not True or
            type(getattr(state, "kv_ledger", None)) is not KRTicketLedger):
        raise HTTPException(503, "Admisión virtual indisponible")
    if admin:
        if headers.getlist("x-browser-session"):
            raise HTTPException(403, "Tipo de sesión incorrecto")
        tokens = headers.getlist("x-api-key")
        if len(tokens) != 1 or not tokens[0]:
            raise HTTPException(401, "Clave de administrador requerida")
        if not _constant_equal(tokens[0], state.kv_admin_digest):
            raise HTTPException(403, "Credencial no válida")
    else:
        if headers.getlist("x-api-key"):
            raise HTTPException(403, "El invitado no usa clave administrativa")
    return state.kv_ledger, str(client)


def _safe(fn, *, denial=409):
    try:
        return fn()
    except KRTicketDenied:
        raise HTTPException(denial, "Solicitud virtual no disponible") from None
    except (FenceRejected, StoreUnavailable):
        raise HTTPException(503, "Estado durable no verificable") from None


def create_kv_virtual_app(db_path, admin_proof, proxy_proof, *, clock=None, **limits):
    """Construye un STAGING virtual, NO un servidor de control físico.

    Dos secretos distintos, modo staging explícito, archivo local privado,
    frente HTTPS Caddy de confianza y único proceso en host único.
    """
    path = Path(db_path).resolve()
    if (os.getenv("APP_ENV") != "staging" or
            os.getenv("ADMISSION_VIRTUAL_ONLY") != "enabled" or
            not path.is_absolute() or path.is_relative_to(_REPO_ROOT) or
            type(admin_proof) is not str or len(admin_proof) < 32 or
            type(proxy_proof) is not str or len(proxy_proof) < 32 or
            admin_proof == proxy_proof):
        raise ValueError("K-V: configuración de staging privado obligatoria")

    @asynccontextmanager
    async def lifecycle(app: FastAPI):
        fence = KQRestartFence(path)
        epoch = fence.start()
        ledger = KRTicketLedger(fence, epoch, admin_proof,
                                clock=clock or __import__("time").time, **limits)
        try:
            ledger.prepare()
            app.state.kv_ledger = ledger
            yield
        finally:
            app.state.kv_ledger = None
            ledger.close()
            fence.close()

    app = FastAPI(lifespan=lifecycle, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware, allow_origins=[PAGES_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Browser-Session",
                       "X-Browser-Proposal", "Idempotency-Key", "Content-Type"],
        allow_credentials=False, max_age=0,
    )
    app.state.kv_ledger = None
    app.state.kv_virtual_only = True
    app.state.kv_admin_digest = sha256(admin_proof.encode()).digest()
    app.state.kv_proxy_digest = sha256(proxy_proof.encode()).digest()

    @app.middleware("http")
    async def prevent_cache(request: Request, next_handler):
        response = await next_handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post(GUEST, status_code=201)
    async def request_ticket(id_vehiculo: int, request: Request,
                             response: Response):
        ledger, identity = _guard(request, id_vehiculo, admin=False)
        if (request.headers.getlist("x-browser-session") or
                request.headers.get("transfer-encoding") is not None or
                await request.body()):
            raise HTTPException(400, "Solicitud no admite sesión/cuerpo")
        keys = request.headers.getlist("idempotency-key")
        proposals = request.headers.getlist("x-browser-proposal")
        if len(keys) != 1 or len(proposals) != 1 or not _KEY.fullmatch(keys[0]) or not _KEY.fullmatch(proposals[0]) or keys[0] == proposals[0]:
            raise HTTPException(428, "Claves opacas de reintento obligatorias")
        try:
            ticket = ledger.request_idempotent(identity, keys[0], proposals[0])
        except KRTicketDenied as error:
            status = 429 if "Limite de solicitudes" in str(error) else 409
            raise HTTPException(status, "Solicitud no disponible") from None
        except (StoreUnavailable, FenceRejected):
            raise HTTPException(503, "Estado durable no verificable") from None
        response.status_code = 200 if ticket["idempotent_replay"] else 201
        return ticket

    @app.get(GUEST + "/estado")
    async def guest_status(id_vehiculo: int, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=False)
        secrets = request.headers.getlist("x-browser-session")
        if len(secrets) != 1 or not _KEY.fullmatch(secrets[0]):
            raise HTTPException(401, "Sesión opaca requerida")
        row = _safe(lambda: ledger.status(secrets[0]), denial=401)
        state = ("autorizado" if row["estado"] == "autorizado_virtual"
                 else row["estado"])
        return _answer(estado=state, display_code=row["display_code"])

    @app.get(ADMIN)
    async def pending(id_vehiculo: int, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        row = _safe(lambda: ledger.snapshot(admin_proof), denial=503)
        return _answer(solicitudes=row["solicitudes"],
                       turno_activo=row["turno_virtual_activo"])

    @app.post(ADMIN + "/supervision")
    async def supervise(id_vehiculo: int, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.supervise(admin_proof), denial=503)
        return _answer(supervision=True, vigencia_s=15)

    @app.post(ADMIN + "/{request_id}/aprobar")
    async def approve(id_vehiculo: int, request_id: UUID,
                      data: KVirtualApproval, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.approve_virtual(
            admin_proof, str(request_id), seconds=data.segundos))
        return _answer(aprobada=True)

    @app.post(ADMIN + "/{request_id}/rechazar")
    async def reject(id_vehiculo: int, request_id: UUID, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.reject(admin_proof, str(request_id)))
        return _answer(rechazada=True)

    @app.post(ADMIN + "/revocar")
    async def revoke(id_vehiculo: int, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.revoke(admin_proof))
        return _answer(revocado=True, stop_fisico_confirmado=False)

    return app
