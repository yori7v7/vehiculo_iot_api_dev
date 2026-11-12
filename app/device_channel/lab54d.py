"""Verificación aislada del protocolo USB 5.4-D (SOLO LABORATORIO).

No usa Wi-Fi, WebSocket, serie ni actuadores. El firmware 5.4-D emplea
claves de prueba PUBLICAS y carece de desafío fresco; por tanto, ESTE MODULO
NO AUTORIZA ni habilita operación física. No registrar ni exponer las claves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import re
import struct

CMD_DOMAIN = b"54D-CMD-v1"
ACK_DOMAIN = b"54D-ACK-v1"
HELLO_DOMAIN = b"54D-HLO-v1"
CMD_STRUCT = struct.Struct(">BIIIIIIIHB")
ACK_STRUCT = struct.Struct(">BIIIIIBIB")
HELLO_STRUCT = struct.Struct(">BIIIIIB")
VERSION = 2
DIRECTIONS = frozenset({1, 2, 4, 5, 6, 8, 9, 10})
HEX = re.compile(r"[0-9a-f]+\Z", re.ASCII)
UINT32 = 2**32 - 1


class LabProtocolError(ValueError):
    """Mensaje inválido, no autenticado o fuera de secuencia."""


@dataclass(frozen=True, repr=False)
class LabKeys:
    """Claves de prueba suministradas por el llamador, NUNCA por defecto."""

    command: bytes
    device: bytes

    def __post_init__(self):
        if (type(self.command) is not bytes or type(self.device) is not bytes
                or len(self.command) != 32 or len(self.device) != 32
                or self.command == self.device):
            raise ValueError("Se necesitan dos claves de laboratorio diferentes de 32 bytes.")


@dataclass(frozen=True)
class Hello:
    version: int
    vehicle: int
    boot: int
    generation: int
    last_sequence: int
    device_millis: int
    simulated: int


@dataclass(frozen=True)
class Ack:
    version: int
    vehicle: int
    boot: int
    generation: int
    sequence: int
    operation: int
    phase: int
    device_millis: int
    simulated: int


@dataclass(frozen=True)
class Pending:
    boot: int
    generation: int
    sequence: int
    operation: int
    stop: bool
    received: bool = False


class Lab54DCodec:
    """Codificador/decodificador USB independiente del transporte."""

    def __init__(self, keys: LabKeys, *, vehicle: int):
        if type(vehicle) is not int or not 0 < vehicle <= UINT32:
            raise ValueError("Vehículo inválido.")
        self._keys = keys
        self.vehicle = vehicle

    @staticmethod
    def _read(line: str, prefix: str, size: int, domain: bytes, key: bytes) -> bytes:
        if type(line) is not str or len(line) > 200 or "\n" in line or "\r" in line:
            raise LabProtocolError("Marco inválido.")
        parts = line.split("|")
        if (len(parts) != 3 or parts[0] != prefix or len(parts[1]) != size * 2
                or len(parts[2]) != 64 or not HEX.fullmatch(parts[1])
                or not HEX.fullmatch(parts[2])):
            raise LabProtocolError("Formato de marco inválido.")
        raw = bytes.fromhex(parts[1])
        mac = bytes.fromhex(parts[2])
        expected = hmac.new(key, domain + raw, sha256).digest()
        if not hmac.compare_digest(expected, mac):
            raise LabProtocolError("Firma de laboratorio inválida.")
        return raw

    def hello(self, line: str) -> Hello:
        raw = self._read(line, "HELLO54D", HELLO_STRUCT.size, HELLO_DOMAIN, self._keys.device)
        msg = Hello(*HELLO_STRUCT.unpack(raw))
        if (msg.version != VERSION or msg.vehicle != self.vehicle or msg.simulated != 1
                or msg.boot == 0 or msg.generation == 0):
            raise LabProtocolError("HELLO de laboratorio no válido.")
        return msg

    def ack(self, line: str) -> Ack:
        raw = self._read(line, "ACK54D", ACK_STRUCT.size, ACK_DOMAIN, self._keys.device)
        msg = Ack(*ACK_STRUCT.unpack(raw))
        if (msg.version != VERSION or msg.vehicle != self.vehicle or msg.simulated != 1
                or msg.boot == 0 or msg.generation == 0 or msg.sequence == 0
                or msg.operation == 0 or msg.phase not in (1, 2, 3)):
            raise LabProtocolError("ACK de laboratorio no válido.")
        return msg

    def command(self, *, boot: int, generation: int, sequence: int, operation: int,
                issued_ms: int, duration_ms: int, code: int) -> str:
        for value in (boot, generation, sequence, operation, issued_ms):
            if type(value) is not int or not 0 < value <= UINT32:
                raise LabProtocolError("Identificador inválido.")
        if type(code) is not int or code not in DIRECTIONS | {0}:
            raise LabProtocolError("Código fuera de la lista blanca de laboratorio.")
        if type(duration_ms) is not int or (duration_ms != 0 if code == 0 else not 100 <= duration_ms <= 500):
            raise LabProtocolError("Duración inválida.")
        expires = (issued_ms + duration_ms) & UINT32
        raw = CMD_STRUCT.pack(VERSION, self.vehicle, boot, generation, sequence, operation,
                              issued_ms, expires, duration_ms, code)
        mac = hmac.new(self._keys.command, CMD_DOMAIN + raw, sha256).hexdigest()
        return f"CMD54D|{raw.hex()}|{mac}"


@dataclass
class DiagnosticAckFence:
    """Correlación estricta de una operación; NO prueba inmovilidad física.

    Exige una nueva lectura HELLO tras parada; no interpreta el ACK de GPIO
    virtual como prueba de dispositivo en producción.
    """

    codec: Lab54DCodec
    hello: Hello | None = None
    pending: Pending | None = None
    _previous_boot: int | None = field(default=None, init=False, repr=False)
    _awaiting_fresh_hello: bool = field(default=False, init=False, repr=False)

    def observe_hello(self, frame: str) -> Hello:
        msg = self.codec.hello(frame)
        if self.pending is not None:
            raise LabProtocolError("Hay una operación sin resolver.")
        if self._previous_boot is not None and msg.boot != self._previous_boot:
            self.fail_closed()
            raise LabProtocolError("Reinicio: nueva autorización manual requerida.")
        if self.hello is not None and msg.generation < self.hello.generation:
            self.fail_closed()
            raise LabProtocolError("Generación anterior.")
        self.hello = msg
        self._previous_boot = msg.boot
        self._awaiting_fresh_hello = False
        return msg

    def prepare(self, *, sequence: int, operation: int, duration_ms: int,
                code: int, issued_ms: int) -> str:
        h = self.hello
        if h is None or self.pending is not None or self._awaiting_fresh_hello:
            raise LabProtocolError("No hay HELLO válido o la operación anterior sigue pendiente.")
        if type(sequence) is not int or sequence != h.last_sequence + 1 or sequence > UINT32:
            raise LabProtocolError("Secuencia inesperada.")
        frame = self.codec.command(boot=h.boot, generation=h.generation,
                                   sequence=sequence, operation=operation, issued_ms=issued_ms,
                                   duration_ms=duration_ms, code=code)
        self.pending = Pending(h.boot, h.generation, sequence, operation, code == 0)
        return frame

    def accept_ack(self, frame: str) -> str:
        ack = self.codec.ack(frame)
        op = self.pending
        if op is None or (ack.boot, ack.generation, ack.sequence, ack.operation) != (
                op.boot, op.generation, op.sequence, op.operation):
            raise LabProtocolError("ACK desconocido o repetido.")
        if ack.phase == 1:
            if op.received:
                raise LabProtocolError("Recepción repetida.")
            self.pending = Pending(op.boot, op.generation, op.sequence, op.operation,
                                   op.stop, True)
            return "recibida_simulada"
        if ack.phase == 2 and not op.received:
            raise LabProtocolError("Falta acuse previo de recepción.")
        if ack.phase in (2, 3):
            self.pending = None
            self._awaiting_fresh_hello = True
            self.hello = None
            return "neutral_virtual" if ack.phase == 2 else "rechazada"
        raise LabProtocolError("Fase imposible.")

    def fail_closed(self) -> None:
        self.hello = None
        self.pending = None
        self._awaiting_fresh_hello = True

    @property
    def safe_for_physical_relay(self) -> bool:
        return False
