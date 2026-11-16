"""K-X: WSS de DIAGNÓSTICO conectado al mismo FastAPI y a los turnos K-R.

Cerrado por defecto. Puede habilitarse con configuración EXPLÍCITA y una
clave privada binaria de 32 bytes fuera de Git, o por inyección en pruebas.
NO hay GPIO ni liberación de motores. Reutiliza la autenticación 55-H y el
contrato CommandWire; los ACK acreditan solamente neutral VIRTUAL.
"""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceLabHandshake, LabDeviceProtocolError, check_key,
)
from app.device_channel.command_wire import (
    AckFence, CommandWire, DeviceOrder, WireProtocolError,
)

from app.public_control.control_evidence_55k import (
    can_dispatch_virtual_55k,
)
from app.public_control.control_permissions_55k import ADMIN, GUEST

router = APIRouter(include_in_schema=False)
PATH = "/ws/kx-diagnostico/1"
HOST = "100-30-4-62.nip.io"
MAX_FRAME_BYTES = 512


async def _receive(ws: WebSocket, *, timeout: float | None = None) -> dict:
    async def read():
        raw = await ws.receive_text()
        if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            raise WireProtocolError("Marco demasiado grande")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise WireProtocolError("Clave JSON duplicada")
                result[key] = value
            return result

        data = json.loads(raw, object_pairs_hook=unique)
        if type(data) is not dict:
            raise WireProtocolError("Marco JSON invalido")
        return data

    return await asyncio.wait_for(read(), timeout) if timeout else await read()


