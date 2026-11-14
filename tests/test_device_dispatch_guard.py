"""Pruebas independientes del arbitraje, sin motores ni AWS."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.device_channel.dispatch_guard import DeviceDispatchGuard, DispatchRejected


def uid():
    return str(uuid4())


def ready():
    dispatcher = DeviceDispatchGuard(1)
    session = uid()
    dispatcher.authenticated_session(session)
    stop = dispatcher.request_stop(uid())
    assert dispatcher.next_to_transmit() == stop
    dispatcher.confirm_stop(
        session_id=session, operation_id=stop.operation_id,
        generation=stop.generation, epoch=stop.epoch, neutral_reported=True,
    )
    dispatcher.supervisor_clear_for_lab(confirmed=True, now=1)
    return dispatcher, session


def lease_for(dispatcher, role="guest"):
    lease = uid()
    dispatcher.authorize_lab_lease(role, lease, supervisor_confirmed=True)
    generation, epoch = dispatcher.barrier
    return lease, generation, epoch


def move(dispatcher, lease, generation, epoch):
    return dispatcher.prepare_move(
        source="guest", lease_id=lease, operation_id=uid(),
        generation=generation, epoch=epoch, sequence=1,
        code=9, duration_ms=250, now=5,
    )


def test_default_closed():
    d = DeviceDispatchGuard(1)
    assert d.stopping_uncertain and not d.safe_for_physical_relay
    with pytest.raises(DispatchRejected):
        d.authorize_lab_lease("guest", uid(), supervisor_confirmed=True)


def test_guest_move_exclusive():
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    cmd = move(d, lease, generation, epoch)
    assert cmd.source == "guest" and cmd.code == 9
    assert d.next_to_transmit() == cmd
    assert not d.safe_for_physical_relay


def test_admin_guest_are_mutually_exclusive():
    d, _ = ready()
    _, generation, epoch = lease_for(d, "admin")
    with pytest.raises(DispatchRejected):
        d.authorize_lab_lease("guest", uid(), supervisor_confirmed=True)
    with pytest.raises(DispatchRejected):
        d.prepare_move(
            source="guest", lease_id=uid(), operation_id=uid(), sequence=1,
            generation=generation, epoch=epoch, code=1, duration_ms=100, now=5,
        )


def test_stop_preempts_movement_and_requires_supervisor_to_reopen():
    d, session = ready()
    lease, generation, epoch = lease_for(d)
    move(d, lease, generation, epoch)
    stop = d.request_stop(uid())
    assert d.next_to_transmit() == stop and stop.code == 0
    with pytest.raises(DispatchRejected):
        d.authorize_lab_lease("admin", uid(), supervisor_confirmed=True)
    with pytest.raises(DispatchRejected):
        d.confirm_stop(
            session_id=session, operation_id=stop.operation_id,
            generation=stop.generation, epoch=stop.epoch, neutral_reported=False,
        )
    d.confirm_stop(
        session_id=session, operation_id=stop.operation_id,
        generation=stop.generation, epoch=stop.epoch, neutral_reported=True,
    )
    assert d.stopping_uncertain
    with pytest.raises(DispatchRejected):
        d.authorize_lab_lease("admin", uid(), supervisor_confirmed=True)
    d.supervisor_clear_for_lab(confirmed=True, now=10)
    d.authorize_lab_lease("admin", uid(), supervisor_confirmed=True)
    assert not d.safe_for_physical_relay


def test_wrong_ack_is_rejected():
    d, session = ready()
    stop = d.request_stop(uid())
    d.next_to_transmit()
    for overrides in (
        {"session_id": uid()},
        {"operation_id": uid()},
        {"generation": stop.generation - 1},
        {"epoch": stop.epoch + 1},
    ):
        fields = {
            "session_id": session, "operation_id": stop.operation_id,
            "generation": stop.generation, "epoch": stop.epoch,
            "neutral_reported": True,
        }
        fields.update(overrides)
        with pytest.raises(DispatchRejected):
            d.confirm_stop(**fields)
    assert d.stopping_uncertain


def test_ack_before_transmission_is_rejected():
    d, session = ready()
    stop = d.request_stop(uid())
    with pytest.raises(DispatchRejected):
        d.confirm_stop(
            session_id=session, operation_id=stop.operation_id,
            generation=stop.generation, epoch=stop.epoch, neutral_reported=True,
        )


def test_duplicate_stop_is_idempotent():
    d, _ = ready()
    stop = d.request_stop(uid())
    assert d.request_stop(uid()) == stop


def test_disconnect_invalidates_movement():
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    move(d, lease, generation, epoch)
    d.lost_session()
    assert d.next_to_transmit() is None and d.stopping_uncertain
    with pytest.raises(DispatchRejected):
        d.prepare_move(
            source="guest", lease_id=lease, operation_id=uid(), sequence=2,
            generation=generation, epoch=epoch, code=1, duration_ms=100, now=6,
        )


def test_reconnect_invalidates_old_generation():
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    d.authenticated_session(uid())
    assert d.barrier[0] > generation
    with pytest.raises(DispatchRejected):
        move(d, lease, generation, epoch)


def test_expired_movement_requires_explicit_stop():
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    move(d, lease, generation, epoch)
    assert not d.observed_move_expired(now=5.24)
    assert d.observed_move_expired(now=5.25)
    assert d.stopping_uncertain and d.next_to_transmit() is None
    with pytest.raises(DispatchRejected):
        d.prepare_move(
            source="guest", lease_id=lease, operation_id=uid(), sequence=2,
            generation=generation, epoch=epoch, code=1, duration_ms=100, now=6,
        )


@pytest.mark.parametrize("code", [0, 16, 32, 64, 128, True, -1, 3])
def test_rejects_unapproved_movement_codes(code):
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    with pytest.raises(ValueError):
        d.prepare_move(
            source="guest", lease_id=lease, operation_id=uid(), sequence=1,
            generation=generation, epoch=epoch, code=code, duration_ms=100, now=5,
        )


@pytest.mark.parametrize("duration", [-1, 0, 99, 501, True])
def test_rejects_invalid_duration(duration):
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    with pytest.raises(ValueError):
        d.prepare_move(
            source="guest", lease_id=lease, operation_id=uid(), sequence=1,
            generation=generation, epoch=epoch, code=1, duration_ms=duration, now=5,
        )


@pytest.mark.parametrize("clock", [-1, float("nan"), float("inf"), True])
def test_rejects_invalid_clock(clock):
    d, _ = ready()
    lease, generation, epoch = lease_for(d)
    with pytest.raises(ValueError):
        d.prepare_move(
            source="guest", lease_id=lease, operation_id=uid(), sequence=1,
            generation=generation, epoch=epoch, code=1, duration_ms=100, now=clock,
        )


def test_concurrent_claim_has_exactly_one_winner():
    d, _ = ready()

    def claim(_):
        try:
            d.authorize_lab_lease("guest", uid(), supervisor_confirmed=True)
            return True
        except DispatchRejected:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(claim, range(100)))
    assert sum(outcomes) == 1
