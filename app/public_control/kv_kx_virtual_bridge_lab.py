"""K-V + K-X in a single *virtual-only*, loopback laboratory ASGI app.

Nothing in the deployed K-V factory, firmware, Caddy, or legacy API is changed.
This module has no server runner or physical dispatcher. Never deploy it to AWS.
"""
from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from ipaddress import ip_address, ip_network
from typing import Literal

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.public_control.kq_restart_fence import FenceRejected
from app.public_control.kr_ticket_ledger import KRTicketDenied
from app.public_control.kv_virtual_staging import (
    _guard, _safe, create_kv_virtual_app,
)
from app.public_control.kx_signed_wss import KXDiagnosticWSSHub, PATH, HOST
from app.public_control.repository import StoreUnavailable
from app.public_control.control_evidence_55k import (
    can_dispatch_virtual_55k,
)
from app.public_control.control_permissions_55k import ADMIN, GUEST
from app.public_control.demo_programada_55k import (
    PasoDemo55K, validar_plan,
)
from app.public_control.demo_coordinator_55k import DemoCoordinator55K

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
HOTSPOT_PATH = "/ws/dispositivos-lab/1/contrato"
LOCAL_ACTION = "/__lab__/vehiculos/{id_vehiculo}/accion-virtual"
LOCAL_ADMIN_ACTION = "/__lab__/vehiculos/{id_vehiculo}/accion-admin-virtual"


