"""Coordinación, vencimientos y parada con SQLite y reloj controlado."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import re
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.public_control.domain import PublicControlError
from app.public_control.repository import PublicControlRepository, StoreUnavailable
from app.public_control.service import PublicControlService
from app.public_control.simulator import SimulatedVehicleDispatcher


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
        self.seconds = 1000.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.seconds += seconds


def identifier():
    return str(uuid4())


def service_for(path, *, dispatcher=None, clock=None, **limits):
    clock = clock or Clock()
    dispatcher = dispatcher or SimulatedVehicleDispatcher()
    repository = PublicControlRepository(path)
    repository.initialize()
    service = PublicControlService(repository, dispatcher, now=clock.now, monotonic=clock.monotonic, **limits)
    service.recover()
    return service, clock, dispatcher


def enable(service, vehicle_id=1, request_id=None):
    return service.enable(vehicle_id, request_id or identifier(), 1200, True)


def expect_status(status, fn, *args):
    with pytest.raises(PublicControlError) as error:
        fn(*args)
    assert error.value.status == status
    return error.value


def move(service, turn, request_id=None, action="AVANZAR", duration=100):
    return service.move(
        1, turn["token"], request_id or identifier(),
        turn["siguiente_secuencia"], turn["epoca_operacion"], duration, action,
    )


def test_window_exact_length_and_duplicate_open_does_not_renew(tmp_path):
    service, clock, _ = service_for(tmp_path / "window.sqlite3")
    request_id = identifier()
    first = enable(service, request_id=request_id)
    clock.advance(10)
    replay = enable(service, request_id=request_id)
    assert first["vence_ventana_en"] == replay["vence_ventana_en"]
    expect_status(409, enable, service)
    clock.advance(1189)
    assert service.status(1)["habilitado"]
    clock.advance(1)
    service.tick()
    assert not service.status(1)["habilitado"]
    assert service.status(1)["estado"] == "cerrado"


@pytest.mark.parametrize("attempt", range(6))
def test_only_one_guest_can_acquire_under_concurrency(tmp_path, attempt):
    service, _, _ = service_for(tmp_path / f"race-{attempt}.sqlite3")
    enable(service)
    barrier = Barrier(3)

    def acquire(client):
        barrier.wait(timeout=5)
        try:
            return 201, service.acquire(1, f"test-client-{client}")
        except PublicControlError as error:
            return error.status, None

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(acquire, range(3)))
    assert sorted(status for status, _ in results) == [201, 409, 409]
    tokens = [turn["token"] for _, turn in results if turn]
    assert len(tokens) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{43}", tokens[0])
    assert tokens[0].encode() not in (tmp_path / f"race-{attempt}.sqlite3").read_bytes()
    assert tokens[0] not in json.dumps(service.audit(1), default=str)


def test_lease_inactivity_releases_a_lost_browser_token_after_stop(tmp_path):
    service, clock, _ = service_for(tmp_path / "lost.sqlite3", turn_seconds=120, inactivity_seconds=3)
    enable(service)
    first = service.acquire(1, "first")
    expect_status(409, service.acquire, 1, "other")
    clock.advance(3)
    service.tick()
    expect_status(401, service.session, 1, first["token"])
    second = service.acquire(1, "other")
    assert second["token"] != first["token"]


def test_absolute_lease_deadline_cannot_be_extended_by_movements(tmp_path):
    service, clock, _ = service_for(tmp_path / "absolute.sqlite3", turn_seconds=4, inactivity_seconds=3)
    enable(service)
    first = service.acquire(1)
    clock.advance(2)
    move(service, first)
    service.tick()
    clock.advance(2.1)
    service.tick()
    expect_status(401, service.session, 1, first["token"])
    assert service.status(1)["estado"] == "disponible"


def test_window_expiration_stops_a_dispatched_movement_and_closes_turn(tmp_path):
    service, clock, dispatcher = service_for(tmp_path / "window-active.sqlite3")
    enable(service)
    clock.advance(1199.8)
    turn = service.acquire(1)
    move(service, turn, duration=500)
    service.tick()
    assert dispatcher.output_code(1, now=clock.monotonic()) == 1
    clock.advance(0.21)
    service.tick()
    assert dispatcher.output_code(1, now=clock.monotonic()) == 0
    assert service.status(1)["estado"] == "cerrado"
    expect_status(401, service.session, 1, turn["token"])


def test_releasing_a_turn_keeps_vehicle_reserved_until_stop_is_verified(tmp_path):
    outcome = "pendiente"
    dispatcher = SimulatedVehicleDispatcher(lambda *_: outcome)
    service, clock, _ = service_for(tmp_path / "pending-stop.sqlite3", dispatcher=dispatcher)
    enable(service)
    turn = service.acquire(1)
    move(service, turn)
    service.tick()
    stopped = service.release(1, turn["token"])
    assert stopped["estado"] == "pendiente"
    expect_status(401, service.session, 1, turn["token"])
    expect_status(409, service.acquire, 1)
    outcome = "verificada"
    clock.advance(0.05)
    service.tick()
    assert service.status(1)["estado"] == "disponible"
    assert service.acquire(1)["token"] != turn["token"]


@pytest.mark.parametrize("outcome", ["incierta", "fallida"])
def test_failed_or_uncertain_stop_never_releases_interlock(tmp_path, outcome):
    dispatcher = SimulatedVehicleDispatcher(lambda *_: outcome)
    service, clock, _ = service_for(tmp_path / "uncertain.sqlite3", dispatcher=dispatcher)
    enable(service)
    turn = service.acquire(1)
    result = service.revoke(1, identifier())
    assert result["estado"] == outcome
    clock.advance(10)
    service.tick()
    assert service.status(1)["estado"] == "bloqueado"
    expect_status(401, service.session, 1, turn["token"])
    with pytest.raises(PublicControlError):
        service.acquire(1)


def test_stop_is_idempotent_and_rejects_a_move_from_the_prior_epoch(tmp_path):
    service, _, dispatcher = service_for(tmp_path / "barrier.sqlite3")
    enable(service)
    turn = service.acquire(1)
    request = identifier()
    accepted = move(service, turn, request)
    repeated = move(service, turn, request)
    assert accepted["id_operacion"] == repeated["id_operacion"]
    expect_status(409, move, service, turn, request, "RETROCEDER")
    stop_request = identifier()
    result = service.stop(1, turn["token"], stop_request)
    replay = service.stop(1, turn["token"], stop_request)
    assert replay["id_operacion"] == result["id_operacion"]
    assert result["epoca_operacion"] > turn["epoca_operacion"]
    expect_status(409, move, service, turn)
    assert dispatcher.is_safe(1, now=1000)


def test_rate_limit_does_not_block_stop(tmp_path):
    service, clock, _ = service_for(tmp_path / "rate.sqlite3", rate_per_second=1)
    enable(service)
    turn = service.acquire(1)
    move(service, turn)
    service.tick()
    clock.advance(0.2)
    service.tick()
    current = dict(service.session(1, turn["token"]), token=turn["token"])
    expect_status(429, move, service, current)
    assert service.stop(1, turn["token"], identifier())["estado"] == "verificada"


def test_recovery_revokes_window_and_does_not_replay_pending_operation(tmp_path):
    path = tmp_path / "recover.sqlite3"
    service, clock, _ = service_for(path)
    enable(service)
    turn = service.acquire(1)
    move(service, turn)
    replacement, _, new_dispatcher = service_for(path, clock=clock)
    assert not replacement.status(1)["habilitado"]
    expect_status(401, replacement.session, 1, turn["token"])
    replacement.tick()
    assert new_dispatcher.output_code(1, now=clock.monotonic()) == 0


def test_stop_without_confirmation_expires_as_uncertain(tmp_path):
    outcome = "pendiente"
    dispatcher = SimulatedVehicleDispatcher(lambda *_: outcome)
    service, clock, _ = service_for(tmp_path / "lost-ack.sqlite3", dispatcher=dispatcher)
    enable(service)
    turn = service.acquire(1)
    stop_id = identifier()
    assert service.stop(1, turn["token"], stop_id)["estado"] == "pendiente"
    clock.advance(2.01)
    service.tick()
    assert service.admin_status(1)["parada"]["estado"] == "incierta"
    assert service.status(1)["estado"] == "bloqueado"
    outcome = "verificada"
    service.tick()
    assert service.admin_status(1)["parada"]["estado"] == "incierta"


def test_queued_motion_does_not_start_after_its_original_deadline(tmp_path):
    service, clock, dispatcher = service_for(tmp_path / "late.sqlite3")
    enable(service)
    turn = service.acquire(1)
    move(service, turn, duration=100)
    clock.advance(0.2)
    service.tick()
    assert dispatcher.output_code(1, now=clock.monotonic()) == 0
    assert service.session(1, turn["token"])["ultima_operacion"]["estado"] == "rechazada"


def test_vehicle_mismatch_and_out_of_order_commands_do_not_reach_simulator(tmp_path):
    service, clock, dispatcher = service_for(tmp_path / "scope.sqlite3", vehicle_ids=(1, 2))
    enable(service)
    enable(service, 2)
    turn = service.acquire(1)
    expect_status(401, service.session, 2, turn["token"])
    expect_status(409, move, service, dict(turn, siguiente_secuencia=2))
    expect_status(422, move, service, turn, identifier(), "LUCES")
    service.tick()
    assert dispatcher.output_code(1, now=clock.monotonic()) == 0
    assert dispatcher.output_code(2, now=clock.monotonic()) == 0


def test_backward_wall_clock_does_not_reopen_lease(tmp_path):
    service, clock, dispatcher = service_for(tmp_path / "clock.sqlite3")
    enable(service)
    turn = service.acquire(1)
    move(service, turn)
    service.tick()
    clock.wall -= timedelta(seconds=30)
    expect_status(503, service.tick)
    assert not dispatcher.is_safe(1, now=clock.monotonic())
    clock.advance(60)
    expect_status(503, service.acquire, 1)


def test_store_failure_trips_simulated_dispatcher_without_recovering_automatically(tmp_path):
    service, clock, dispatcher = service_for(tmp_path / "database-failure.sqlite3")
    enable(service)
    turn = service.acquire(1)
    move(service, turn)
    service.tick()
    with patch.object(PublicControlRepository, "transaction", side_effect=StoreUnavailable("detalle ficticio")):
        error = expect_status(503, service.tick)
        assert "detalle ficticio" not in str(error)
    assert not dispatcher.is_safe(1, now=clock.monotonic())
    expect_status(503, service.acquire, 1)
