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
    ADMIN, GUEST, _guard, _safe, create_kv_virtual_app,
)
from app.public_control.kx_signed_wss import KXDiagnosticWSSHub, PATH, HOST
from app.public_control.repository import StoreUnavailable

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
HOTSPOT_PATH = "/ws/dispositivos-lab/1/contrato"
LOCAL_ACTION = "/__lab__/vehiculos/{id_vehiculo}/accion-virtual"


class VirtualAction(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    codigo: Literal[0, 1, 2, 4, 5, 6, 8, 9, 10]
    duracion_ms: int = Field(ge=0, le=500, strict=True)

    @model_validator(mode="after")
    def consistent_duration(self):
        if (self.codigo == 0 and self.duracion_ms != 0) or (
            self.codigo != 0 and not 100 <= self.duracion_ms <= 500
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

    async def execute(self, ledger, browser_secret: str, code: int, duration_ms: int):
        async with self.lock:
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


def create_kv_kx_virtual_lab_app(db_path, admin_proof: str, proxy_proof: str,
                                  device_key: bytes, *, clock=None,
                                  hotspot_host: str | None = None,
                                  hotspot_device_ip: str | None = None,
                                  **limits):
    """Offline-only factory; *not* an alternative production startup entrypoint."""
    if os.environ.get("KX_KV_VIRTUAL_BRIDGE_LAB") != "isolated_ci_only":
        raise ValueError("Puente virtual disponible solo en CI/laboratorio aislado")
    if type(device_key) is not bytes or len(device_key) != 32:
        raise ValueError("Clave HMAC de prueba de exactamente 32 bytes requerida")

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
    hub = KXDiagnosticWSSHub(device_key, expected_host=hotspot_host or HOST)
    authority = VirtualOnlyAuthority(hub)
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

    @app.post(LOCAL_ACTION, include_in_schema=False)
    async def virtual_action(id_vehiculo: int, data: VirtualAction, request: Request):
        ledger, _ = _guard(request, id_vehiculo, admin=False)
        keys = request.headers.getlist("x-browser-session")
        if (len(keys) != 1 or not _TOKEN.fullmatch(keys[0]) or
                request.headers.getlist("x-api-key")):
            raise HTTPException(401, "Sesión de invitado requerida")
        return await authority.execute(ledger, keys[0], data.codigo, data.duracion_ms)

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
