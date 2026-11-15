"""Prueba de integración WSS: una orden virtual seguida de STOP autenticados.

NO usa motores, RDS, turnos reales ni WSS de producción. Se ejecuta solo en
loopback y en desarrollo con credencial de laboratorio. Ningún ACK indica
inmovilidad física.
"""
from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceLabHandshake, LabDeviceProtocolError, decoded, NONCE_LEN,
)
from app.device_channel.command_wire import (
    AckFence, CommandWire, DeviceOrder, WireProtocolError,
)
from app.device_channel.ws_lab import (
    _client_is_loopback, _local_host_only, _read_frame,
    HANDSHAKE_TIMEOUT, DeviceLabRegistry,
)

router = APIRouter()
log = logging.getLogger(__name__)


def _allowed(ws: WebSocket, id_vehiculo: str) -> bool:
    settings = getattr(ws.app.state, "device_lab_settings", None)
    registry = getattr(ws.app.state, "device_lab_registry", None)
    if (settings is None or registry is None or not isinstance(registry, DeviceLabRegistry)
            or settings.app_env != "development" or not settings.device_lab_enabled
            or not _client_is_loopback(ws) or not _local_host_only(ws)
            or ws.headers.get("origin") is not None or bool(ws.query_params)):
        return False
    if (type(id_vehiculo) is not str or not id_vehiculo.isascii()
            or not id_vehiculo.isdecimal() or len(id_vehiculo) > 10
            or str(int(id_vehiculo)) != id_vehiculo):
        return False
    return int(id_vehiculo) == settings.device_lab_vehicle_id


async def _deliver(ws: WebSocket, fence: AckFence, order: DeviceOrder) -> None:
    """Orden completa y sus dos acuses con timeout independiente."""
    await ws.send_json(fence.queue(order))
    received = await _read_frame(ws, 1.5)
    if fence.consume(received) != "recibida":
        raise WireProtocolError("Falta acuse autenticado de recepción.")
    neutral = await _read_frame(ws, 1.5)
    if fence.consume(neutral) != "neutral_reportado_no_fisico":
        raise WireProtocolError("Falta acuse firmado de neutral virtual.")
    # La prueba no libera un turno físico.
    if fence.physical_stop_verified:
        raise RuntimeError("Un acuse virtual no acredita parada física.")


@router.websocket("/ws/dispositivos-lab/{id_vehiculo}/contrato")
async def diagnostic_command_socket(ws: WebSocket, id_vehiculo: str):
    """Integración WSS virtual de orden diagonal y DETENER. NUNCA actuadores."""
    if not _allowed(ws, id_vehiculo):
        await ws.close(code=1008)
        return

    vehicle = int(id_vehiculo)
    registry = ws.app.state.device_lab_registry
    lease = await registry.claim(vehicle)
    if lease is None:
        await ws.close(code=1008)
        return

    try:
        secret = decoded(ws.app.state.device_lab_settings.device_lab_key.get_secret_value(),
                         NONCE_LEN)
        handshake = DeviceLabHandshake(vehicle, secret)
        await ws.accept()
        await ws.send_json(handshake.challenge)
        reply = await _read_frame(ws, HANDSHAKE_TIMEOUT)
        session, confirmation = handshake.verify(reply)
        await ws.send_json(confirmation)

        wire = CommandWire(session)
        fence = AckFence(wire)
        now = int(time.time() * 1000)
        # Orden deliberadamente ficticia: el cliente de ensayo no tiene GPIO.
        drive = DeviceOrder(
            vehicle, session.session_id, str(uuid4()), 1, 1, 1,
            now, now + 750, 250, 9,
        )
        await _deliver(ws, fence, drive)

        now = int(time.time() * 1000)
        stop = DeviceOrder(
            vehicle, session.session_id, str(uuid4()), 1, 2, 2,
            now, now + 750, 0, 0,
        )
        await _deliver(ws, fence, stop)
        await ws.send_json({
            "tipo": "prueba_contrato_terminada", "simulado": True,
            "movimiento": 9, "detener": 0,
            "parada_fisica_verificada": False,
        })
        await ws.close(code=1000)
    except (LabDeviceProtocolError, WireProtocolError, TimeoutError):
        try:
            await ws.close(code=1008)
        except (RuntimeError, WebSocketDisconnect):
            pass
    except WebSocketDisconnect:
        pass
    except Exception:
        log.error("Fallo cerrado del diagnóstico WSS binario.")
        try:
            await ws.close(code=1011)
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        await registry.release(vehicle, lease)
