"""Contrato de prueba compatible con 5.4-D, sin abrir puerto USB ni AWS."""
from hashlib import sha256
import hmac

import pytest

from app.device_channel.lab54d import (
    ACK_DOMAIN, ACK_STRUCT, HELLO_DOMAIN, HELLO_STRUCT, CMD_DOMAIN, CMD_STRUCT,
    Lab54DCodec, LabKeys, LabProtocolError, DiagnosticAckFence, VERSION,
)


KEYS = LabKeys(b"TEST-54D-COMMAND-KEY-ONLY-LOCAL!", b"TEST-54D-ACK-KEY-NOT-FOR-REAL!!!")


def signed(prefix, values, fmt, domain, key=KEYS.device):
    raw = fmt.pack(*values)
    return f"{prefix}|{raw.hex()}|{hmac.new(key, domain + raw, sha256).hexdigest()}"


def hello(*, vehicle=1, boot=5678, generation=1, last=0, millis=1000, simulated=1):
    return signed("HELLO54D", (VERSION, vehicle, boot, generation, last, millis, simulated),
                  HELLO_STRUCT, HELLO_DOMAIN)


def ack(*, vehicle=1, boot=5678, generation=1, sequence=1, operation=54,
        phase=1, millis=1100, simulated=1):
    return signed("ACK54D", (VERSION, vehicle, boot, generation, sequence, operation,
                              phase, millis, simulated), ACK_STRUCT, ACK_DOMAIN)


def test_key_provision_must_be_explicit_distinct_and_exact():
    with pytest.raises(ValueError):
        LabKeys(b"x", b"y")
    with pytest.raises(ValueError):
        LabKeys(b"x" * 32, b"x" * 32)
    assert "TEST-54D" not in repr(KEYS)


def test_fixture_binary_contract_matches_usb_54d_exactly():
    codec = Lab54DCodec(KEYS, vehicle=1)
    frame = codec.command(boot=5678, generation=1, sequence=1, operation=54,
                          issued_ms=1000, duration_ms=500, code=9)
    label, hexbody, signature = frame.split("|")
    raw = bytes.fromhex(hexbody)
    assert label == "CMD54D"
    assert len(raw) == 32
    assert CMD_STRUCT.unpack(raw) == (2, 1, 5678, 1, 1, 54, 1000, 1500, 500, 9)
    assert signature == hmac.new(KEYS.command, CMD_DOMAIN + raw, sha256).hexdigest()


@pytest.mark.parametrize("code", [0, 1, 2, 4, 5, 6, 8, 9, 10])
def test_allowlist_is_exact(code):
    codec = Lab54DCodec(KEYS, vehicle=1)
    frame = codec.command(boot=1, generation=1, sequence=1, operation=1,
                          issued_ms=1, duration_ms=0 if code == 0 else 100, code=code)
    assert frame.startswith("CMD54D|")


@pytest.mark.parametrize("code,duration", [(16, 100), (32, 100), (64, 100), (128, 100),
                                            (True, 100), (1, 99), (1, 501), (0, 1)])
def test_auxiliaries_and_invalid_duration_rejected(code, duration):
    codec = Lab54DCodec(KEYS, vehicle=1)
    with pytest.raises(LabProtocolError):
        codec.command(boot=1, generation=1, sequence=1, operation=1,
                      issued_ms=1, duration_ms=duration, code=code)


def test_reject_tampered_frame_and_wrong_vehicle_or_real_marker():
    codec = Lab54DCodec(KEYS, vehicle=1)
    valid = hello()
    assert codec.hello(valid).boot == 5678
    parts = valid.split("|")
    parts[1] = parts[1][:-2] + ("02" if parts[1][-2:] != "02" else "01")
    with pytest.raises(LabProtocolError):
        codec.hello("|".join(parts))
    with pytest.raises(LabProtocolError):
        codec.hello(hello(vehicle=2))
    with pytest.raises(LabProtocolError):
        codec.hello(hello(simulated=0))
    with pytest.raises(LabProtocolError):
        codec.hello(valid.replace("HELLO54D", "OTHER", 1))


def test_fail_closed_on_reordered_repeated_and_wrong_operation_acks():
    c = DiagnosticAckFence(Lab54DCodec(KEYS, vehicle=1))
    c.observe_hello(hello())
    frame = c.prepare(sequence=1, operation=54, duration_ms=500, code=1, issued_ms=1000)
    assert frame.startswith("CMD54D|")
    with pytest.raises(LabProtocolError):
        c.accept_ack(ack(phase=2))
    with pytest.raises(LabProtocolError):
        c.accept_ack(ack(operation=55))
    assert c.accept_ack(ack(phase=1)) == "recibida_simulada"
    with pytest.raises(LabProtocolError):
        c.accept_ack(ack(phase=1))
    assert c.accept_ack(ack(phase=2)) == "neutral_virtual"
    assert not c.safe_for_physical_relay
    with pytest.raises(LabProtocolError):
        c.accept_ack(ack(phase=2))
    with pytest.raises(LabProtocolError):
        c.prepare(sequence=2, operation=55, duration_ms=100, code=1, issued_ms=1200)
    c.observe_hello(hello(last=1, millis=1200))
    assert c.prepare(sequence=2, operation=55, duration_ms=100, code=1, issued_ms=1200)


def test_stop_requires_fresh_hello_and_stale_boot_fails_closed():
    c = DiagnosticAckFence(Lab54DCodec(KEYS, vehicle=1))
    c.observe_hello(hello())
    c.prepare(sequence=1, operation=9, duration_ms=0, code=0, issued_ms=1000)
    assert c.accept_ack(ack(operation=9, phase=1)) == "recibida_simulada"
    assert c.accept_ack(ack(operation=9, phase=2)) == "neutral_virtual"
    c.observe_hello(hello(generation=2, last=1))
    with pytest.raises(LabProtocolError):
        c.observe_hello(hello(boot=99, generation=2, last=1))
    assert c.hello is None
    assert c.pending is None


def test_rejected_ack_never_counts_as_neutral():
    c = DiagnosticAckFence(Lab54DCodec(KEYS, vehicle=1))
    c.observe_hello(hello())
    c.prepare(sequence=1, operation=54, duration_ms=100, code=1, issued_ms=1000)
    assert c.accept_ack(ack(phase=3)) == "rechazada"
    assert c.safe_for_physical_relay is False


def test_ack_with_wrong_generation_rejected():
    c = DiagnosticAckFence(Lab54DCodec(KEYS, vehicle=1))
    c.observe_hello(hello())
    c.prepare(sequence=1, operation=54, duration_ms=100, code=1, issued_ms=1000)
    with pytest.raises(LabProtocolError):
        c.accept_ack(ack(generation=2, phase=1))


def test_rejects_malformed_frames():
    codec = Lab54DCodec(KEYS, vehicle=1)
    for value in ("", "HELLO54D|xyz|123", "HELLO54D||", hello() + "\n",
                  hello().upper(), hello() + "|extra", "HELLO54D|" + "0"*500):
        with pytest.raises(LabProtocolError):
            codec.hello(value)
