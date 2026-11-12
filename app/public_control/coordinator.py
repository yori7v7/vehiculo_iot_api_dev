"""Barreras persistentes y despacho serial del simulador."""

from uuid import uuid4

from app.public_control.domain import STOP_CONFIRMATION_SECONDS


def operation(db, operation_id):
    return db.execute(
        "SELECT * FROM control_operation WHERE operation_id = ?", (operation_id,),
    ).fetchone()


def active_turn(db, vehicle_id):
    return db.execute(
        "SELECT * FROM control_turn WHERE vehicle_id = ? AND active = 1", (vehicle_id,),
    ).fetchone()


def record(db, vehicle_id, now, event, *, turn_id=None, operation_id=None, reason=None):
    db.execute(
        "INSERT INTO control_audit(vehicle_id, occurred_at, event, turn_id, operation_id, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vehicle_id, now, event, turn_id, operation_id, reason),
    )
    db.execute("UPDATE control_vehicle SET revision = revision + 1 WHERE vehicle_id = ?", (vehicle_id,))


def close_window(db, vehicle_id):
    db.execute(
        "UPDATE control_vehicle SET window_started = NULL, window_expires = NULL, "
        "window_request = NULL WHERE vehicle_id = ?", (vehicle_id,),
    )


def end_turn(db, turn):
    if turn is not None:
        db.execute("UPDATE control_turn SET active = 0 WHERE turn_id = ?", (turn["turn_id"],))


def schedule_stop(db, vehicle, now, mono, *, reason, turn=None, force=False):
    vehicle_id = vehicle["vehicle_id"]
    previous = operation(db, vehicle["stop_id"])
    turn_id = turn["turn_id"] if turn is not None else None
    if previous is not None and previous["status"] == "pendiente":
        if not force:
            record(db, vehicle_id, now, "parada_compartida", turn_id=turn_id,
                   operation_id=previous["operation_id"], reason=reason)
            return previous["operation_id"]
        db.execute("UPDATE control_operation SET status = 'incierta' WHERE operation_id = ?",
                   (previous["operation_id"],))
    stop_id = str(uuid4())
    epoch = vehicle["epoch"] + 1
    db.execute(
        "UPDATE control_vehicle SET epoch = ?, stop_id = ?, blocked_reason = NULL WHERE vehicle_id = ?",
        (epoch, stop_id, vehicle_id),
    )
    discarded = db.execute(
        "UPDATE control_operation SET status = 'rechazada' "
        "WHERE vehicle_id = ? AND kind = 'move' AND status = 'aceptada' RETURNING operation_id, turn_id",
        (vehicle_id,),
    ).fetchall()
    for movement in discarded:
        record(db, vehicle_id, now, "movimiento_descartado", turn_id=movement["turn_id"],
               operation_id=movement["operation_id"], reason=reason)
    db.execute(
        "INSERT INTO control_operation(operation_id, vehicle_id, turn_id, generation, epoch, kind, "
        "code, duration_ms, created_at, deadline, status) VALUES (?, ?, ?, ?, ?, 'stop', 0, 0, ?, ?, 'pendiente')",
        (stop_id, vehicle_id, turn_id, vehicle["generation"], epoch, now, mono + STOP_CONFIRMATION_SECONDS),
    )
    record(db, vehicle_id, now, "parada_solicitada", turn_id=turn_id, operation_id=stop_id, reason=reason)
    return stop_id


