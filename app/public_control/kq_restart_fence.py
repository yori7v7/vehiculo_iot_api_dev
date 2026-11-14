"""5.5-K-Q: journal de epocas para aislar sesiones virtuales entre reinicios.

Este componente NO concede turnos, no acepta peticiones HTTP, no crea tokens
de movimiento y nunca despacha el 74HC595. Reutiliza el repositorio SQLite
privado del simulador; usar SIEMPRE un archivo dedicado y aislado del legacy.

Cada arranque incrementa una epoca durable y cierra cualquier rastro de
sesiones/ventanas antiguas en ese archivo; una segunda instancia local queda
excluida por CoordinatorOwnership. Las epocas no certifican STOP fisico.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Final

from app.public_control.ownership import CoordinatorOwnership
from app.public_control.repository import PublicControlRepository

VEHICLE_ID: Final[int] = 1
BLOCKED: Final[str] = "kq_virtual_sin_traspaso_fisico"
_MAX_COUNTER: Final[int] = 2**63 - 2


class FenceRejected(RuntimeError):
    """La epoca no es vigente, el journal no esta abierto o fue bloqueado."""


class KQRestartFence:
    """Reinicio durable fail-closed del modelo virtual; NO autoridad fisica.

    No compartir con la base SQLite utilizada por otra etapa. El objeto puede
    abrirse una sola vez; para otro arranque debe crearse una instancia nueva.
    """

    def __init__(self, path: Path | str):
        self._repo = PublicControlRepository(path)
        self._owner = CoordinatorOwnership(path)
        self._epoch: int | None = None
        self._invalidated = False
        self._opened_once = False

    @staticmethod
    def _close_virtual_state(db) -> None:
        # No convertir STOP pendiente en confirmado: mantenerlo INCIERTO.
        db.execute(
            "UPDATE control_operation SET status = 'incierta' "
            "WHERE vehicle_id = ? AND kind IN ('stop','revoke') "
            "AND status = 'pendiente'", (VEHICLE_ID,),
        )
        db.execute(
            "UPDATE control_operation SET status = 'incierta' "
            "WHERE vehicle_id = ? AND kind = 'move' "
            "AND status IN ('aceptada','despachada')", (VEHICLE_ID,),
        )
        db.execute(
            "UPDATE control_turn SET active = 0 WHERE vehicle_id = ? AND active = 1",
            (VEHICLE_ID,),
        )

    @classmethod
    def _rotate(cls, db) -> int:
        row = db.execute(
            "SELECT epoch, generation, revision FROM control_vehicle WHERE vehicle_id = ?",
            (VEHICLE_ID,),
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO control_vehicle (vehicle_id, blocked_reason) VALUES (?, ?)",
                (VEHICLE_ID, BLOCKED),
            )
            row = db.execute(
                "SELECT epoch, generation, revision FROM control_vehicle WHERE vehicle_id = ?",
                (VEHICLE_ID,),
            ).fetchone()
        if any(row[key] >= _MAX_COUNTER for key in ("epoch", "generation", "revision")):
            raise FenceRejected("Contador durable agotado; no reutilizar epoca")
        cls._close_virtual_state(db)
        db.execute(
            "UPDATE control_vehicle SET epoch = epoch + 1, "
            "generation = generation + 1, revision = revision + 1, "
            "window_started = NULL, window_expires = NULL, window_request = NULL, "
            "stop_id = NULL, blocked_reason = ? WHERE vehicle_id = ?",
            (BLOCKED, VEHICLE_ID),
        )
        return int(row["epoch"]) + 1

    def start(self) -> int:
        """Adquirir exclusividad y reiniciar SIEMPRE revocando el estado antiguo."""
        if self._opened_once:
            raise FenceRejected("No se puede reabrir la misma instancia")
        self._opened_once = True
        self._owner.acquire()
        try:
            self._repo.initialize()
            with self._repo.transaction() as db:
                epoch = self._rotate(db)
            self._epoch = epoch
            self._invalidated = False
            return epoch
        except BaseException:
            self._owner.release()
            raise

    @contextmanager
    def transaction(self, epoch: int):
        """Verificar y operar bajo EL MISMO bloqueo transaccional SQLite.

        K-R nunca hace check-then-act por separado; la epoca vigente y la
        mutacion deben estar dentro del mismo BEGIN IMMEDIATE.
        """
        if (type(epoch) is not int or self._epoch is None
                or self._invalidated or epoch != self._epoch):
            raise FenceRejected("Epoca antigua o inaccesible")
        with self._repo.transaction() as db:
            row = db.execute(
                "SELECT epoch, blocked_reason, window_expires "
                "FROM control_vehicle WHERE vehicle_id = ?", (VEHICLE_ID,),
            ).fetchone()
            if (row is None or row["epoch"] != epoch
                    or row["blocked_reason"] != BLOCKED
                    or row["window_expires"] is not None
                    or self._invalidated):
                raise FenceRejected("El journal cambio o no esta cerrado")
            yield db
            # Una invalidacion concurrente invalida la operacion aunque
            # ocurra mientras el callback tenia el lock SQLite.
            if self._invalidated or self._epoch != epoch:
                raise FenceRejected("La autoridad se invalido durante la transaccion")

    def assert_current(self, epoch: int) -> None:
        """Verificar la epoca vigente con el mismo cierre transaccional."""
        with self.transaction(epoch):
            pass

    def invalidate(self) -> int:
        """Rotar epoch tras perdida WSS; NO puede rearmarse en este proceso."""
        if self._epoch is None or self._invalidated:
            raise FenceRejected("El journal no esta disponible")
        # Invalida primero el objeto local, aun si el disco deja de responder.
        prior_epoch = self._epoch
        self._invalidated = True
        with self._repo.transaction() as db:
            row = db.execute(
                "SELECT epoch FROM control_vehicle WHERE vehicle_id = ?",
                (VEHICLE_ID,),
            ).fetchone()
            if row is None or row["epoch"] != prior_epoch:
                raise FenceRejected("Otro propietario cambio la epoca")
            next_epoch = self._rotate(db)
        return next_epoch

    def close(self) -> None:
        """Cerrar la instancia, sin conceder permiso alguno."""
        self._invalidated = True
        self._epoch = None
        self._owner.release()

    def __enter__(self) -> "KQRestartFence":
        self.start()
        return self

    def __exit__(self, *_exception) -> None:
        self.close()
