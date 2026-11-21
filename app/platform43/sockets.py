"""WSS de navegador con ticket de un uso y canal de dispositivo independiente."""
import asyncio
import logging
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.errors.database import DatabaseError
from app.websocket.events import InitialStateEvent
from app.websocket.manager import WebSocketManager
from .models import Id
from .operations import state
from .security import Actor, Database, authorized_unit, digest, missing, one, unit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plataforma", tags=["4.3 WebSocket"])
ORIGINAL_PROTOCOL = "q6-q7-v1"


@router.post("/vehiculos/{vehicle}/ticket", status_code=201)
def new_ticket(vehicle: Id, actor: Actor, db: Database, response: Response):
    ticket = token_urlsafe(32)
    with db.transaction() as connection, connection.cursor() as cursor:
        authorized_unit(cursor, actor.key, vehicle)
        cursor.execute("INSERT INTO iot_ticket(huella,sesion,vehiculo,vence) VALUES(%s,%s,%s,UTC_TIMESTAMP(6)+INTERVAL 20 SECOND)",
                       (digest(ticket), actor.key, vehicle))
    response.headers["Cache-Control"] = "no-store"
    return {"ticket": ticket}


def consume(db, token, vehicle):
    with db.transaction() as connection, connection.cursor() as cursor:
        key = digest(token)
        ticket = one(cursor, "SELECT sesion FROM iot_ticket WHERE huella=%s AND vehiculo=%s AND vence>UTC_TIMESTAMP(6) FOR UPDATE", (key, vehicle))
        if not ticket:
            logger.debug("Ticket WSS ausente, caducado o asociado a otra unidad.")
            raise missing()
        actor, row = authorized_unit(cursor, ticket["sesion"], vehicle)
        cursor.execute("DELETE FROM iot_ticket WHERE huella=%s", (key,))
        return actor, row["version"]


class Subscription:
    def __init__(self, socket, db, vehicle, actor, version):
        self.socket = socket
        self.db = db
        self.vehicle = vehicle
        self.actor = actor
        self.version = version

    async def accept(self):
        await self.socket.accept(subprotocol="iot43")

    async def close(self, code=1000):
        await self.socket.close(code)

    def check(self, *, initial=False):
        with self.db.transaction(read_only=True) as connection, connection.cursor() as cursor:
            actor, row = authorized_unit(cursor, self.actor.key, self.vehicle)
            if row["version"] != self.version:
                raise missing()
            if initial:
                return InitialStateEvent.from_state(self.vehicle, state(connection, self.vehicle, actor)).model_dump(mode="json")

    async def send_json(self, event):
        await run_in_threadpool(self.check)
        await self.socket.send_json(event)


async def maintain(socket, validate):
    while True:
        try:
            message = await asyncio.wait_for(socket.receive(), timeout=2)
            if message["type"] == "websocket.disconnect":
                return
            await socket.close(code=1008)
            return
        except TimeoutError:
            await run_in_threadpool(validate)


@router.websocket("/ws/vehiculos/{vehicle}")
async def browser(socket: WebSocket, vehicle: Id, db: Database):
    app = socket.app.state
    protocol = socket.scope.get("subprotocols", [])
    if (socket.headers.get("origin") not in app.platform_origins or len(protocol) != 2
            or protocol[0] != "iot43" or len(protocol[1]) != 43 or not protocol[1].isascii()):
        await socket.close(code=1008)
        return
    sub = None
    try:
        actor, version = await run_in_threadpool(consume, db, protocol[1], vehicle)
        sub = Subscription(socket, db, vehicle, actor, version)
        await app.websocket_manager.connect(vehicle, sub, lambda: run_in_threadpool(sub.check, initial=True))
        await maintain(socket, sub.check)
    except asyncio.CancelledError:
        pass
    except (HTTPException, DatabaseError, WebSocketDisconnect, RuntimeError) as error:
        logger.debug("Conexión WSS 4.3 cerrada (%s, estado %s, ticket consumido %s).",
                     type(error).__name__, getattr(error, "status_code", None), bool(sub))
        try:
            await socket.close(code=1008)
        except RuntimeError:
            pass
    finally:
        if sub:
            with CancelScope(shield=True):
                await app.websocket_manager.disconnect(vehicle, sub, close=False)


