"""WebSocket de diagnóstico exclusivo del dispositivo, SOLO loopback y sin despacho.

NO transmite órdenes, no modifica el almacén de turnos y no produce telemetría
física. La identidad del dispositivo exige un secreto que NO se incluye en el
frontend ni en este repositorio.
"""
from __future__ import annotations

import asyncio
import json
import logging
from ipaddress import ip_address
from urllib.parse import urlsplit
from secrets import token_hex

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.device_channel.authenticated_lab import (
    DeviceLabHandshake, DeviceTelemetryVerifier, LabDeviceProtocolError,
    decoded, NONCE_LEN,
)


router = APIRouter()
log = logging.getLogger(__name__)
FRAME_LIMIT = 512
HANDSHAKE_TIMEOUT = 5.0
RECEIVE_TIMEOUT = 15.0


class DeviceLabRegistry:
    """Máximo un canal activo por vehículo en un *proceso* de laboratorio."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._active: dict[int, str] = {}

    async def claim(self, vehicle_id: int) -> str | None:
        async with self._lock:
            if vehicle_id in self._active:
                return None
            lease = token_hex(16)
            self._active[vehicle_id] = lease
            return lease

    async def release(self, vehicle_id: int, lease: str) -> None:
        async with self._lock:
            if self._active.get(vehicle_id) == lease:
                self._active.pop(vehicle_id, None)

    def is_active(self, vehicle_id: int) -> bool:
        return vehicle_id in self._active


def _client_is_loopback(ws: WebSocket) -> bool:
    client = ws.client
    if client is None:
        return False
    try:
        address = ip_address(client.host)
        return (getattr(address, "ipv4_mapped", None) or address).is_loopback
    except ValueError:
        return False


def _local_host_only(ws: WebSocket) -> bool:
    """Rechazar proxy/Host no local. No es un control para producción."""
    if any(ws.headers.get(h) is not None for h in (
        "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip", "via",
    )):
        return False
    try:
        host = urlsplit("http://" + ws.headers.get("host", "")).hostname
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _no_duplicates(pairs):
    data = {}
    for k, v in pairs:
        if k in data:
            raise LabDeviceProtocolError("Clave JSON duplicada.")
        data[k] = v
    return data


async def _read_frame(ws: WebSocket, timeout: float) -> dict:
    raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
    if len(raw.encode("utf-8")) > FRAME_LIMIT:
        raise LabDeviceProtocolError("Marco demasiado grande.")
    try:
        result = json.loads(raw, object_pairs_hook=_no_duplicates)
    except (ValueError, json.JSONDecodeError):
        raise LabDeviceProtocolError("Marco JSON incorrecto.") from None
    if type(result) is not dict:
        raise LabDeviceProtocolError("Se requiere objeto JSON.")
    return result


@router.websocket("/ws/dispositivos-lab/{id_vehiculo}")
async def device_lab_socket(ws: WebSocket, id_vehiculo: str):
    """Recibe estado virtual autenticado. JAMÁS permite una orden física."""
    config = getattr(ws.app.state, "device_lab_settings", None)
    registry = getattr(ws.app.state, "device_lab_registry", None)
    if (config is None or not config.device_lab_enabled or registry is None
            or config.app_env != "development" or not _client_is_loopback(ws)
            or not _local_host_only(ws)
            or ws.headers.get("origin") is not None or ws.query_params):
        await ws.close(code=1008)
        return
    if (not id_vehiculo.isascii() or not id_vehiculo.isdecimal()
            or str(int(id_vehiculo)) != id_vehiculo
            or int(id_vehiculo) != config.device_lab_vehicle_id):
        await ws.close(code=1008)
        return

    vehicle = int(id_vehiculo)
    lease = await registry.claim(vehicle)
    if lease is None:
        await ws.close(code=1008)
        return
    try:
        # La configuración ya se validó antes de arrancar FastAPI.
        secret = decoded(config.device_lab_key.get_secret_value(), NONCE_LEN)
        handshake = DeviceLabHandshake(vehicle, secret)
        await ws.accept()
        await ws.send_json(handshake.challenge)
        proof = await _read_frame(ws, HANDSHAKE_TIMEOUT)
        session, confirmation = handshake.verify(proof)
        await ws.send_json(confirmation)
        verifier = DeviceTelemetryVerifier(session)
        while True:
            frame = await _read_frame(ws, RECEIVE_TIMEOUT)
            count = verifier.verify(frame)
            await ws.send_json(verifier.confirmation(count))
    except (LabDeviceProtocolError, TimeoutError):
        try:
            await ws.close(code=1008)
        except RuntimeError:
            pass
    except WebSocketDisconnect:
        pass
    except Exception:
        # Fallar cerrado sin reflejar la excepción ni la clave al cliente.
        log.error("Se cerró el canal de dispositivo de laboratorio.")
        try:
            await ws.close(code=1011)
        except RuntimeError:
            pass
    finally:
        await registry.release(vehicle, lease)
