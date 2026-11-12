"""Modelo de salidas local, sin cliente de red ni acceso a hardware."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from threading import RLock
from typing import Literal

from app.public_control.domain import MOVEMENT_CODES


StopOutcome = Literal["pendiente", "verificada", "incierta", "fallida"]
STOP_OUTCOMES = frozenset(("pendiente", "verificada", "incierta", "fallida"))


@dataclass
class SimulatedOutput:
    barrier: tuple[int, int] = (0, 0)
    code: int = 0
    deadline: float = 0
    move_id: str | None = None
    stop_id: str | None = None
    stop_outcome: StopOutcome = "verificada"

    def expire(self, now: float) -> None:
        if self.code and now >= self.deadline:
            self.code = 0


class SimulatedVehicleDispatcher:
    """Aplica límites y barreras a salidas virtuales en memoria."""

    def __init__(self, stop_outcome: Callable[[int, str], StopOutcome] | None = None) -> None:
        self._stop_outcome = stop_outcome
        self._outputs: dict[int, SimulatedOutput] = {}
        self._lock = RLock()
        self._interlocked = False

    def move(
        self, vehicle_id: int, *, code: int, generation: int, epoch: int,
        operation_id: str, deadline: float, now: float,
    ) -> None:
        if (
            type(code) is not int or code not in MOVEMENT_CODES.values()
            or not isfinite(now) or not isfinite(deadline)
            or not now < deadline <= now + 0.5
        ):
            raise ValueError("Movimiento simulado fuera de contrato.")
        with self._lock:
            output = self._outputs.setdefault(vehicle_id, SimulatedOutput())
            output.expire(now)
            barrier = (generation, epoch)
            if (
                self._interlocked or barrier < output.barrier
                or output.stop_outcome != "verificada" or output.code
                or output.move_id == operation_id
            ):
                raise RuntimeError("El simulador no admite ese movimiento.")
            output.barrier = barrier
            output.code = code
            output.deadline = deadline
            output.move_id = operation_id

    def stop(
        self, vehicle_id: int, *, generation: int, epoch: int,
        operation_id: str, now: float,
    ) -> StopOutcome:
        with self._lock:
            output = self._outputs.setdefault(vehicle_id, SimulatedOutput())
            barrier = (generation, epoch)
            if self._interlocked or barrier < output.barrier or not isfinite(now):
                return "incierta"
            output.expire(now)
            if output.stop_id == operation_id:
                return output.stop_outcome
            if output.stop_id is not None and barrier == output.barrier:
                return "incierta"
            output.barrier = barrier
            output.stop_id = operation_id
            output.stop_outcome = self._decide(vehicle_id, operation_id)
            if output.stop_outcome == "verificada":
                output.code = 0
            return output.stop_outcome

    def poll_stop(self, vehicle_id: int, operation_id: str, *, now: float) -> StopOutcome:
        with self._lock:
            output = self._outputs.get(vehicle_id)
            if self._interlocked or output is None or output.stop_id != operation_id or not isfinite(now):
                return "incierta"
            output.expire(now)
            if output.stop_outcome == "pendiente":
                output.stop_outcome = self._decide(vehicle_id, operation_id)
                if output.stop_outcome == "verificada":
                    output.code = 0
            return output.stop_outcome

    def is_safe(self, vehicle_id: int, *, now: float) -> bool:
        with self._lock:
            if self._interlocked or not isfinite(now):
                return False
            output = self._outputs.setdefault(vehicle_id, SimulatedOutput())
            output.expire(now)
            return output.code == 0 and output.stop_outcome == "verificada"

    def output_code(self, vehicle_id: int, *, now: float) -> int:
        """Inspección de las salidas virtuales para pruebas locales."""
        with self._lock:
            output = self._outputs.setdefault(vehicle_id, SimulatedOutput())
            output.expire(now)
            return output.code

    def interlock(self) -> None:
        """Inhabilitar esta instancia cuando el coordinador pierde garantías."""
        with self._lock:
            self._interlocked = True
            for output in self._outputs.values():
                output.code = 0
                output.stop_outcome = "incierta"

    def _decide(self, vehicle_id: int, operation_id: str) -> StopOutcome:
        if self._stop_outcome is None:
            return "verificada"
        try:
            outcome = self._stop_outcome(vehicle_id, operation_id)
        except Exception:
            return "fallida"
        return outcome if isinstance(outcome, str) and outcome in STOP_OUTCOMES else "incierta"