class VirtualAction(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    codigo: Literal[0, 1, 2, 4, 5, 6, 8, 9, 10, 16, 32, 128]
    duracion_ms: int = Field(ge=0, le=500, strict=True)

    @model_validator(mode="after")
    def consistent_duration(self):
        if (
            (self.codigo == 0 and self.duracion_ms != 0)
            or (
                self.codigo in (16, 32, 128)
                and not 100 <= self.duracion_ms <= 300
            )
            or (
                self.codigo not in (0, 16, 32, 128)
                and not 100 <= self.duracion_ms <= 500
            )
        ):
            raise ValueError("Duración incompatible con orden virtual")
        return self


class VirtualOnlyAuthority:
    """Serializes K-V admin mutations with virtual WSS commands.

    The admin revoke request preempts the hub *before* taking this lock.
    Even in-flight commands fail closed on the hub's post-command check;
    this is emphatically not a claim about mechanical STOP.
    """

    def __init__(self, hub: KXDiagnosticWSSHub):
        self.hub = hub
        self.lock = asyncio.Lock()
        self.demo_busy = False

    async def execute(self, ledger, browser_secret: str, code: int, duration_ms: int):
        async with self.lock:
            if self.demo_busy:
                raise HTTPException(409, "DEMO virtual en ejecucion")
            try:
                ledger.verify_virtual_action(browser_secret)
            except KRTicketDenied:
                raise HTTPException(403, "Turno virtual no vigente") from None
            except (FenceRejected, StoreUnavailable):
                raise HTTPException(503, "Autoridad durable no verificable") from None
            if not self.hub.ready:
                raise HTTPException(503, "WSS virtual no disponible")
            await self.hub.execute_virtual(ledger, browser_secret, code, duration_ms)
            try:
                ledger.verify_virtual_action(browser_secret)
            except KRTicketDenied:
                raise HTTPException(409, "Turno revocado durante orden") from None
            except (FenceRejected, StoreUnavailable):
                raise HTTPException(503, "Autoridad durable no verificable") from None
            if not self.hub.ready:
                raise HTTPException(409, "Canal virtual invalidado")
            return {
                "aceptada": True, "codigo": code, "duracion_ms": duration_ms,
                "despacho_wss": True, "neutral_virtual_reportado": True,
                "stop_fisico_confirmado": False, "motor": False,
                "simulado": True, "control_fisico": False, "canDrive": False,
            }


    async def execute_admin(
        self, ledger, admin_proof: str,
        code: int, duration_ms: int
    ):
        async with self.lock:
            if self.demo_busy:
                raise HTTPException(409, "DEMO virtual en ejecucion")
            if not self.hub.ready:
                raise HTTPException(503, "WSS virtual no disponible")

            if not can_dispatch_virtual_55k(
                ledger,
                server_role=ADMIN,
                credential=admin_proof,
                action=code,
                authenticated_device=self.hub.ready,
            ):
                raise HTTPException(403, "Turno administrativo no disponible")

            await self.hub.execute_admin_virtual(
                ledger, admin_proof, code, duration_ms
            )

            if not can_dispatch_virtual_55k(
                ledger,
                server_role=ADMIN,
                credential=admin_proof,
                action=code,
                authenticated_device=self.hub.ready,
            ):
                raise HTTPException(409, "Turno cambio durante orden")

            if not self.hub.ready:
                raise HTTPException(409, "Canal virtual invalidado")

            return {
                "aceptada": True,
                "codigo": code,
                "duracion_ms": duration_ms,
                "despacho_wss": True,
                "neutral_virtual_reportado": True,
                "stop_fisico_confirmado": False,
                "motor": False,
                "simulado": True,
                "control_fisico": False,
                "canDrive": False,
            }


def create_kv_kx_virtual_lab_app(db_path, admin_proof: str, proxy_proof: str,
                                  device_key: bytes, *, clock=None,
                                  hotspot_host: str | None = None,
                                  hotspot_device_ip: str | None = None,
                                  demo_plan: tuple[PasoDemo55K, ...] | None = None,
                                  demo_cycles: int = 1,
                                  **limits):
    """Offline-only factory; *not* an alternative production startup entrypoint."""
    mode = os.environ.get("KX_KV_VIRTUAL_BRIDGE_LAB")
    if mode == "isolated_lab_local":
        # En pruebas reales es OBLIGATORIO peer exacto en interfaz hotspot.
        # El arranque de red solo podrá hacerse con el wrapper WSS-only.
        if hotspot_host is None or hotspot_device_ip is None:
            raise ValueError("NO-GO: laboratorio real exige host y peer cerrados")
    elif mode != "isolated_ci_only":
        raise ValueError("Puente virtual disponible solo en CI/laboratorio aislado")
    if type(device_key) is not bytes or len(device_key) != 32:
        raise ValueError("Clave HMAC de prueba de exactamente 32 bytes requerida")
    if demo_plan is not None:
        if mode != "isolated_ci_only":
            raise ValueError("Plan virtual solo permitido en CI aislado")
        validar_plan(demo_plan, demo_cycles)
    elif demo_cycles != 1:
        raise ValueError("Ciclos sin plan no permitidos")

    # Host y peer LAN se enlazan entre sí: no habilitar modo LAN abierto
    # ni exponerlo en una interfaz pública.
    if (hotspot_host is None) != (hotspot_device_ip is None):
        raise ValueError("NO-GO: host y peer de hotspot deben definirse juntos")
    peer_required = None
    if hotspot_host is not None:
        try:
            ip_literal, port_literal = hotspot_host.rsplit(":", 1)
            host_ip = ip_address(ip_literal)
            peer_required = ip_address(hotspot_device_ip)
            valid = (port_literal == "8443" and host_ip.version == 4 and
                     peer_required.version == 4 and host_ip.is_private and
                     peer_required.is_private and not host_ip.is_loopback and
                     not peer_required.is_loopback and
                     peer_required in ip_network(f"{host_ip}/24", strict=False) and
                     host_ip != peer_required)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("NO-GO: destino privado hotspot 55-I invalido")
    app = create_kv_virtual_app(db_path, admin_proof, proxy_proof,
                                clock=clock, **limits)
    hub = KXDiagnosticWSSHub(
        device_key,
        expected_host=hotspot_host or HOST,
        # Solo el simulador CI admite auxiliares.
        # El laboratorio LAN con ESP real permanece cerrado.
        allow_auxiliary=(mode == "isolated_ci_only"),
    )
    authority = VirtualOnlyAuthority(hub)
    demo = DemoCoordinator55K(authority, demo_plan, demo_cycles)
    app.state.kv_demo_coordinator = demo
    app.state.kx_enabled = True
    app.state.kx_diag_hub = hub
    app.state.kx_kv_lab_only = True

    # Close the diagnostic transport *before* closing the persistent ledger.
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lab_lifespan(lab_app):
        async with original_lifespan(lab_app):
            try:
                yield
            finally:
                demo.request_cancel()
                await demo.close()
                hub.interlock()
                await hub.shutdown()

    app.router.lifespan_context = lab_lifespan

    # K-V's existing endpoints remain unmodified. A single ASGI coordinator
    # now locks all admin writes against the experimental guest action route.
    @app.middleware("http")
    async def serialize_admin_mutations(request: Request, call_next):
        if request.method != "POST" or not request.url.path.startswith(
            "/admin/vehiculos/1/control-publico/solicitudes"
        ):
            return await call_next(request)

        is_revoke = request.url.path == "/admin/vehiculos/1/control-publico/solicitudes/revocar"
        if is_revoke:
            # Only an already-authenticated administrator can preempt WSS.
            try:
                _guard(request, 1, admin=True)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            demo.request_cancel()
            hub.interlock()  # Priority: block new sends before awaiting lock.

        async with authority.lock:
            response = await call_next(request)
            if is_revoke and response.status_code == 200:
                # A virtual signed STOP, never a physical STOP assertion.
                try:
                    await hub.stop_virtual()
                finally:
                    await hub.shutdown()  # Require fresh authentication later.
            return response

    async def stop_demo_virtual(role: str, credential: str):
        """Interlock y STOP firmado; no confirma parada fisica."""
        if not demo.active:
            raise HTTPException(409, "No existe DEMO activa")

        if role == GUEST and not demo.owns_active(role, credential):
            raise HTTPException(403, "No es titular de la DEMO")

        # Bloquear envios nuevos ANTES de esperar cualquier lock.
        demo.request_cancel()
        hub.interlock()

        # Esperar el cierre cooperativo del tramo pendiente.
        await demo.close()

        # STOP adicional firmado, aunque el permiso ya no exista.
        if not await hub.stop_virtual():
            raise HTTPException(503, "STOP virtual no confirmado")

        return {
            "aceptada": True,
            "codigo": 0,
            "duracion_ms": 0,
            "demo_cancelada": True,
            "neutral_virtual_reportado": True,
            "stop_fisico_confirmado": False,
            "motor": False,
            "simulado": True,
            "control_fisico": False,
            "canDrive": False,
        }

    @app.post(LOCAL_ACTION, include_in_schema=False)
    async def virtual_action(id_vehiculo: int, data: VirtualAction, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=False)
        keys = request.headers.getlist("x-browser-session")
        if (len(keys) != 1 or not _TOKEN.fullmatch(keys[0]) or
                request.headers.getlist("x-api-key")):
            raise HTTPException(401, "Sesión de invitado requerida")
        if demo.active:
            if data.codigo == 0:
                return await stop_demo_virtual(GUEST, keys[0])
            raise HTTPException(409, "DEMO virtual en ejecucion")
        return await authority.execute(ledger, keys[0], data.codigo, data.duracion_ms)

    @app.post(LOCAL_ADMIN_ACTION, include_in_schema=False)
    async def admin_virtual_action(
        id_vehiculo: int,
        data: VirtualAction,
        request: Request,
    ):
        # La credencial se verifica en el servidor.
        # El navegador no proporciona el rol.
        ledger, _ = _guard(request, id_vehiculo, admin=True)
        credentials = request.headers.getlist("x-api-key")
        if len(credentials) != 1:
            raise HTTPException(401, "Credencial requerida")

        if demo.active:
            if data.codigo == 0:
                return await stop_demo_virtual(
                    ADMIN, credentials[0]
                )
            raise HTTPException(409, "DEMO virtual en ejecucion")
        return await authority.execute_admin(
            ledger, credentials[0], data.codigo, data.duracion_ms
        )


    DEMO_URL = "/__lab__/vehiculos/{id_vehiculo}/demo-programada"

    def demo_actor(request, id_vehiculo, admin):
        ledger, _ = _guard(request, id_vehiculo, admin=admin)
        if admin:
            keys = request.headers.getlist("x-api-key")
            if len(keys) != 1:
                raise HTTPException(401, "Clave requerida")
            return ledger, ADMIN, keys[0]

        keys = request.headers.getlist("x-browser-session")
        if len(keys) != 1 or not _TOKEN.fullmatch(keys[0]):
            raise HTTPException(401, "Sesion de invitado requerida")
        return ledger, GUEST, keys[0]

    @app.post(DEMO_URL + "/iniciar", status_code=202, include_in_schema=False)
    async def start_guest_demo(id_vehiculo: int, request: Request):
        ledger, role, proof = demo_actor(request, id_vehiculo, False)
        if await request.body():
            raise HTTPException(400, "DEMO sin cuerpo JSON")
        return await demo.start(ledger, role, proof)

    @app.post(DEMO_URL + "/admin/iniciar", status_code=202, include_in_schema=False)
    async def start_admin_demo(id_vehiculo: int, request: Request):
        ledger, role, proof = demo_actor(request, id_vehiculo, True)
        if await request.body():
            raise HTTPException(400, "DEMO sin cuerpo JSON")
        return await demo.start(ledger, role, proof)

    @app.post(DEMO_URL + "/cancelar", include_in_schema=False)
    async def cancel_guest_demo(id_vehiculo: int, request: Request):
        _, role, proof = demo_actor(request, id_vehiculo, False)
        if await request.body():
            raise HTTPException(400, "Cancelacion sin cuerpo")
        return await demo.cancel(role, proof)

    @app.post(DEMO_URL + "/admin/cancelar", include_in_schema=False)
    async def cancel_admin_demo(id_vehiculo: int, request: Request):
        _, role, proof = demo_actor(request, id_vehiculo, True)
        if await request.body():
            raise HTTPException(400, "Cancelacion sin cuerpo")
        return await demo.cancel(role, proof)

    @app.get(DEMO_URL + "/estado", include_in_schema=False)
    async def guest_demo_status(id_vehiculo: int, request: Request):
        _, role, proof = demo_actor(request, id_vehiculo, False)
        return demo.status(role, proof)

    @app.get(DEMO_URL + "/admin/estado", include_in_schema=False)
    async def admin_demo_status(id_vehiculo: int, request: Request):
        _, role, proof = demo_actor(request, id_vehiculo, True)
        return demo.status(role, proof)

    @app.get(
        "/__lab__/vehiculos/{id_vehiculo}/monitoreo-demo",
        include_in_schema=False,
    )
    async def monitoring_demo(id_vehiculo: int, request: Request):
        # Solo perimetro del laboratorio. Sin login ni
        # divulgacion de tickets o tokens de usuario.
        _guard(request, id_vehiculo, admin=False)

        if request.headers.getlist("x-browser-session"):
            raise HTTPException(
                403, "Monitoreo no recibe sesiones privadas"
            )

        return demo.monitoring_snapshot()

    @app.websocket(HOTSPOT_PATH if hotspot_host is not None else PATH)
    async def lab_device_ws(ws: WebSocket):
        # Host exacto verificado por el Hub; peer exacto en modo hotspot.
        # Default K-V/K-X mantiene condición loopback histórica.
        try:
            peer = ip_address(ws.client.host if ws.client else "")
            if peer.version == 6 and peer.ipv4_mapped:
                peer = peer.ipv4_mapped
        except ValueError:
            await ws.close(code=1008)
            return
        if ((peer_required is None and not peer.is_loopback) or
                (peer_required is not None and peer != peer_required)):
            await ws.close(code=1008)
            return
        await hub.serve(ws)  # Includes HMAC challenge and signed initial STOP.

    return app
