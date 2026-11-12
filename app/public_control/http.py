"""Contratos HTTP y frontera de seguridad para el modo simulado."""

from datetime import datetime, timezone
from hmac import digest
from ipaddress import ip_address
import logging
import re
from secrets import token_bytes
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models.common import ErrorResponse, INT_MAX
from app.public_control.domain import TOKEN_PATTERN, PublicControlError
from app.public_control.models import (
    AcquireTurn, AdminStatus, AuditEntry, ControlErrorResponse, ControlOperation,
    CurrentTurn, EnableWindow, GrantedTurn, MoveRequest, PublicStatus, StopRequest,
    StopResult,
)
from app.security.api_key import SECURITY_RESPONSES, require_api_key


PAGES_ORIGIN = "https://yori7v7.github.io"
MAX_BODY_BYTES = 2048
ADMIN_PATH = re.compile(r"/admin/vehiculos/[^/]+/control-publico(?:/|$)")
GUEST_PATH = "/publico/vehiculos/"
BODY_METHODS = frozenset(("POST", "PUT", "DELETE"))
BEARER_VALUE = re.compile(rf"(?i:Bearer) ({TOKEN_PATTERN.pattern})")
CLIENT_SALT = token_bytes(32)
LOG = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(
    scheme_name="GuestControlBearer", bearerFormat="opaque",
    description="Token opaco de un turno de simulación.", auto_error=False,
)


