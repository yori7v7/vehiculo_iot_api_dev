"""Pruebas locales del nuevo contrato; ninguna conexión externa."""
from dataclasses import replace
from hashlib import sha256
import hmac
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.device_channel.command_wire import (
    ACK, ORDER, ACK_CONTEXT, ORDER_CONTEXT,
    AckFence, CommandWire, DeviceAck, DeviceOrder, WireProtocolError,
)


def mock_session():
    import base64
    return SimpleNamespace(vehicle_id=1, session_id=base64.urlsafe_b64encode(b's' * 16).decode().rstrip('='),
                           command_key=bytes(range(32)), telemetry_key=bytes(range(32, 64)))


def command(*, code=9, duration=250, sequence=1, generation=1, epoch=1,
            issued=1000000, expires=1000750):
    return DeviceOrder(1, mock_session().session_id, str(uuid4()), generation,
                       epoch, sequence, issued, expires, duration, code)


def ack_for(order, *, phase=1, neutral=False):
    return DeviceAck(order.vehicle_id, order.session_id, order.operation_id,
                     order.generation, order.epoch, order.sequence,
                     order.issued_at_ms + 20, phase, neutral)


def test_fixed_binary_size_and_independent_hmac():
    w = CommandWire(mock_session())
    message = w.sign_order(command())
    import base64
    raw = base64.urlsafe_b64decode(message['paquete']+'=')
    assert len(raw) == ORDER.size == 68
    assert message['firma'] == hmac.new(mock_session().command_key, ORDER_CONTEXT+raw, sha256).hexdigest()
    a = w.sign_ack(ack_for(command()))
    raw_ack = base64.urlsafe_b64decode(a['paquete']+'=')
    assert len(raw_ack) == ACK.size == 59
    assert a['firma'] == hmac.new(mock_session().telemetry_key, ACK_CONTEXT+raw_ack, sha256).hexdigest()


def test_order_and_ack_roundtrip():
    w = CommandWire(mock_session())
    order = command()
    assert w.verify_order(w.sign_order(order), now_ms=1000100) == order
    ack = ack_for(order)
    assert w.verify_ack(w.sign_ack(ack)) == ack


@pytest.mark.parametrize('code', [0, 1, 2, 4, 5, 6, 8, 9, 10])
def test_exact_allowlist(code):
    w = CommandWire(mock_session())
    c = command(code=code, duration=0 if code == 0 else 100)
    assert w.sign_order(c)['tipo'] == 'orden_dispositivo_v1'


@pytest.mark.parametrize('code,duration', [(16,100), (32,100), (64,100), (128,100), (True,100), (3,100),
                                           (1,99), (1,501), (0,1), (1,True)])
def test_reject_aux_and_bad_durations(code, duration):
    with pytest.raises(WireProtocolError):
        CommandWire(mock_session()).sign_order(command(code=code, duration=duration))


@pytest.mark.parametrize('issued,expires', [(-1,1000), (1000,1000), (1000,1001), (1000,2001),
                                               (0,2**64), (True,1200)])
def test_reject_bad_time(issued, expires):
    with pytest.raises(WireProtocolError):
        CommandWire(mock_session()).sign_order(command(issued=issued, expires=expires, duration=100))


def test_order_must_not_be_expired_or_future():
    w = CommandWire(mock_session())
    frame = w.sign_order(command())
    for now in (999999, 1000750, 1000751, True):
        with pytest.raises(WireProtocolError):
            w.verify_order(frame, now_ms=now)


def test_signatures_are_session_bound_and_tamper_proof():
    w = CommandWire(mock_session())
    c = command()
    frame = w.sign_order(c)
    with pytest.raises(WireProtocolError):
        w.verify_order(dict(frame, firma='0'*64), now_ms=1000100)
    with pytest.raises(WireProtocolError):
        w.verify_order(dict(frame, sesion='other'), now_ms=1000100)
    with pytest.raises(WireProtocolError):
        w.verify_order(dict(frame, extra=1), now_ms=1000100)
    with pytest.raises(WireProtocolError):
        w.verify_order(dict(frame, paquete=frame['paquete'][:-1]+'A'), now_ms=1000100)


def test_ack_fence_sequence_and_replay():
    w = CommandWire(mock_session())
    f = AckFence(w)
    c = command()
    f.queue(c)
    with pytest.raises(WireProtocolError):
        f.queue(replace(c, operation_id=str(uuid4()), sequence=2))
    assert f.consume(w.sign_ack(ack_for(c))) == 'recibida'
    assert f.consume(w.sign_ack(ack_for(c,phase=2,neutral=True))) == 'neutral_reportado_no_fisico'
    assert f.physical_stop_verified is False
    with pytest.raises(WireProtocolError):
        f.consume(w.sign_ack(ack_for(c,phase=2,neutral=True)))
    assert f.poisoned


def test_stop_preempts_unacknowledged_move_and_old_ack_fails_closed():
    w = CommandWire(mock_session()); f = AckFence(w)
    c = command()
    f.queue(c)
    stop = replace(command(code=0,duration=0,issued=1000100,expires=1000900),sequence=2,epoch=2)
    f.queue(stop)
    assert f.pending == stop
    with pytest.raises(WireProtocolError):
        f.consume(w.sign_ack(ack_for(c)))
    assert f.poisoned and f.pending is None


def test_stop_requires_ack_but_does_not_unlock_physical():
    w = CommandWire(mock_session()); f = AckFence(w)
    stop = command(code=0, duration=0)
    f.queue(stop)
    with pytest.raises(WireProtocolError):
        f.consume(w.sign_ack(ack_for(stop,phase=2,neutral=True)))
    assert f.poisoned and not f.physical_stop_verified


def test_disconnect_blocks_remaining_operation():
    f=AckFence(CommandWire(mock_session()));f.queue(command());f.transport_lost()
    with pytest.raises(WireProtocolError):
        f.queue(command(sequence=2))
    assert not f.physical_stop_verified


def test_second_stop_must_be_new_epoch():
    w=CommandWire(mock_session());f=AckFence(w);f.queue(command(code=0,duration=0))
    with pytest.raises(WireProtocolError):
        f.queue(command(code=0,duration=0,sequence=2))
    stop2=command(code=0,duration=0,sequence=2,epoch=2)
    f.queue(stop2)
    assert f.pending == stop2
