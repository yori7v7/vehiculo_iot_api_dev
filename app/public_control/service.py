"""Aplicación de política, turnos y operaciones del control simulado."""

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from math import isfinite
import sqlite3
from threading import RLock
from time import monotonic as system_monotonic
from uuid import uuid4

from app.public_control.coordinator import (
    PublicControlCoordinator, active_turn, close_window, end_turn, operation, record, schedule_stop,
)
from app.public_control.domain import (
    GuestTokenService, MAX_SEQUENCE, MOVEMENT_CODES, PublicControlError, WINDOW_SECONDS,
    operation_response, request_identifier, stop_response, unavailable, unauthorized, utc,
)
from app.public_control.repository import StoreUnavailable


def _system_utc():
    return datetime.now(timezone.utc)


class PublicControlService:
    """Autoriza cada transición bajo una transacción SQLite y una barrera local."""

    def __init__(
        self, repository, dispatcher, *, now=_system_utc, monotonic=system_monotonic,
        vehicle_ids=(1,), turn_seconds=120, inactivity_seconds=20, rate_per_second=5,
    ):
        self._repository = repository
        self._dispatcher = dispatcher
        self._coordinator = PublicControlCoordinator(repository, dispatcher)
        self._vehicle_ids = frozenset(vehicle_ids)
        self._turn_seconds = turn_seconds
        self._inactivity_seconds = inactivity_seconds
        self._rate_per_second = rate_per_second
        self._now = now
        self._monotonic = monotonic
        self._lock = RLock()
        self._ready = False
        self._fault = False
        self._clock_anchor = None
        self._previous_clock = None
        self._claims = OrderedDict()

    def recover(self):
        with self._lock:
            if self._fault or self._ready:
                raise unavailable()
            try:
                wall, mono = self._read_clock()
                if not self._coordinator.recover(self._vehicle_ids, wall, mono):
                    self._fail_closed()
                self._coordinator.drive_stops(self._read_clock)
                self._ready = True
            except (StoreUnavailable, sqlite3.IntegrityError):
                self._fail_closed()

    def _fail_closed(self):
        self._fault = True
        self._ready = False
        self._dispatcher.interlock()
        raise unavailable() from None

    def _read_clock(self):
        try:
            instant = self._now()
            if instant.utcoffset() is None:
                raise ValueError
            wall, mono = instant.timestamp(), self._monotonic()
            if not isfinite(wall) or not isfinite(mono) or mono < 0:
                raise ValueError
        except Exception:
            self._fail_closed()
        if self._previous_clock is not None:
            last_wall, last_mono = self._previous_clock
            if wall < last_wall or mono < last_mono:
                self._fail_closed()
        else:
            self._clock_anchor = (wall, mono)
        self._previous_clock = (wall, mono)
        initial_wall, initial_mono = self._clock_anchor
        # Una corrección lenta del reloj de pared no prolonga permisos.
        effective_wall = max(wall, initial_wall + (mono - initial_mono))
        try:
            utc(effective_wall + WINDOW_SECONDS)
        except (ValueError, OverflowError, OSError):
            self._fail_closed()
        return effective_wall, mono

    @contextmanager
    def _cycle(self, vehicle_id=None):
        with self._lock:
            if not self._ready:
                raise unavailable()
            if vehicle_id is not None and vehicle_id not in self._vehicle_ids:
                raise PublicControlError(404, "vehiculo_no_encontrado", "El vehículo no existe en el simulador.")
            try:
                self._read_clock()
                self._coordinator.maintain(self._read_clock)
                self._coordinator.drive_stops(self._read_clock)
                yield
            except (StoreUnavailable, sqlite3.IntegrityError):
                self._fail_closed()

    def tick(self):
        with self._cycle():
            self._coordinator.drive_moves(self._read_clock)

    @contextmanager
    def _timed_transaction(self):
        with self._repository.transaction() as db:
            wall, mono = self._read_clock()
            yield db, wall, mono

    @staticmethod
    def _vehicle(db, vehicle_id):
        return db.execute("SELECT * FROM control_vehicle WHERE vehicle_id = ?", (vehicle_id,)).fetchone()

    def _safe(self, vehicle_id, mono):
        try:
            return self._dispatcher.is_safe(vehicle_id, now=mono)
        except Exception:
            self._fail_closed()

    def _state(self, db, vehicle, wall, mono, *, admin=False):
        vehicle_id = vehicle["vehicle_id"]
        turn = active_turn(db, vehicle_id)
        stop = operation(db, vehicle["stop_id"])
        enabled = vehicle["window_expires"] is not None and wall < vehicle["window_expires"]
        reason = vehicle["blocked_reason"]
        if stop is not None and stop["status"] == "pendiente":
            state = "deteniendo"
        elif reason:
            state = "bloqueado"
        elif turn is not None:
            state = "ocupado"
        elif not self._safe(vehicle_id, mono):
            state = "bloqueado"
            reason = "simulador_no_seguro"
        else:
            state = "disponible" if enabled else "cerrado"
        projection = {
            "id_vehiculo": vehicle_id,
            "habilitado": enabled,
            "estado": state,
            "vence_ventana_en": utc(vehicle["window_expires"]) if enabled else None,
            "hora_servidor": utc(wall),
            "revision": vehicle["revision"],
            "simulado": True,
        }
        if admin:
            projection.update(
                inicio_ventana_en=utc(vehicle["window_started"]),
                id_turno_auditoria=turn["turn_id"] if turn is not None else None,
                turno_vence_en=utc(turn["absolute_expires"]) if turn is not None else None,
                parada=stop_response(stop),
                motivo_bloqueo=reason,
            )
        return projection

    def status(self, vehicle_id):
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, mono):
            return self._state(db, self._vehicle(db, vehicle_id), wall, mono)

    def admin_status(self, vehicle_id):
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, mono):
            return self._state(db, self._vehicle(db, vehicle_id), wall, mono, admin=True)

    def audit(self, vehicle_id, limit=50):
        with self._cycle(vehicle_id), self._repository.transaction() as db:
            if type(limit) is not int or not 1 <= limit <= 100:
                raise PublicControlError(422, "solicitud_invalida", "El límite de auditoría no es válido.")
            rows = db.execute(
                "SELECT * FROM control_audit WHERE vehicle_id = ? ORDER BY audit_id DESC LIMIT ?",
                (vehicle_id, limit),
            ).fetchall()
            return [{
                "id_auditoria": row["audit_id"],
                "id_vehiculo": row["vehicle_id"],
                "hora": utc(row["occurred_at"]),
                "evento": row["event"],
                "id_turno": row["turn_id"],
                "id_operacion": row["operation_id"],
                "motivo": row["reason"],
            } for row in rows]

    def enable(self, vehicle_id, request_id, duration_seconds=WINDOW_SECONDS, supervision=True):
        request_id = request_identifier(request_id)
        if type(duration_seconds) is not int or duration_seconds != WINDOW_SECONDS or supervision is not True:
            raise PublicControlError(422, "ventana_invalida", "Confirma la supervisión y una duración de 1200 segundos.")
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, mono):
            vehicle = self._vehicle(db, vehicle_id)
            duplicate = db.execute(
                "SELECT 1 FROM control_window_request WHERE vehicle_id = ? AND request_id = ?",
                (vehicle_id, request_id),
            ).fetchone()
            if duplicate is not None:
                return self._state(db, vehicle, wall, mono, admin=True)
            if vehicle["window_expires"] is not None:
                raise PublicControlError(409, "ventana_activa", "Ya existe una ventana habilitada.")
            self._require_safe(db, vehicle, mono)
            expires = wall + WINDOW_SECONDS
            db.execute("INSERT INTO control_window_request VALUES (?, ?, ?, ?)",
                       (vehicle_id, request_id, wall, expires))
            db.execute(
                "UPDATE control_vehicle SET window_started = ?, window_expires = ?, window_request = ? "
                "WHERE vehicle_id = ?", (wall, expires, request_id, vehicle_id),
            )
            record(db, vehicle_id, wall, "ventana_habilitada")
            return self._state(db, self._vehicle(db, vehicle_id), wall, mono, admin=True)

    def _require_safe(self, db, vehicle, mono):
        stop = operation(db, vehicle["stop_id"])
        if stop is not None and stop["status"] == "pendiente":
            raise PublicControlError(409, "parada_pendiente", "El relevo espera una parada simulada.")
        if vehicle["blocked_reason"] or not self._safe(vehicle["vehicle_id"], mono):
            raise PublicControlError(503, "vehiculo_bloqueado", "El simulador está bloqueado.")

    def disable(self, vehicle_id):
        with self._cycle(vehicle_id):
            with self._timed_transaction() as (db, wall, mono):
                vehicle = self._vehicle(db, vehicle_id)
                turn = active_turn(db, vehicle_id)
                previous = operation(db, vehicle["stop_id"])
                already_closed = vehicle["window_expires"] is None and turn is None
                if already_closed and previous is not None and previous["status"] == "pendiente":
                    return 202, stop_response(previous)
                if already_closed and not vehicle["blocked_reason"] and self._safe(vehicle_id, mono):
                    return 200, self._state(db, vehicle, wall, mono, admin=True)
                close_window(db, vehicle_id)
                end_turn(db, turn)
                stop_id = schedule_stop(db, vehicle, wall, mono, reason="ventana_cerrada", turn=turn)
            return 202, self._complete_stop(stop_id)

    def _rate_claim(self, client_key, mono):
        if client_key is None:
            return
        while self._claims and next(iter(self._claims.values()))[0] + 5 <= mono:
            self._claims.popitem(last=False)
        started, attempts = self._claims.get(client_key, (mono, 0))
        if attempts >= 12 or (len(self._claims) >= 256 and client_key not in self._claims):
            raise PublicControlError(429, "limite_solicitudes", "Inténtalo de nuevo en unos segundos.", 5)
        self._claims[client_key] = (started, attempts + 1)

    def acquire(self, vehicle_id, client_key=None):
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, mono):
            self._rate_claim(client_key, mono)
            vehicle = self._vehicle(db, vehicle_id)
            if vehicle["window_expires"] is None or wall >= vehicle["window_expires"]:
                raise PublicControlError(409, "ventana_cerrada", "La ventana está cerrada.")
            stop = operation(db, vehicle["stop_id"])
            if stop is not None and stop["status"] == "pendiente":
                raise PublicControlError(409, "parada_pendiente", "El relevo espera una parada simulada.")
            if vehicle["blocked_reason"]:
                raise PublicControlError(503, "vehiculo_bloqueado", "El simulador está bloqueado.")
            if active_turn(db, vehicle_id) is not None:
                raise PublicControlError(409, "turno_ocupado", "El vehículo ya tiene un turno activo.")
            self._require_safe(db, vehicle, mono)
            token, digest = GuestTokenService.issue()
            turn_id = str(uuid4())
            absolute = min(wall + self._turn_seconds, vehicle["window_expires"])
            idle = min(wall + self._inactivity_seconds, absolute)
            generation = vehicle["generation"] + 1
            db.execute(
                "INSERT INTO control_turn(turn_id, vehicle_id, token_digest, generation, "
                "absolute_expires, idle_expires, granted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (turn_id, vehicle_id, digest, generation, absolute, idle, wall),
            )
            db.execute("UPDATE control_vehicle SET generation = ?, epoch = epoch + 1 WHERE vehicle_id = ?",
                       (generation, vehicle_id))
            record(db, vehicle_id, wall, "turno_concedido", turn_id=turn_id)
            projection = self._session(db, self._vehicle(db, vehicle_id), active_turn(db, vehicle_id), wall)
            return dict(projection, token=token)

    @staticmethod
    def _authorize(db, vehicle, token, wall):
        digest = GuestTokenService.digest(token)
        turn = db.execute(
            "SELECT * FROM control_turn WHERE vehicle_id = ? AND token_digest = ? AND active = 1",
            (vehicle["vehicle_id"], digest),
        ).fetchone()
        if (
            turn is None or turn["generation"] != vehicle["generation"]
            or vehicle["window_expires"] is None
            or wall >= min(turn["absolute_expires"], turn["idle_expires"], vehicle["window_expires"])
        ):
            raise unauthorized()
        return turn

    @staticmethod
    def _session(db, vehicle, turn, wall):
        last = db.execute(
            "SELECT * FROM control_operation WHERE turn_id = ? AND kind = 'move' ORDER BY sequence DESC LIMIT 1",
            (turn["turn_id"],),
        ).fetchone()
        stop = operation(db, vehicle["stop_id"])
        stopping = vehicle["blocked_reason"] or (stop is not None and stop["status"] == "pendiente")
        return {
            "id_vehiculo": vehicle["vehicle_id"],
            "estado": "deteniendo" if stopping else "activo",
            "vence_en": utc(turn["absolute_expires"]),
            "vence_inactividad_en": utc(turn["idle_expires"]),
            "hora_servidor": utc(wall),
            "epoca_operacion": vehicle["epoch"],
            "siguiente_secuencia": turn["last_seq"] + 1,
            "ultima_operacion": operation_response(last),
            "simulado": True,
        }

    def session(self, vehicle_id, token):
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, _):
            vehicle = self._vehicle(db, vehicle_id)
            return self._session(db, vehicle, self._authorize(db, vehicle, token, wall), wall)

    def _complete_stop(self, stop_id):
        self._coordinator.drive_stops(self._read_clock)
        with self._repository.transaction() as db:
            return stop_response(operation(db, stop_id))

    def release(self, vehicle_id, token):
        with self._cycle(vehicle_id):
            with self._timed_transaction() as (db, wall, mono):
                vehicle = self._vehicle(db, vehicle_id)
                turn = self._authorize(db, vehicle, token, wall)
                end_turn(db, turn)
                stop_id = schedule_stop(db, vehicle, wall, mono, reason="turno_cedido", turn=turn)
            return self._complete_stop(stop_id)

    @staticmethod
    def _stop_alias(db, vehicle_id, scope, request_id):
        row = db.execute(
            "SELECT operation_id FROM control_stop_request WHERE vehicle_id = ? AND scope = ? AND request_id = ?",
            (vehicle_id, scope, request_id),
        ).fetchone()
        return row["operation_id"] if row is not None else None

    def revoke(self, vehicle_id, request_id):
        request_id = request_identifier(request_id)
        with self._cycle(vehicle_id):
            with self._timed_transaction() as (db, wall, mono):
                previous = self._stop_alias(db, vehicle_id, "admin", request_id)
                if previous is not None:
                    return stop_response(operation(db, previous))
                vehicle = self._vehicle(db, vehicle_id)
                turn = active_turn(db, vehicle_id)
                stop = operation(db, vehicle["stop_id"])
                if turn is None and (stop is None or stop["status"] != "pendiente"):
                    raise PublicControlError(409, "turno_inexistente", "No hay un turno o una parada pendiente.")
                end_turn(db, turn)
                stop_id = schedule_stop(db, vehicle, wall, mono, reason="turno_revocado", turn=turn)
                db.execute("INSERT INTO control_stop_request VALUES (?, 'admin', ?, ?)",
                           (vehicle_id, request_id, stop_id))
            return self._complete_stop(stop_id)

    def stop(self, vehicle_id, token, request_id):
        request_id = request_identifier(request_id)
        with self._cycle(vehicle_id):
            with self._timed_transaction() as (db, wall, mono):
                vehicle = self._vehicle(db, vehicle_id)
                turn = self._authorize(db, vehicle, token, wall)
                scope = turn["turn_id"]
                previous = self._stop_alias(db, vehicle_id, scope, request_id)
                if previous is not None:
                    return stop_response(operation(db, previous))
                stop_id = schedule_stop(db, vehicle, wall, mono, reason="detener", turn=turn)
                db.execute("INSERT INTO control_stop_request VALUES (?, ?, ?, ?)",
                           (vehicle_id, scope, request_id, stop_id))
            return self._complete_stop(stop_id)

    def move(self, vehicle_id, token, request_id, sequence, epoch, duration_ms, action):
        request_id = request_identifier(request_id)
        if (
            not isinstance(action, str) or action not in MOVEMENT_CODES
            or type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE
            or type(epoch) is not int or not 1 <= epoch <= MAX_SEQUENCE
            or type(duration_ms) is not int or not 100 <= duration_ms <= 500
        ):
            raise PublicControlError(422, "movimiento_invalido", "La acción, secuencia o duración no es válida.")
        code = MOVEMENT_CODES[action]
        with self._cycle(vehicle_id), self._timed_transaction() as (db, wall, mono):
            vehicle = self._vehicle(db, vehicle_id)
            turn = self._authorize(db, vehicle, token, wall)
            turn_id = turn["turn_id"]
            previous = db.execute(
                "SELECT * FROM control_operation WHERE turn_id = ? AND kind = 'move' AND request_id = ?",
                (turn_id, request_id),
            ).fetchone()
            if previous is not None:
                if (previous["sequence"], previous["epoch"], previous["code"], previous["duration_ms"]) != (
                    sequence, epoch, code, duration_ms,
                ):
                    raise PublicControlError(409, "idempotencia_incompatible", "El identificador ya tiene otra solicitud.")
                return operation_response(previous)
            if epoch != vehicle["epoch"] or sequence != turn["last_seq"] + 1:
                raise PublicControlError(409, "orden_fuera_de_vigencia", "La época o secuencia no es vigente.")
            current = db.execute(
                "SELECT 1 FROM control_operation WHERE turn_id = ? AND kind = 'move' "
                "AND status IN ('aceptada','despachada') LIMIT 1", (turn_id,),
            ).fetchone()
            if current is not None:
                raise PublicControlError(409, "movimiento_en_curso", "Ya existe un movimiento pendiente o activo.")
            self._require_safe(db, vehicle, mono)
            rate = db.execute(
                "SELECT count(*) FROM control_operation WHERE turn_id = ? AND kind = 'move' "
                "AND deadline > ? AND deadline - duration_ms / 1000.0 > ?",
                (turn_id, mono - 1, mono - 1),
            ).fetchone()[0]
            if rate >= self._rate_per_second:
                raise PublicControlError(429, "limite_frecuencia", "Se alcanzó la frecuencia permitida.", 1)
            deadline = mono + duration_ms / 1000
            operation_id = str(uuid4())
            db.execute(
                "INSERT INTO control_operation(operation_id, vehicle_id, turn_id, generation, epoch, kind, "
                "request_id, sequence, code, duration_ms, created_at, deadline, status) "
                "VALUES (?, ?, ?, ?, ?, 'move', ?, ?, ?, ?, ?, ?, 'aceptada')",
                (operation_id, vehicle_id, turn_id, turn["generation"], epoch, request_id, sequence,
                 code, duration_ms, wall, deadline),
            )
            idle = min(wall + self._inactivity_seconds, turn["absolute_expires"])
            db.execute("UPDATE control_turn SET last_seq = ?, idle_expires = ? WHERE turn_id = ?",
                       (sequence, idle, turn_id))
            record(db, vehicle_id, wall, "movimiento_aceptado", turn_id=turn_id, operation_id=operation_id)
            return operation_response(operation(db, operation_id))