class KXDiagnosticWSSHub:
    """Un socket, un lock de despacho y dos ACK firmados por operación.

    Este objeto SOLO sirve con firmware 55-H GPIO INHIBIDO y simulador.
    No puede certificar parada física ni usarse como autoridad de motores.
    """

    def __init__(self, device_secret: bytes, *, expected_host: str = HOST):
        # Inyectable SOLO para laboratorio LAN con peer exacto en el router.
        # El host productivo por defecto permanece intacto.
        if type(expected_host) is not str or not expected_host:
            raise ValueError("Host de dispositivo invalido")
        self._expected_host = expected_host
        self._secret = check_key(device_secret)
        self._lock = asyncio.Lock()
        self._ws: WebSocket | None = None
        self._queue: asyncio.Queue | None = None
        self._fence: AckFence | None = None
        self._session = None
        self._ready = False
        self._blocked = True
        self._seq = 0
        self._epoch = 0

    @property
    def ready(self) -> bool:
        return self._ready and not self._blocked and self._ws is not None

    def interlock(self) -> None:
        """Revocar antes de esperar el lock: impedir órdenes nuevas."""
        self._blocked = True

    async def _drop(self, ws: WebSocket) -> None:
        if self._ws is ws:
            self._ready = False
            self._blocked = True
            self._ws = None
            self._session = None
            if self._fence is not None:
                self._fence.transport_lost()
            self._fence = None
            q = self._queue
            self._queue = None
            if q is not None:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
        try:
            await ws.close(code=1011)
        except (RuntimeError, WebSocketDisconnect):
            pass

    async def _send(self, code: int, duration_ms: int = 0) -> None:
        """Sólo con _lock tomado; la operación vence en <= 1 segundo."""
        if not self._ws or not self._fence or not self._queue or not self._session:
            raise WireProtocolError("Dispositivo no disponible")
        self._seq += 1
        self._epoch += 1
        # Margen validado para el reloj NTP del laboratorio 55-H.
        now = int(time.time() * 1000) - 150
        order = DeviceOrder(
            1, self._session.session_id, str(uuid4()), 1,
            self._epoch, self._seq, now, now + 1000,
            duration_ms if code else 0, code,
        )
        frame = self._fence.queue(order)
        await self._ws.send_json(frame)
        for expected in ("recibida", "neutral_reportado_no_fisico"):
            reply = await asyncio.wait_for(self._queue.get(), timeout=2.5)
            if reply is None or self._fence.consume(reply) != expected:
                raise WireProtocolError("ACK ausente o incompatible")

    async def execute_virtual(self, ledger, browser_secret: str,
                              code: int, duration_ms: int) -> bool:
        """Autorización + envío firmados bajo el lock del mismo proceso.

        El ledger aún puede revocarse concurrentemente: se revalida antes y
        después de cada tramo; esto NO es una garantía de STOP físico.
        """
        async with self._lock:
            if not self.ready:
                raise HTTPException(503, "Canal WSS diagnostico no autenticado")
            # Nunca usar un resultado autorizado almacenado en el navegador.
            try:
                ledger.verify_virtual_action(browser_secret)
            except Exception:
                raise HTTPException(403, "Turno virtual no vigente") from None
            if not can_dispatch_virtual_55k(
                ledger,
                server_role=GUEST,
                credential=browser_secret,
                action=code,
                authenticated_device=self.ready,
            ):
                raise HTTPException(403, "Invitado sin control vigente")
            if self._blocked:
                raise HTTPException(503, "Coordinador bloqueado")
            try:
                await self._send(code, 0 if code == 0 else duration_ms)
                if code != 0:
                    # STOP firmado incluso si el permiso caduca en vuelo.
                    await self._send(0)
            except (TimeoutError, RuntimeError, ValueError, WireProtocolError,
                    WebSocketDisconnect):
                if self._ws is not None:
                    await self._drop(self._ws)
                raise HTTPException(503, "WSS diagnostico sin acuses validos") from None
            try:
                ledger.verify_virtual_action(browser_secret)
            except Exception:
                raise HTTPException(409, "Turno revocado durante orden virtual") from None
            if not can_dispatch_virtual_55k(
                ledger,
                server_role=GUEST,
                credential=browser_secret,
                action=code,
                authenticated_device=self.ready,
            ):
                raise HTTPException(409, "Turno invalidado durante orden")
            if self._blocked:
                raise HTTPException(409, "Turno revocado durante orden virtual")
            return True

    async def execute_admin_virtual(
        self, ledger, admin_proof: str,
        code: int, duration_ms: int
    ) -> bool:
        """Control administrativo virtual, sin GPIO ni motores."""
        async with self._lock:
            if not self.ready:
                raise HTTPException(503, "WSS virtual no disponible")

            if not can_dispatch_virtual_55k(
                ledger,
                server_role=ADMIN,
                credential=admin_proof,
                action=code,
                authenticated_device=self.ready,
            ):
                raise HTTPException(403, "Administrador sin control exclusivo")

            if self._blocked:
                raise HTTPException(503, "Coordinador bloqueado")

            try:
                await self._send(code, 0 if code == 0 else duration_ms)
                if code != 0:
                    await self._send(0)
            except (
                TimeoutError, RuntimeError, ValueError,
                WireProtocolError, WebSocketDisconnect
            ):
                if self._ws is not None:
                    await self._drop(self._ws)
                raise HTTPException(
                    503, "WSS virtual sin acuses validos"
                ) from None

            if not can_dispatch_virtual_55k(
                ledger,
                server_role=ADMIN,
                credential=admin_proof,
                action=code,
                authenticated_device=self.ready,
            ):
                raise HTTPException(409, "Turno modificado durante orden")

            if self._blocked:
                raise HTTPException(409, "Canal virtual revocado")

            return True

    async def stop_virtual(self) -> bool:
        """Interlock primero; STOP virtual después, sin afirmar inmovilidad."""
        self.interlock()
        async with self._lock:
            if self._ws is None or not self._ready:
                return False
            try:
                await self._send(0)
                return True
            except (TimeoutError, RuntimeError, ValueError, WireProtocolError,
                    WebSocketDisconnect):
                if self._ws is not None:
                    await self._drop(self._ws)
                return False

    async def shutdown(self) -> None:
        """Cerrar el canal al detener FastAPI; ESP debe neutralizar localmente."""
        self.interlock()
        async with self._lock:
            if self._ws is not None:
                await self._drop(self._ws)

    async def serve(self, ws: WebSocket) -> None:
        if (ws.headers.get("host") != self._expected_host or ws.headers.get("origin") is not None
                or ws.query_params or ws.headers.get("authorization") is not None
                or not getattr(ws.app.state, "kx_enabled", False)):
            await ws.close(code=1008)
            return
        async with self._lock:
            if self._ws is not None:
                await ws.close(code=1008)
                return
            self._ws = ws  # Reservar antes del primer await de autenticación.
            self._ready = False
            self._blocked = True

        reader = None
        try:
            handshake = DeviceLabHandshake(1, self._secret)
            await ws.accept()
            await ws.send_json(handshake.challenge)
            proof = await _receive(ws, timeout=5.0)
            session, confirmation = handshake.verify(proof)
            await ws.send_json(confirmation)
            async with self._lock:
                if self._ws is not ws:
                    raise WireProtocolError("Conexión reemplazada")
                self._session = session
                self._queue = asyncio.Queue(maxsize=4)
                self._fence = AckFence(CommandWire(session))
                self._seq = 0
                self._epoch = 0

            async def reader_loop():
                try:
                    while True:
                        frame = await _receive(ws)
                        if self._queue is None:
                            break
                        await self._queue.put(frame)
                except (WebSocketDisconnect, RuntimeError, ValueError,
                        WireProtocolError, json.JSONDecodeError):
                    pass
                finally:
                    if self._queue is not None:
                        try:
                            self._queue.put_nowait(None)
                        except asyncio.QueueFull:
                            pass

            reader = asyncio.create_task(reader_loop())
            async with self._lock:
                await self._send(0)  # STOP inicial firmado: solo neutral virtual.
                self._blocked = False
                self._ready = True
            await reader
        except (TimeoutError, RuntimeError, ValueError, WireProtocolError,
                LabDeviceProtocolError, WebSocketDisconnect, json.JSONDecodeError):
            pass
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass
            async with self._lock:
                if self._ws is ws:
                    await self._drop(ws)


@router.websocket(PATH)
async def kx_wss_diagnostic(ws: WebSocket):
    hub = getattr(ws.app.state, "kx_diag_hub", None)
    if not isinstance(hub, KXDiagnosticWSSHub):
        await ws.close(code=1008)
        return
    await hub.serve(ws)
