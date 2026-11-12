"""El simulador comprueba barreras y vencimientos con tiempo inyectado."""

from uuid import uuid4

import pytest

from app.public_control.simulator import SimulatedVehicleDispatcher


def move(dispatcher, *, operation_id=None, code=1, generation=1, epoch=1, now=10, deadline=10.5):
    dispatcher.move(
        1, code=code, generation=generation, epoch=epoch, operation_id=operation_id or str(uuid4()),
        now=now, deadline=deadline,
    )


def test_simulated_output_expires_and_same_operation_cannot_restart_it():
    dispatcher = SimulatedVehicleDispatcher()
    operation_id = str(uuid4())
    move(dispatcher, operation_id=operation_id, code=5)
    assert dispatcher.output_code(1, now=10.49) == 5
    assert dispatcher.output_code(1, now=10.5) == 0
    with pytest.raises(RuntimeError):
        move(dispatcher, operation_id=operation_id, now=10.5, deadline=11)


@pytest.mark.parametrize("code,deadline", [(0, 10.5), (16, 10.5), (32, 10.5), (64, 10.5),
                                             (128, 10.5), (True, 10.5), (1, 10), (1, 10.501)])
def test_simulator_rejects_auxiliaries_stop_as_movement_and_invalid_deadline(code, deadline):
    dispatcher = SimulatedVehicleDispatcher()
    with pytest.raises(ValueError):
        move(dispatcher, code=code, deadline=deadline)
    assert dispatcher.output_code(1, now=10) == 0


def test_pending_stop_prevents_restart_even_after_the_simulated_output_expires():
    outcome = "pendiente"
    dispatcher = SimulatedVehicleDispatcher(lambda *_: outcome)
    move(dispatcher)
    stop_id = str(uuid4())
    assert dispatcher.stop(1, generation=1, epoch=2, operation_id=stop_id, now=10.1) == "pendiente"
    assert dispatcher.output_code(1, now=10.5) == 0
    assert not dispatcher.is_safe(1, now=10.5)
    with pytest.raises(RuntimeError):
        move(dispatcher, epoch=2, now=10.5, deadline=11)

    outcome = "verificada"
    assert dispatcher.poll_stop(1, stop_id, now=10.51) == "verificada"
    assert dispatcher.is_safe(1, now=10.51)
    with pytest.raises(RuntimeError):
        move(dispatcher, epoch=1, now=10.51, deadline=10.8)
    move(dispatcher, epoch=2, code=10, now=10.51, deadline=10.8)
    assert dispatcher.output_code(1, now=10.6) == 10


@pytest.mark.parametrize("outcome", ["incierta", "fallida"])
def test_unsuccessful_stop_is_distinct_and_does_not_report_safe(outcome):
    dispatcher = SimulatedVehicleDispatcher(lambda *_: outcome)
    move(dispatcher)
    stop_id = str(uuid4())
    assert dispatcher.stop(1, generation=1, epoch=2, operation_id=stop_id, now=10.1) == outcome
    assert dispatcher.poll_stop(1, stop_id, now=10.5) == outcome
    assert not dispatcher.is_safe(1, now=10.5)


def test_process_interlock_neutralizes_outputs_without_verifying_a_stop():
    dispatcher = SimulatedVehicleDispatcher()
    move(dispatcher)
    dispatcher.interlock()
    assert dispatcher.output_code(1, now=10.1) == 0
    assert not dispatcher.is_safe(1, now=10.1)
    assert dispatcher.stop(1, generation=2, epoch=2, operation_id=str(uuid4()), now=10.1) == "incierta"