def verify_device(db, vehicle, key):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        row = unit(cursor, vehicle)
        if not (row["activo"] and row["modelo_activo"] and row["dispositivo"]
                and compare_digest(row["dispositivo"], key)):
            raise missing()


class PlatformEvents(WebSocketManager):
    """La telemetría de navegador y las órdenes a hardware usan canales distintos."""

    def __init__(self, *, dispatch, device_connections):
        super().__init__()
        self.dispatch = dispatch
        self.device_connections = device_connections
        self.devices = {}
        self.device_lock = asyncio.Lock()
        self.original_pending = set()

    def dispatch_status(self, vehicle):
        device = self.devices.get(vehicle)
        return {
            "estado": "inhibido" if not self.dispatch else "sin_dispositivo" if device is None else "disponible_sin_ack",
            "demo_original": bool(self.dispatch and device and device[2]),
            "demo_original_pendiente": vehicle in self.original_pending,
        }

    async def to_device(self, vehicle, event, should_send=None):
        if not self.dispatch:
            return "inhibido"
        kind, code = event.get("tipo_evento"), event.get("codigo")
        async with self.device_lock:
            device = self.devices.get(vehicle)
            if device is None:
                return "sin_dispositivo"
            socket, validate, original_capable = device
            if code == 64 and (kind != "movimiento" or not original_capable or vehicle in self.original_pending):
                return "inhibido"
            if vehicle in self.original_pending and (kind != "movimiento" or code not in (0, 128)):
                return "inhibido"
            try:
                await run_in_threadpool(validate)
                if should_send is not None and not should_send():
                    return "cancelado"
                if code == 64:
                    # Un fallo tras empezar a enviar no demuestra que Q6 no se activó.
                    self.original_pending.add(vehicle)
                safe_fields = ("tipo_evento", "id_evento", "id_vehiculo", "codigo", "duracion_ms", "pausa_ms")
                await asyncio.wait_for(socket.send_json({key: event[key] for key in safe_fields if key in event}), timeout=1)
            except (TimeoutError, HTTPException, DatabaseError, RuntimeError, OSError, WebSocketDisconnect):
                self.devices.pop(vehicle, None)
                try:
                    await asyncio.wait_for(socket.close(code=1011), timeout=1)
                except (TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
                    pass
                return "error_envio"
            if kind == "movimiento" and code == 128:
                self.original_pending.discard(vehicle)  # Solicitud despachada, sin confirmación mecánica.
            return "enviado_sin_ack"

    async def stop_device(self, vehicle):
        return await self.to_device(vehicle, {
            "tipo_evento": "demo_cancelada", "id_vehiculo": vehicle, "id_evento": uuid4().hex,
        })

    async def broadcast(self, vehicle_id, event, *, should_send=None):
        await self.to_device(vehicle_id, event, should_send)
        await super().broadcast(vehicle_id, event, should_send=should_send)

    async def close_all(self):
        async with self.device_lock:
            devices = tuple(self.devices.values())
            self.devices.clear()
        await self._close_clients(tuple(device[0] for device in devices), code=1001)
        await super().close_all()


@router.websocket("/ws/dispositivos/{vehicle}")
async def device(socket: WebSocket, vehicle: Id, db: Database):
    app = socket.app.state
    credentials = socket.headers.getlist("authorization")
    if (not app.websocket_manager.device_connections or socket.headers.get("origin") or len(credentials) != 1
            or not credentials[0].startswith("Bearer ") or len(credentials[0]) != 50):
        await socket.close(code=1008)
        return
    key = digest(credentials[0][7:])

    def validate():
        verify_device(db, vehicle, key)

    events = app.websocket_manager
    accepted = False
    try:
        await run_in_threadpool(validate)
        original_capable = socket.headers.getlist("x-iot-demo") == [ORIGINAL_PROTOCOL]
        async with events.device_lock:
            if vehicle in events.devices:
                await socket.close(code=1008)
                return
            await socket.accept()
            accepted = True
            events.devices[vehicle] = (socket, validate, original_capable)
        await maintain(socket, validate)
    except (HTTPException, DatabaseError, WebSocketDisconnect, RuntimeError) as error:
        logger.debug("Conexión WSS 4.3 cerrada (%s).", type(error).__name__)
        try:
            await socket.close(code=1008)
        except RuntimeError:
            pass
    finally:
        if accepted:
            async with events.device_lock:
                current = events.devices.get(vehicle)
                if current and current[0] is socket:
                    events.devices.pop(vehicle)