class PublicControlCoordinator:
    """Programa paradas antes de despachar nuevos movimientos."""

    def __init__(self, repository, dispatcher):
        self.repository = repository
        self.dispatcher = dispatcher
        self._issued_stops = set()

    def recover(self, vehicle_ids, now, mono):
        with self.repository.transaction() as db:
            last = db.execute("SELECT max(occurred_at) FROM control_audit").fetchone()[0]
            if last is not None and now < last:
                return False
            for vehicle_id in vehicle_ids:
                db.execute("INSERT OR IGNORE INTO control_vehicle(vehicle_id) VALUES (?)", (vehicle_id,))
            for vehicle in db.execute("SELECT * FROM control_vehicle").fetchall():
                vehicle_id = vehicle["vehicle_id"]
                turn = active_turn(db, vehicle_id)
                pending = operation(db, vehicle["stop_id"])
                unfinished = db.execute(
                    "SELECT 1 FROM control_operation WHERE vehicle_id = ? AND kind = 'move' "
                    "AND status IN ('aceptada','despachada') LIMIT 1", (vehicle_id,),
                ).fetchone()
                if (turn is not None or vehicle["window_expires"] is not None or vehicle["blocked_reason"]
                        or unfinished is not None or (pending is not None and pending["status"] == "pendiente")):
                    close_window(db, vehicle_id)
                    end_turn(db, turn)
                    schedule_stop(db, vehicle, now, mono, reason="reinicio", turn=turn, force=True)
        return True

    def maintain(self, read_clock):
        with self.repository.transaction() as db:
            for vehicle in db.execute("SELECT * FROM control_vehicle").fetchall():
                now, mono = read_clock()
                self._expire(db, vehicle, now, mono)

    def _expire(self, db, vehicle, now, mono):
        vehicle_id = vehicle["vehicle_id"]
        turn = active_turn(db, vehicle_id)
        if vehicle["window_expires"] is not None and now >= vehicle["window_expires"]:
            close_window(db, vehicle_id)
            end_turn(db, turn)
            schedule_stop(db, vehicle, now, mono, reason="ventana_vencida", turn=turn)
            return
        if turn is None:
            return
        if now >= min(turn["absolute_expires"], turn["idle_expires"]):
            reason = "turno_vencido" if now >= turn["absolute_expires"] else "inactividad"
            end_turn(db, turn)
            schedule_stop(db, vehicle, now, mono, reason=reason, turn=turn)
            return
        due = db.execute(
            "SELECT * FROM control_operation WHERE turn_id = ? AND epoch = ? AND kind = 'move' "
            "AND status IN ('aceptada','despachada') AND deadline <= ?",
            (turn["turn_id"], vehicle["epoch"], mono),
        ).fetchone()
        if due is None:
            return
        if due["status"] == "despachada":
            schedule_stop(db, vehicle, now, mono, reason="fin_movimiento", turn=turn)
        else:
            db.execute("UPDATE control_operation SET status = 'rechazada' WHERE operation_id = ?",
                       (due["operation_id"],))
            record(db, vehicle_id, now, "movimiento_vencido", turn_id=turn["turn_id"],
                   operation_id=due["operation_id"])

    def drive_stops(self, read_clock):
        with self.repository.transaction() as db:
            pending = db.execute(
                "SELECT o.* FROM control_vehicle v JOIN control_operation o ON o.operation_id = v.stop_id "
                "WHERE o.status = 'pendiente'",
            ).fetchall()
        for stop in pending:
            self._drive_stop(stop, read_clock)

    def _drive_stop(self, stop, read_clock):
        _, mono = read_clock()
        stop_id = stop["operation_id"]
        vehicle_id = stop["vehicle_id"]
        issued = stop_id in self._issued_stops
        try:
            if not issued:
                outcome = self.dispatcher.stop(
                    vehicle_id, generation=stop["generation"], epoch=stop["epoch"],
                    operation_id=stop_id, now=mono,
                )
            elif mono < stop["deadline"]:
                outcome = self.dispatcher.poll_stop(vehicle_id, stop_id, now=mono)
            else:
                outcome = "incierta"
        except Exception:
            outcome = "fallida"
        now, mono = read_clock()
        if outcome == "pendiente" and mono < stop["deadline"]:
            self._issued_stops.add(stop_id)
            return
        if outcome == "verificada" and mono >= stop["deadline"]:
            outcome = "incierta"
        if outcome not in ("verificada", "fallida"):
            outcome = "incierta"
        self._issued_stops.discard(stop_id)
        verified = outcome == "verificada"
        with self.repository.transaction() as db:
            db.execute("UPDATE control_operation SET status = ?, verified_at = ? WHERE operation_id = ?",
                       (outcome, now if verified else None, stop_id))
            db.execute("UPDATE control_vehicle SET blocked_reason = ? WHERE vehicle_id = ? AND stop_id = ?",
                       (None if verified else f"parada_{outcome}", vehicle_id, stop_id))
            db.execute(
                "UPDATE control_operation SET status = ? WHERE vehicle_id = ? AND kind = 'move' "
                "AND status = 'despachada' AND epoch < ?",
                ("finalizada" if verified else "incierta", vehicle_id, stop["epoch"]),
            )
            record(db, vehicle_id, now, f"parada_{outcome}", turn_id=stop["turn_id"], operation_id=stop_id)

    def drive_moves(self, read_clock):
        with self.repository.transaction() as db:
            accepted = db.execute(
                "SELECT operation_id FROM control_operation WHERE kind = 'move' AND status = 'aceptada' "
                "ORDER BY created_at, operation_id",
            ).fetchall()
        for (operation_id,) in accepted:
            self._drive_move(operation_id, read_clock)
        self.drive_stops(read_clock)

    def _drive_move(self, operation_id, read_clock):
        with self.repository.transaction() as db:
            move = operation(db, operation_id)
            vehicle_id = move["vehicle_id"]
            vehicle = db.execute("SELECT * FROM control_vehicle WHERE vehicle_id = ?", (vehicle_id,)).fetchone()
            turn = active_turn(db, vehicle_id)
            stop = operation(db, vehicle["stop_id"])
            now, mono = read_clock()
            allowed = (
                move["status"] == "aceptada" and mono < move["deadline"]
                and turn is not None and turn["turn_id"] == move["turn_id"]
                and now < min(turn["absolute_expires"], turn["idle_expires"])
                and vehicle["window_expires"] is not None and now < vehicle["window_expires"]
                and move["generation"] == vehicle["generation"] and move["epoch"] == vehicle["epoch"]
                and not vehicle["blocked_reason"] and (stop is None or stop["status"] == "verificada")
            )
            if not allowed:
                db.execute("UPDATE control_operation SET status = 'rechazada' WHERE operation_id = ? "
                           "AND status = 'aceptada'", (operation_id,))
                record(db, vehicle_id, now, "movimiento_descartado", turn_id=move["turn_id"],
                       operation_id=operation_id, reason="fuera_de_vigencia")
                return
            try:
                self.dispatcher.move(
                    vehicle_id, code=move["code"], generation=move["generation"], epoch=move["epoch"],
                    operation_id=operation_id, deadline=move["deadline"], now=mono,
                )
            except Exception:
                db.execute("UPDATE control_operation SET status = 'incierta' WHERE operation_id = ?",
                           (operation_id,))
                end_turn(db, turn)
                schedule_stop(db, vehicle, now, mono, reason="fallo_despacho", turn=turn)
                record(db, vehicle_id, now, "movimiento_incierto", turn_id=move["turn_id"],
                       operation_id=operation_id, reason="fallo_despacho")
                return
            db.execute("UPDATE control_operation SET status = 'despachada' WHERE operation_id = ?", (operation_id,))
            record(db, vehicle_id, now, "movimiento_despachado", turn_id=move["turn_id"], operation_id=operation_id)
