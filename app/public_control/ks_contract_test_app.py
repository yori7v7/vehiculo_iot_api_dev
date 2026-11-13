"""5.5-K-S: contrato HTTPS SOLO DE PRUEBAS para solicitudes K-R durables.

NO importar en app.main, K-G ni servidores públicos. No usa AWS, RDS, WSS
ni firmware. Enrutador aislado en memoria de TestClient, transporte HTTPS
simulado, origen del sitio oficial y cliente loopback. NO hay rutas de mando.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address
import os
from pathlib import Path
import re
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.public_control.kq_restart_fence import KQRestartFence, FenceRejected
from app.public_control.kr_ticket_ledger import KRTicketLedger, KRTicketDenied
from app.public_control.repository import StoreUnavailable


PAGES_ORIGIN = "https://yori7v7.github.io"
PATH_GUEST = "/publico/vehiculos/{id_vehiculo}/solicitudes"
PATH_ADMIN = "/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes"
_B64 = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
FORBIDDEN_PROXY_HEADERS = (
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip",
    "via", "x-original-url", "x-rewrite-url", "proxy-authorization",
)
_PRIVATE_ROOT = Path(__file__).resolve().parents[2]


class TimedVirtualApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    modo: Literal["timed"]
    segundos: int = Field(strict=True, ge=1, le=120)


def _virtual(**data) -> dict:
    return {**data, "simulado": True, "control_fisico": False, "canDrive": False}


def _guard(request: Request, vehicle: int, *, admin: bool) -> KRTicketLedger:
    state = request.app.state
    client = request.client.host if request.client is not None else ""
    try:
        addr = ip_address(client)
        addr = addr.ipv4_mapped or addr if addr.version == 6 else addr
        local = addr.is_loopback
    except ValueError:
        local = False

    if (not local or vehicle != 1
            or request.url.scheme != "https"
            or request.headers.getlist("host") != [state.ks_expected_host]
            or request.headers.getlist("origin") != [PAGES_ORIGIN]
            or request.headers.get("sec-fetch-site") not in (None, "cross-site")
            or any(request.headers.getlist(x) for x in FORBIDDEN_PROXY_HEADERS)
            or request.headers.getlist("cookie")
            or request.query_params):
        raise HTTPException(403, "Solicitud de laboratorio no autorizada")
    if getattr(state, "ks_lab_only", False) is not True:
        raise HTTPException(503, "Laboratorio aislado deshabilitado")
    ledger = getattr(state, "ks_ledger", None)
    if type(ledger) is not KRTicketLedger:
        raise HTTPException(503, "Registro virtual indisponible")

    if admin:
        if request.headers.getlist("authorization") or request.headers.getlist("x-browser-session"):
            raise HTTPException(403, "Credenciales de administrador incompatibles")
        header = request.headers.getlist("x-api-key")
        if len(header) != 1 or not header[0]:
            raise HTTPException(401, "Clave administrativa requerida")
        supplied = sha256(header[0].encode("utf-8")).digest()
        if not compare_digest(supplied, state.ks_admin_digest):
            raise HTTPException(403, "Credencial administrativa incorrecta")
    else:
        if request.headers.getlist("authorization") or request.headers.getlist("x-api-key"):
            raise HTTPException(403, "El visitante no usa credenciales administrativas")
    return ledger


def _safe(action, *, denial=409):
    try:
        return action()
    except KRTicketDenied:
        raise HTTPException(denial, "Solicitud virtual no disponible") from None
    except (StoreUnavailable, FenceRejected):
        raise HTTPException(503, "Almacén de laboratorio no verificable") from None


def create_ks_contract_test_app(
    private_db: Path | str, admin_proof: str, *,
    expected_host: str = "ks.localhost:9443",
    clock=None, **limits,
) -> FastAPI:
    """Construye ASGI exclusivamente para pruebas de TestClient.

    No ejecutarlo con uvicorn ni conectarlo a una EC2: aislamiento a nivel
    arquitectura y loopback no sustituyen cortafuegos ni auth pública real.
    """
    private_db = Path(private_db).resolve()
    if (os.environ.get("APP_ENV", "development").lower() != "development"
            or not private_db.is_absolute()
            or private_db.is_relative_to(_PRIVATE_ROOT)
            or type(admin_proof) is not str or len(admin_proof) < 32
            or expected_host != "ks.localhost:9443"):
        raise ValueError("K-S se limita a pruebas de desarrollo aisladas")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        fence = KQRestartFence(private_db)
        epoch = fence.start()
        ledger = KRTicketLedger(fence, epoch, admin_proof, clock=clock or __import__("time").time, **limits)
        try:
            ledger.prepare()
            app.state.ks_ledger = ledger
            yield
        finally:
            app.state.ks_ledger = None
            ledger.close()
            fence.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[PAGES_ORIGIN], allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Browser-Session", "Content-Type"],
        allow_credentials=False, max_age=0,
    )
    app.state.ks_lab_only = True
    app.state.ks_expected_host = expected_host
    app.state.ks_ledger = None
    app.state.ks_admin_digest = sha256(admin_proof.encode("utf-8")).digest()

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post(PATH_GUEST, status_code=201)
    async def request_ticket(id_vehiculo: int, request: Request):
        ledger = _guard(request, id_vehiculo, admin=False)
        if request.headers.getlist("x-browser-session"):
            raise HTTPException(403, "El ticket debe empezar sin sesión")
        if request.headers.get("transfer-encoding") is not None or await request.body():
            raise HTTPException(400, "No enviar cuerpo en una solicitud")
        # La IP viene del transporte ASGI, NUNCA de headers de proxy.
        client = request.client.host
        return _safe(lambda: ledger.request(client), denial=429)

    @app.get(PATH_GUEST + "/estado")
    async def visitor_status(id_vehiculo: int, request: Request):
        ledger = _guard(request, id_vehiculo, admin=False)
        secrets = request.headers.getlist("x-browser-session")
        if len(secrets) != 1 or not _B64.fullmatch(secrets[0]):
            raise HTTPException(401, "Sesión de visitante requerida")
        row = _safe(lambda: ledger.status(secrets[0]), denial=401)
        # El frontend actual usa "autorizado" para un permiso virtual;
        # JAMÁS se concede canDrive por esta respuesta.
        status = "autorizado" if row["estado"] == "autorizado_virtual" else row["estado"]
        return _virtual(estado=status, display_code=row["display_code"])

    @app.get(PATH_ADMIN)
    async def pending(id_vehiculo: int, request: Request):
        ledger = _guard(request, id_vehiculo, admin=True)
        row = _safe(lambda: ledger.snapshot(admin_proof), denial=503)
        return _virtual(solicitudes=row["solicitudes"],
                        turno_activo=row["turno_virtual_activo"])

    @app.post(PATH_ADMIN + "/supervision")
    async def supervise(id_vehiculo: int, request: Request):
        ledger = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.supervise(admin_proof), denial=503)
        return _virtual(supervision=True, vigencia_s=15)

    @app.post(PATH_ADMIN + "/{request_id}/aprobar")
    async def approve(id_vehiculo: int, request_id: UUID, data: TimedVirtualApproval, request: Request):
        ledger = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.approve_virtual(
            admin_proof, str(request_id), seconds=data.segundos))
        return _virtual(aprobada=True)

    @app.post(PATH_ADMIN + "/{request_id}/rechazar")
    async def reject(id_vehiculo: int, request_id: UUID, request: Request):
        ledger = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.reject(admin_proof, str(request_id)))
        return _virtual(rechazada=True)

    @app.post(PATH_ADMIN + "/revocar")
    async def revoke(id_vehiculo: int, request: Request):
        ledger = _guard(request, id_vehiculo, admin=True)
        _safe(lambda: ledger.revoke(admin_proof))
        # No fingir "STOP HMAC" al revocar: NO hay ESP.
        return _virtual(revocado=True, stop_fisico_confirmado=False)

    return app
