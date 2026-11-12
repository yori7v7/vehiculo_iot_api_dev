"""Barreras de despacho, sin WebSocket, GPIO ni efectos sobre el vehículo.

Prototipo de la etapa 5.5-B: los productores (administrador/invitado)
comparten una única exclusión. Los acuses de GPIO en neutro son solo
observación; NO prueban inmovilidad física ni habilitan otro conductor.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import RLock
from typing import Literal
from uuid import UUID

DIRECTIONS = frozenset((1, 2, 4, 5, 6, 8, 9, 10))
Source = Literal["admin", "guest"]


class DispatchRejected(RuntimeError):
    """El guardián mantiene el despacho bloqueado."""


@dataclass(frozen=True)
class Envelope:
    operation_id: str
    vehicle_id: int
    session_id: str
    generation: int
    epoch: int
    sequence: int
    code: int
    duration_ms: int
    expires_at: float
    source: Source


@dataclass(frozen=True)
class StopEnvelope:
    operation_id: str
    vehicle_id: int
    session_id: str
    generation: int
    epoch: int
    code: int = 0


def valid_uuid(text: str) -> bool:
    if type(text) is not str:
        return False
    try:
        return str(UUID(text)) == text
    except ValueError:
        return False


class DeviceDispatchGuard:
    """Contrato síncrono para una sesión de *laboratorio*.

    No autoriza movimiento físico. Su salida son objetos de datos; ningún
    método transmite paquetes a hardware. El relevo requiere ratificación
    explícita del supervisor en cada nueva sesión.
    """

    def __init__(self, vehicle_id: int):
        if type(vehicle_id) is not int or not 0 < vehicle_id < 2**31:
            raise ValueError("Vehículo inválido")
        self.vehicle_id = vehicle_id
        self._lock = RLock()
        self._session_id: str | None = None
        self._generation = 0
        self._epoch = 0
        self._source: Source | None = None
        self._lease_id: str | None = None
        self._last_sequence = 0
        self._current: Envelope | None = None
        self._pending_stop: StopEnvelope | None = None
        self._stop_sent = False
        self._stopping_uncertain = True
        self._neutral_reported = False

    def authenticated_session(self, session_id: str) -> None:
        """Una reconexión invalida necesariamente la conducción anterior."""
        if not valid_uuid(session_id):
            raise ValueError("ID de sesión inválido")
        with self._lock:
            self._session_id = session_id
            self._generation += 1
            self._epoch += 1
            self._source = None
            self._lease_id = None
            self._last_sequence = 0
            self._current = None
            self._pending_stop = None
            self._stop_sent = False
            self._stopping_uncertain = True
            self._neutral_reported = False

    def lost_session(self) -> None:
        """Fail-closed incluso si no se sabe qué hizo el dispositivo."""
        with self._lock:
            self._session_id = None
            self._generation += 1
            self._epoch += 1
            self._source = None
            self._lease_id = None
            self._last_sequence = 0
            self._current = None
            self._pending_stop = None
            self._stop_sent = False
            self._stopping_uncertain = True
            self._neutral_reported = False

    def authorize_lab_lease(self, source: Source, lease_id: str, *, supervisor_confirmed: bool) -> None:
        """Solo habilita emisión de órdenes *virtuales* tras confirmación externa."""
        if source not in ("admin", "guest") or not valid_uuid(lease_id):
            raise ValueError("Conductor o licencia inválidos")
        with self._lock:
            if (self._session_id is None or self._source is not None or self._current is not None
                    or self._pending_stop is not None or self._stopping_uncertain
                    or not self._neutral_reported or supervisor_confirmed is not True):
                raise DispatchRejected("Relevo no autorizado")
            self._source = source
            self._lease_id = lease_id
            self._epoch += 1
            self._last_sequence = 0

    def prepare_move(self, *, source: Source, lease_id: str, operation_id: str,
                     sequence: int, generation: int, epoch: int,
                     code: int, duration_ms: int, now: float) -> Envelope:
        with self._lock:
            if (self._session_id is None or self._source != source or self._lease_id != lease_id
                    or self._stopping_uncertain or self._pending_stop is not None
                    or self._current is not None):
                raise DispatchRejected("Movimiento sin turno exclusivo")
            if (type(generation) is not int or type(epoch) is not int
                    or generation != self._generation or epoch != self._epoch
                    or type(sequence) is not int or sequence != self._last_sequence + 1):
                raise DispatchRejected("Orden obsoleta o fuera de secuencia")
            if (not valid_uuid(operation_id) or type(code) is not int or code not in DIRECTIONS
                    or type(duration_ms) is not int or not 100 <= duration_ms <= 500
                    or type(now) not in (int, float) or not isfinite(now) or now < 0):
                raise ValueError("Orden de movimiento fuera de contrato")
            cmd = Envelope(operation_id, self.vehicle_id, self._session_id,
                           generation, epoch, sequence, code, duration_ms,
                           now + duration_ms / 1000, source)
            self._current = cmd
            self._last_sequence = sequence
            return cmd

    def request_stop(self, operation_id: str) -> StopEnvelope:
        """STOP prioritario: elimina el movimiento anterior y sella la época."""
        if not valid_uuid(operation_id):
            raise ValueError("Operación inválida")
        with self._lock:
            if self._session_id is None:
                self.lost_session()
                raise DispatchRejected("Sin dispositivo autenticado; detención incierta")
            if self._pending_stop is not None:
                return self._pending_stop
            self._epoch += 1
            self._current = None
            self._source = None
            self._lease_id = None
            self._last_sequence = 0
            self._stopping_uncertain = True
            self._neutral_reported = False
            stop = StopEnvelope(operation_id, self.vehicle_id, self._session_id,
                                self._generation, self._epoch)
            self._pending_stop = stop
            self._stop_sent = False
            return stop

    def next_to_transmit(self) -> StopEnvelope | Envelope | None:
        """STOP siempre antes que MOVE. Devuelve datos, no envía."""
        with self._lock:
            if self._pending_stop is not None:
                self._stop_sent = True
                return self._pending_stop
            return self._current

    def confirm_stop(self, *, session_id: str, operation_id: str, generation: int,
                     epoch: int, neutral_reported: bool) -> None:
        with self._lock:
            stop = self._pending_stop
            if (stop is None or not self._stop_sent or neutral_reported is not True
                    or (session_id, operation_id, generation, epoch) !=
                    (stop.session_id, stop.operation_id, stop.generation, stop.epoch)):
                raise DispatchRejected("Parada sin acuse correlacionado")
            self._pending_stop = None
            self._neutral_reported = True
            # El acuse NO puede verificar inmovilidad física ni desbloquear por sí solo.
            self._stopping_uncertain = True

    def supervisor_clear_for_lab(self, *, confirmed: bool, now: float) -> None:
        """Permite un relevo SIMULADO, nunca autoriza control físico."""
        with self._lock:
            if (confirmed is not True or self._session_id is None
                    or self._pending_stop is not None or not self._neutral_reported
                    or type(now) not in (int, float) or not isfinite(now) or now < 0):
                raise DispatchRejected("No se cumple la condición de parada")
            self._stopping_uncertain = False

    def observed_move_expired(self, *, now: float) -> bool:
        """No supone STOP: si vence una orden, demanda una parada explícita."""
        with self._lock:
            if type(now) not in (int, float) or not isfinite(now) or now < 0:
                raise ValueError("Reloj inválido")
            if self._current is None or now < self._current.expires_at:
                return False
            self._current = None
            self._stopping_uncertain = True
            self._neutral_reported = False
            return True

    @property
    def barrier(self) -> tuple[int, int]:
        with self._lock:
            return self._generation, self._epoch

    @property
    def safe_for_physical_relay(self) -> bool:
        return False

    @property
    def stopping_uncertain(self) -> bool:
        with self._lock:
            return self._stopping_uncertain
