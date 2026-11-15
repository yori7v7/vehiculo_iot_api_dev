"""Contrato binario firmado del dispositivo, aislado de transporte y hardware.

NO permite operaciones físicas: autentica tramas solamente. Antes de instalar
un dispositivo real faltan despacho, firmware, pruebas y aprobación explícita.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
from hashlib import sha256
import hmac
import re
import struct
from typing import Protocol
from uuid import UUID

VERSION = 1
ORDER_CONTEXT = b"vehiculo-iot|device-order-v1|"
ACK_CONTEXT = b"vehiculo-iot|device-order-ack-v1|"
ORDER = struct.Struct(">BI16s16sIIIQQHB")
ACK = struct.Struct(">BI16s16sIIIQBB")
DIRECTIONS = frozenset((1, 2, 4, 5, 6, 8, 9, 10))
MAX_U32 = 2**32 - 1
MAX_U64 = 2**64 - 1
MAX_PACKET_TTL_MS = 1000
PHASE_RECEIVED = 1
PHASE_NEUTRAL = 2
PHASE_REJECTED = 3
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class WireProtocolError(ValueError):
    """Marco no firmado, inválido, revocado, caducado o fuera de contrato."""


class SessionLike(Protocol):
    vehicle_id: int
    session_id: str
    command_key: bytes
    telemetry_key: bytes


def _u32(value: object, *, positive: bool = True) -> bool:
    return type(value) is int and (0 < value <= MAX_U32 if positive else 0 <= value <= MAX_U32)


def _u64(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_U64


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(raw: object, length: int) -> bytes:
    if type(raw) is not str or len(raw) != (length * 8 + 5) // 6:
        raise WireProtocolError("Campo de base64 inválido.")
    try:
        value = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        raise WireProtocolError("Campo de base64 inválido.") from None
    if len(value) != length or _encode(value) != raw:
        raise WireProtocolError("Campo de base64 inválido.")
    return value


def _uuid(value: str) -> bytes:
    if type(value) is not str:
        raise WireProtocolError("Operación inválida.")
    try:
        identifier = UUID(value)
    except (ValueError, AttributeError):
        raise WireProtocolError("Operación inválida.") from None
    if str(identifier) != value or identifier.version != 4:
        raise WireProtocolError("Se requiere un identificador UUID v4.")
    return identifier.bytes


def _session(session: SessionLike) -> bytes:
    if (not _u32(session.vehicle_id) or type(session.command_key) is not bytes
            or type(session.telemetry_key) is not bytes
            or len(session.command_key) != 32 or len(session.telemetry_key) != 32
            or session.command_key == session.telemetry_key):
        raise WireProtocolError("Sesión no autenticada.")
    return _decode(session.session_id, 16)


def _verify(mac: object, expected: str) -> None:
    if type(mac) is not str or HEX64.fullmatch(mac) is None or not hmac.compare_digest(mac, expected):
        raise WireProtocolError("HMAC incorrecto.")


def _frame(msg: object, name: str, size: int, key: bytes, context: bytes) -> bytes:
    if (type(msg) is not dict or set(msg) != {"tipo", "sesion", "paquete", "firma"}
            or msg["tipo"] != name):
        raise WireProtocolError("Estructura incorrecta.")
    if type(msg["sesion"]) is not str:
        raise WireProtocolError("Sesión inválida.")
    data = _decode(msg["paquete"], size)
    digest = hmac.new(key, context + data, sha256).hexdigest()
    _verify(msg["firma"], digest)
    return data


@dataclass(frozen=True)
class DeviceOrder:
    vehicle_id: int
    session_id: str
    operation_id: str
    generation: int
    epoch: int
    sequence: int
    issued_at_ms: int
    expires_at_ms: int
    duration_ms: int
    code: int


@dataclass(frozen=True)
class DeviceAck:
    vehicle_id: int
    session_id: str
    operation_id: str
    generation: int
    epoch: int
    sequence: int
    device_time_ms: int
    phase: int
    neutral: bool


class CommandWire:
    """Mismo formato de bytes para emisor FastAPI y consumidor virtual."""

    def __init__(self, session: SessionLike):
        self._session = session
        self._session_bytes = _session(session)

    def sign_order(self, order: DeviceOrder) -> dict:
        if order.vehicle_id != self._session.vehicle_id or order.session_id != self._session.session_id:
            raise WireProtocolError("Orden para otra sesión.")
        if not all(_u32(x) for x in (order.generation, order.epoch, order.sequence)):
            raise WireProtocolError("Época o secuencia inválida.")
        if not _u64(order.issued_at_ms) or not _u64(order.expires_at_ms):
            raise WireProtocolError("Tiempo inválido.")
        if (not 0 < order.expires_at_ms - order.issued_at_ms <= MAX_PACKET_TTL_MS):
            raise WireProtocolError("Plazo de entrega inválido.")
        if type(order.code) is not int or order.code not in (DIRECTIONS | {0}):
            raise WireProtocolError("Acción inválida.")
        if (type(order.duration_ms) is not int or
                (order.duration_ms != 0 if order.code == 0 else not 100 <= order.duration_ms <= 500)):
            raise WireProtocolError("Duración inválida.")
        if order.duration_ms > order.expires_at_ms - order.issued_at_ms:
            raise WireProtocolError("El plazo no cubre la duración.")
        raw = ORDER.pack(VERSION, order.vehicle_id, self._session_bytes,
                         _uuid(order.operation_id), order.generation, order.epoch,
                         order.sequence, order.issued_at_ms, order.expires_at_ms,
                         order.duration_ms, order.code)
        return {"tipo": "orden_dispositivo_v1", "sesion": order.session_id,
                "paquete": _encode(raw),
                "firma": hmac.new(self._session.command_key, ORDER_CONTEXT + raw, sha256).hexdigest()}

    def verify_order(self, frame: object, *, now_ms: int) -> DeviceOrder:
        if not _u64(now_ms):
            raise WireProtocolError("Reloj inválido.")
        raw = _frame(frame, "orden_dispositivo_v1", ORDER.size,
                     self._session.command_key, ORDER_CONTEXT)
        version, vehicle, session, operation, generation, epoch, seq, issued, expires, duration, code = ORDER.unpack(raw)
        if (version != VERSION or vehicle != self._session.vehicle_id
                or session != self._session_bytes or frame["sesion"] != self._session.session_id):
            raise WireProtocolError("Orden ajena a la sesión.")
        candidate = DeviceOrder(vehicle, frame["sesion"], str(UUID(bytes=operation)),
                                generation, epoch, seq, issued, expires, duration, code)
        self.sign_order(candidate)  # comprobar también restricciones de dominio
        if not issued <= now_ms < expires:
            raise WireProtocolError("Orden no vigente.")
        return candidate

    def sign_ack(self, ack: DeviceAck) -> dict:
        if ack.vehicle_id != self._session.vehicle_id or ack.session_id != self._session.session_id:
            raise WireProtocolError("Acuse de otra sesión.")
        if not all(_u32(x) for x in (ack.generation, ack.epoch, ack.sequence)):
            raise WireProtocolError("Acuse fuera de secuencia.")
        if not _u64(ack.device_time_ms):
            raise WireProtocolError("Marca de tiempo inválida.")
        if type(ack.phase) is not int or ack.phase not in (1, 2, 3):
            raise WireProtocolError("Fase inválida.")
        if type(ack.neutral) is not bool or (ack.phase == PHASE_NEUTRAL) != ack.neutral:
            raise WireProtocolError("Neutral no corresponde a la fase.")
        raw = ACK.pack(VERSION, ack.vehicle_id, self._session_bytes,
                       _uuid(ack.operation_id), ack.generation, ack.epoch,
                       ack.sequence, ack.device_time_ms, ack.phase, int(ack.neutral))
        return {"tipo": "acuse_dispositivo_v1", "sesion": ack.session_id,
                "paquete": _encode(raw),
                "firma": hmac.new(self._session.telemetry_key, ACK_CONTEXT + raw, sha256).hexdigest()}

    def verify_ack(self, frame: object) -> DeviceAck:
        raw = _frame(frame, "acuse_dispositivo_v1", ACK.size,
                     self._session.telemetry_key, ACK_CONTEXT)
        version, vehicle, session, operation, generation, epoch, seq, device_ms, phase, neutral = ACK.unpack(raw)
        if (version != VERSION or vehicle != self._session.vehicle_id
                or session != self._session_bytes or frame["sesion"] != self._session.session_id
                or neutral not in (0, 1)):
            raise WireProtocolError("Acuse ajeno a la sesión.")
        value = DeviceAck(vehicle, frame["sesion"], str(UUID(bytes=operation)),
                          generation, epoch, seq, device_ms, phase, bool(neutral))
        self.sign_ack(value)
        return value


class AckFence:
    """Solo una operación pendiente; STOP puede invalidar MOVE inmediato.

    No se libera el siguiente conductor automáticamente: el acuse de neutro
    solo confirma estado lógico de la salida reportado por el microcontrolador.
    """

    def __init__(self, wire: CommandWire):
        self.wire = wire
        self.pending: DeviceOrder | None = None
        self.received = False
        self.latest_generation = 0
        self.latest_epoch = 0
        self.latest_seq = 0
        self.poisoned = False

    def queue(self, order: DeviceOrder) -> dict:
        if self.poisoned:
            raise WireProtocolError("Sesión bloqueada.")
        if (order.generation < self.latest_generation or
                order.generation == self.latest_generation and order.epoch < self.latest_epoch or
                order.sequence <= self.latest_seq):
            raise WireProtocolError("Orden antigua.")
        if self.pending is not None and order.code != 0:
            raise WireProtocolError("Hay una operación pendiente.")
        if self.pending is not None and order.code == 0:
            if (order.generation, order.epoch) <= (self.pending.generation, self.pending.epoch):
                raise WireProtocolError("STOP debe avanzar la época.")
        frame = self.wire.sign_order(order)
        self.pending = order
        self.received = False
        self.latest_generation = order.generation
        self.latest_epoch = order.epoch
        self.latest_seq = order.sequence
        return frame

    def consume(self, frame: object) -> str:
        try:
            ack = self.wire.verify_ack(frame)
            pending = self.pending
            if pending is None or (ack.vehicle_id, ack.session_id, ack.operation_id,
                    ack.generation, ack.epoch, ack.sequence) != (
                    pending.vehicle_id, pending.session_id, pending.operation_id,
                    pending.generation, pending.epoch, pending.sequence):
                raise WireProtocolError("Acuse no correlacionado.")
            if ack.phase == PHASE_RECEIVED:
                if self.received or ack.neutral:
                    raise WireProtocolError("Recepción inválida.")
                self.received = True
                return "recibida"
            if ack.phase == PHASE_NEUTRAL:
                if not self.received or not ack.neutral:
                    raise WireProtocolError("Falta acuse previo o neutro.")
                self.pending = None
                self.received = False
                return "neutral_reportado_no_fisico"
            if ack.phase == PHASE_REJECTED:
                self.pending = None
                self.received = False
                return "rechazada"
            raise WireProtocolError("Fase desconocida.")
        except WireProtocolError:
            self.poisoned = True
            self.pending = None
            raise

    def transport_lost(self) -> None:
        self.poisoned = True
        self.pending = None

    @property
    def physical_stop_verified(self) -> bool:
        return False
