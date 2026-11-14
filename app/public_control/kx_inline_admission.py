"""K-X: admisión HTTPS virtual integrada en el FastAPI existente.

Sólo rama experimental. Sin nuevo Python, puerto o Caddy. NUNCA despacha
motores y bloquea TODAS las escrituras legacy cuando está habilitada.
La aprobación es exclusivamente virtual: canDrive=False.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from re import compile as regex_compile
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.public_control.kr_ticket_ledger import KRTicketDenied, KRTicketLedger
from app.public_control.kq_restart_fence import KQRestartFence, FenceRejected
from app.public_control.repository import StoreUnavailable
from app.security.api_key import require_api_key

PAGES_ORIGIN = "https://yori7v7.github.io"
PUBLIC_HOST = "100-30-4-62.nip.io"
GUEST_PREFIX = "/publico/vehiculos/{id_vehiculo}/solicitudes"
ADMIN_PREFIX = "/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes"
_TOKEN = regex_compile(r"[A-Za-z0-9_-]{43}\Z")
_GUEST_PATH = regex_compile(r"^/publico/vehiculos/1/solicitudes(?:/|$)")
_ADMIN_PATH = regex_compile(r"^/admin/vehiculos/1/control-publico/solicitudes(?:/|$)")

router = APIRouter(include_in_schema=False)


class TimedVirtualApproval(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    modo: Literal["timed"]
    segundos: int = Field(strict=True, ge=30, le=120)


class KXWriteFence:
    """En modo K-X ninguna ruta de escritura legacy puede enviar eventos al ESP.

    STOP mecánico NO se acredita: la batería debe seguir desconectada.
    """
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in (
                "POST", "PUT", "PATCH", "DELETE"):
            state = scope.get("app").state if scope.get("app") else None
            if state is not None and getattr(state, "kx_enabled", False):
                path = scope.get("path", "")
                if not (_GUEST_PATH.match(path) or _ADMIN_PATH.match(path)):
                    await JSONResponse(
                        {"detail": "Escrituras legacy bloqueadas durante la admisión virtual."},
                        status_code=503, headers={"Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _context(request: Request, vehicle_id: int, *, admin: bool = False):
    state = request.app.state
    if not getattr(state, "kx_enabled", False) or vehicle_id != 1:
        raise HTTPException(503, "Admisión virtual no disponible")
    if (request.url.scheme != "https"
            or request.headers.getlist("host") != [PUBLIC_HOST]
            or request.headers.getlist("origin") != [PAGES_ORIGIN]
            or request.headers.getlist("cookie")
            or request.headers.getlist("authorization")
            or request.headers.getlist("proxy-authorization")
            or request.query_params):
        raise HTTPException(403, "Contexto público no permitido")
    if not admin and request.headers.getlist("x-api-key"):
        raise HTTPException(403, "El visitante no usa clave administrativa")
    if admin and request.headers.getlist("x-browser-session"):
        raise HTTPException(403, "Sesión incorrecta")
    ledger = getattr(state, "kx_ledger", None)
    if type(ledger) is not KRTicketLedger:
        raise HTTPException(503, "Registro de turnos no disponible")
    return ledger


def _virtual(**data):
    return {**data, "simulado": True, "control_fisico": False, "canDrive": False}


def _run(fn, *, denied=409):
    try:
        return fn()
    except KRTicketDenied:
        raise HTTPException(denied, "Solicitud de admisión no disponible") from None
    except (FenceRejected, StoreUnavailable):
        raise HTTPException(503, "Registro de admisión no verificable") from None


@router.post(GUEST_PREFIX, status_code=201)
async def visitor_request(id_vehiculo: int, request: Request, response: Response):
    ledger = _context(request, id_vehiculo)
    if (request.headers.getlist("x-browser-session")
            or request.headers.get("transfer-encoding") is not None
            or await request.body()):
        raise HTTPException(400, "La solicitud no acepta cuerpo ni sesión previa")
    keys = request.headers.getlist("idempotency-key")
    proposals = request.headers.getlist("x-browser-proposal")
    if (len(keys) != 1 or len(proposals) != 1
            or not _TOKEN.fullmatch(keys[0]) or not _TOKEN.fullmatch(proposals[0])
            or keys[0] == proposals[0]):
        raise HTTPException(428, "Identificadores de sesión inválidos")
    # El límite durable aplica incluso si Caddy no propaga IP: no se confía
    # en encabezados X-Forwarded-* que aporte el visitante.
    peer = request.client.host if request.client else "sin-identidad"
    row = _run(lambda: ledger.request_idempotent(peer, keys[0], proposals[0]),
               denied=429)
    response.status_code = 200 if row["idempotent_replay"] else 201
    return row


@router.get(GUEST_PREFIX + "/estado")
async def visitor_status(id_vehiculo: int, request: Request):
    ledger = _context(request, id_vehiculo)
    secrets = request.headers.getlist("x-browser-session")
    if len(secrets) != 1 or not _TOKEN.fullmatch(secrets[0]):
        raise HTTPException(401, "Sesión de navegador requerida")
    row = _run(lambda: ledger.status(secrets[0]), denied=401)
    return _virtual(
        estado="autorizado" if row["estado"] == "autorizado_virtual" else row["estado"],
        display_code=row["display_code"],
    )


def _admin(request: Request, vehicle_id: int):
    ledger = _context(request, vehicle_id, admin=True)
    proof = request.app.state.kx_admin_proof
    return ledger, proof


@router.get(ADMIN_PREFIX, dependencies=[Depends(require_api_key)])
async def admin_pending(id_vehiculo: int, request: Request):
    ledger, proof = _admin(request, id_vehiculo)
    row = _run(lambda: ledger.snapshot(proof), denied=503)
    return _virtual(solicitudes=row["solicitudes"],
                    turno_activo=row["turno_virtual_activo"])


@router.post(ADMIN_PREFIX + "/supervision", dependencies=[Depends(require_api_key)])
async def admin_supervision(id_vehiculo: int, request: Request):
    ledger, proof = _admin(request, id_vehiculo)
    _run(lambda: ledger.supervise(proof), denied=503)
    return _virtual(supervision=True, vigencia_s=15)


@router.post(ADMIN_PREFIX + "/{request_id}/aprobar",
             dependencies=[Depends(require_api_key)])
async def admin_approve(id_vehiculo: int, request_id: UUID,
                        data: TimedVirtualApproval, request: Request):
    ledger, proof = _admin(request, id_vehiculo)
    _run(lambda: ledger.approve_virtual(
        proof, str(request_id), seconds=data.segundos))
    return _virtual(aprobada=True)


@router.post(ADMIN_PREFIX + "/{request_id}/rechazar",
             dependencies=[Depends(require_api_key)])
async def admin_reject(id_vehiculo: int, request_id: UUID, request: Request):
    ledger, proof = _admin(request, id_vehiculo)
    _run(lambda: ledger.reject(proof, str(request_id)))
    return _virtual(rechazada=True)


@router.post(ADMIN_PREFIX + "/revocar", dependencies=[Depends(require_api_key)])
async def admin_revoke(id_vehiculo: int, request: Request):
    ledger, proof = _admin(request, id_vehiculo)
    _run(lambda: ledger.revoke(proof), denied=503)
    return _virtual(revocado=True, stop_fisico_confirmado=False)


@asynccontextmanager
async def admission_lifespan(app):
    """Un solo registro en el MISMO proceso FastAPI; cero servicios nuevos."""
    if not getattr(app.state, "kx_enabled", False):
        yield
        return
    settings = app.state.public_control_settings
    path = Path(settings.public_virtual_admission_sqlite_path)
    proof = settings.api_key.get_secret_value()
    fence = KQRestartFence(path)
    app.state.kx_ledger = None
    app.state.kx_admin_proof = None
    try:
        epoch = fence.start()
        ledger = KRTicketLedger(fence, epoch, proof)
        ledger.prepare()
        app.state.kx_admin_proof = proof
        app.state.kx_ledger = ledger
        yield
    finally:
        app.state.kx_ledger = None
        app.state.kx_admin_proof = None
        fence.close()