def error_response(
    status: int, code: str, detail: str, retry_after: int | None = None,
) -> JSONResponse:
    body: dict[str, str | int] = {"codigo": code, "detalle": detail}
    headers = {}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if retry_after is not None:
        body["reintentar_en_seg"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(body, status_code=status, headers=headers)


class ControlRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return error_response(422, "entrada_invalida", "La solicitud no es válida.")
            except PublicControlError as error:
                return error_response(error.status, error.code, error.detail, error.retry_after)
            except HTTPException:
                # El contrato de la clave administrativa utiliza el formato existente.
                raise
            except Exception:
                LOG.error("Fallo interno del control público simulado.")
                return error_response(503, "servicio_no_disponible", "Control simulado no disponible.")

        return safe_handler


def is_loopback(scope: Scope) -> bool:
    client = scope.get("client")
    if client is None:
        return False
    try:
        address = ip_address(client[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback


class ScopedControlMiddleware:
    """Mantener CORS histórico y aplicar límites solo a las rutas nuevas."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._legacy = CORSMiddleware(
            app, allow_origins=[PAGES_ORIGIN], allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
        )
        self._admin = CORSMiddleware(
            self._bounded, allow_origins=[PAGES_ORIGIN], allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
        )
        self._guest = CORSMiddleware(
            self._bounded, allow_origins=[PAGES_ORIGIN], allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"], expose_headers=["Retry-After"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = scope["path"]
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path):]
        if path.startswith(GUEST_PATH):
            cors = self._guest
        elif ADMIN_PATH.match(path):
            cors = self._admin
        else:
            await self._legacy(scope, receive, send)
            return

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await cors(scope, receive, no_store)

    async def _bounded(self, scope: Scope, receive: Receive, send: Send) -> None:
        state = scope["app"].state
        if (getattr(state, "public_control_simulation", False)
                or getattr(state, "public_control", None) is not None) and not is_loopback(scope):
            await error_response(
                403, "solo_simulacion_local", "La simulación solo admite conexiones locales.",
            )(scope, receive, send)
            return
        if scope["method"] not in BODY_METHODS:
            await self._app(scope, receive, send)
            return

        sizes = Headers(scope=scope).getlist("content-length")
        if len(sizes) > 1 or (sizes and not sizes[0].isdecimal()):
            await error_response(422, "entrada_invalida", "La solicitud no es válida.")(
                scope, receive, send,
            )
            return
        if sizes and (len(sizes[0]) > 6 or int(sizes[0]) > MAX_BODY_BYTES):
            await self._too_large(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                await self._too_large(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        async def receive_bounded() -> Message:
            nonlocal body
            if body is None:
                return await receive()
            content = bytes(body)
            body = None
            return {"type": "http.request", "body": content, "more_body": False}

        await self._app(scope, receive_bounded, send)

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
        await error_response(413, "cuerpo_demasiado_grande", "El cuerpo supera el límite permitido.")(
            scope, receive, send,
        )


def reject_guest_credentials(request: Request) -> None:
    if request.headers.getlist("x-api-key") or request.headers.getlist("authorization"):
        raise PublicControlError(403, "credenciales_no_permitidas", "No se admiten credenciales en esta ruta.")


def reject_admin_bearer(request: Request) -> None:
    if request.headers.getlist("authorization"):
        raise HTTPException(status_code=403, detail="La credencial no está autorizada.")


def require_pages_origin(request: Request) -> None:
    if request.headers.getlist("origin") != [PAGES_ORIGIN]:
        raise PublicControlError(403, "origen_no_permitido", "El origen de la solicitud no está permitido.")


def require_guest_token(
    request: Request, _scheme: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> str:
    if request.headers.getlist("x-api-key"):
        raise PublicControlError(403, "credenciales_no_permitidas", "Esta ruta admite únicamente un token de turno.")
    values = request.headers.getlist("authorization")
    match = BEARER_VALUE.fullmatch(values[0]) if len(values) == 1 else None
    if match is None:
        raise PublicControlError(401, "token_invalido", "Se requiere un token de turno válido.")
    return match[1]


def control_service(request: Request):
    if getattr(request.app.state, "public_control_unavailable", False):
        raise PublicControlError(503, "servicio_no_disponible", "Control simulado no disponible.")
    service = getattr(request.app.state, "public_control", None)
    if service is None:
        raise PublicControlError(503, "control_deshabilitado", "Control simulado no disponible.")
    return service


def disabled_status(vehicle_id: int) -> dict[str, Any]:
    return {
        "id_vehiculo": vehicle_id, "habilitado": False, "estado": "cerrado",
        "vence_ventana_en": None, "hora_servidor": datetime.now(timezone.utc),
        "revision": 0, "simulado": False,
    }


def optional_service(request: Request):
    if getattr(request.app.state, "public_control_unavailable", False):
        return control_service(request)
    return getattr(request.app.state, "public_control", None)


VehiclePath = Annotated[int, Path(gt=0, le=INT_MAX)]
Service = Annotated[Any, Depends(control_service)]
GuestToken = Annotated[str, Depends(require_guest_token)]
SHARED_ERRORS = {
    404: {"model": ControlErrorResponse, "description": "Vehículo simulado desconocido."},
    409: {"model": ControlErrorResponse, "description": "Conflicto con el estado del vehículo o el turno."},
    413: {"model": ControlErrorResponse, "description": "Cuerpo de solicitud demasiado grande."},
    422: {"model": ControlErrorResponse, "description": "Solicitud no válida."},
}
GUEST_ERRORS = {
    **SHARED_ERRORS,
    401: {
        "model": ControlErrorResponse, "description": "Token de turno ausente o inválido.",
        "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
    },
    403: {"model": ControlErrorResponse, "description": "Origen o credenciales no permitidos."},
    429: {
        "model": ControlErrorResponse, "description": "Límite temporal de solicitudes.",
        "headers": {"Retry-After": {"schema": {"type": "string"}}},
    },
    503: {"model": ControlErrorResponse, "description": "Control simulado no disponible."},
}
ADMIN_ERRORS = {
    **SHARED_ERRORS, **SECURITY_RESPONSES,
    403: {"model": ErrorResponse | ControlErrorResponse, "description": "Credencial o acceso no autorizado."},
    503: {"model": ErrorResponse | ControlErrorResponse, "description": "Autorización o simulación no disponible."},
}
PUBLIC_ERRORS = {key: value for key, value in GUEST_ERRORS.items() if key != 401}

admin_router = APIRouter(
    prefix="/admin/vehiculos/{id_vehiculo}/control-publico",
    tags=["Administración de control simulado"], route_class=ControlRoute,
    dependencies=[Depends(require_api_key), Depends(reject_admin_bearer)],
    responses=ADMIN_ERRORS,
)
guest_router = APIRouter(
    prefix="/publico/vehiculos/{id_vehiculo}",
    tags=["Control público simulado"], route_class=ControlRoute,
)


@admin_router.get("", response_model=AdminStatus, summary="Consultar la ventana simulada")
def get_admin_status(id_vehiculo: VehiclePath, request: Request):
    service = optional_service(request)
    if service is not None:
        return service.admin_status(id_vehiculo)
    return dict(
        disabled_status(id_vehiculo), inicio_ventana_en=None, id_turno_auditoria=None,
        turno_vence_en=None, parada=None, motivo_bloqueo=None,
    )


@admin_router.get("/auditoria", response_model=list[AuditEntry], summary="Consultar auditoría simulada")
def get_audit(
    id_vehiculo: VehiclePath, request: Request,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
):
    service = optional_service(request)
    return service.audit(id_vehiculo, limit=limite) if service is not None else []


@admin_router.put("/ventana", response_model=AdminStatus, summary="Habilitar una ventana de veinte minutos")
def enable_window(id_vehiculo: VehiclePath, data: EnableWindow, service: Service):
    return service.enable(
        id_vehiculo, data.id_solicitud, duration_seconds=data.duracion_seg,
        supervision=data.supervision_confirmada,
    )


@admin_router.delete(
    "/ventana", response_model=AdminStatus, summary="Cerrar la ventana y resolver la parada",
    responses={202: {"model": StopResult, "description": "Parada simulada iniciada o pendiente."}},
)
def disable_window(id_vehiculo: VehiclePath, service: Service):
    status, result = service.disable(id_vehiculo)
    if status == 202:
        return JSONResponse(StopResult.model_validate(result).model_dump(mode="json"), status_code=status)
    return result


@admin_router.post("/revocacion", response_model=StopResult, status_code=202, summary="Revocar el turno")
def revoke_turn(id_vehiculo: VehiclePath, data: StopRequest, service: Service):
    return service.revoke(id_vehiculo, data.id_solicitud)


@guest_router.get(
    "/control", response_model=PublicStatus, summary="Consultar disponibilidad pública",
    dependencies=[Depends(reject_guest_credentials)], responses=PUBLIC_ERRORS,
)
def get_public_status(id_vehiculo: VehiclePath, request: Request):
    service = optional_service(request)
    return service.status(id_vehiculo) if service is not None else disabled_status(id_vehiculo)


@guest_router.post(
    "/sesion", response_model=GrantedTurn, status_code=201, summary="Tomar un turno exclusivo",
    dependencies=[Depends(require_pages_origin), Depends(reject_guest_credentials)], responses=PUBLIC_ERRORS,
)
def acquire_turn(id_vehiculo: VehiclePath, _data: AcquireTurn, request: Request, service: Service):
    host = request.client.host if request.client is not None else ""
    client_key = digest(CLIENT_SALT, host.encode(), "sha256").hex()
    return service.acquire(id_vehiculo, client_key=client_key)


@guest_router.get("/sesion", response_model=CurrentTurn, summary="Consultar mi turno", responses=GUEST_ERRORS)
def get_turn(id_vehiculo: VehiclePath, token: GuestToken, service: Service):
    return service.session(id_vehiculo, token)


@guest_router.delete(
    "/sesion", response_model=StopResult, status_code=202, summary="Ceder mi turno",
    dependencies=[Depends(require_pages_origin)], responses=GUEST_ERRORS,
)
def release_turn(id_vehiculo: VehiclePath, token: GuestToken, service: Service):
    return service.release(id_vehiculo, token)


@guest_router.post(
    "/sesion/acciones", response_model=ControlOperation, status_code=202,
    summary="Aceptar un movimiento simulado", dependencies=[Depends(require_pages_origin)],
    responses=GUEST_ERRORS,
)
def move(id_vehiculo: VehiclePath, data: MoveRequest, token: GuestToken, service: Service):
    return service.move(
        id_vehiculo, token, data.id_solicitud, data.secuencia, data.epoca_operacion,
        data.duracion_ms, data.accion.value,
    )


@guest_router.post(
    "/sesion/parada", response_model=StopResult, status_code=202,
    summary="Solicitar una parada simulada prioritaria", dependencies=[Depends(require_pages_origin)],
    responses=GUEST_ERRORS,
)
def stop(id_vehiculo: VehiclePath, data: StopRequest, token: GuestToken, service: Service):
    return service.stop(id_vehiculo, token, data.id_solicitud)


router = APIRouter()
router.include_router(admin_router)
router.include_router(guest_router)
