"""55-K: protocolo auxiliar opt-in, sin AWS ni GPIO."""
import base64
import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.device_channel.command_wire import (
    CommandWire, DeviceOrder, WireProtocolError
)


def session():
    return SimpleNamespace(
        vehicle_id=1,
        session_id=base64.urlsafe_b64encode(
            b"s" * 16
        ).decode().rstrip("="),
        command_key=bytes(range(32)),
        telemetry_key=bytes(range(32, 64)),
    )


def order(code, duration):
    return DeviceOrder(
        1, session().session_id, str(uuid4()),
        1, 1, 1, 1000000, 1000900,
        duration, code
    )


class TestAuxiliary55K(unittest.TestCase):

    def test_default_stays_closed(self):
        wire = CommandWire(session())
        for code in (16, 32, 64, 128):
            with self.assertRaises(WireProtocolError):
                wire.sign_order(order(code, 100))

    def test_three_auxiliaries_explicitly_enabled(self):
        wire = CommandWire(
            session(), allow_auxiliary=True
        )
        for code in (16, 32, 128):
            for duration in (100, 300):
                operation = order(code, duration)
                frame = wire.sign_order(operation)
                verified = wire.verify_order(
                    frame, now_ms=1000100
                )
                self.assertEqual(verified, operation)

    def test_original_demo_remains_blocked(self):
        wire = CommandWire(
            session(), allow_auxiliary=True
        )
        with self.assertRaises(WireProtocolError):
            wire.sign_order(order(64, 300))

    def test_invalid_durations_and_flag(self):
        wire = CommandWire(
            session(), allow_auxiliary=True
        )
        for duration in (0, 99, 301, 500):
            with self.assertRaises(WireProtocolError):
                wire.sign_order(order(16, duration))
        with self.assertRaises(WireProtocolError):
            CommandWire(session(), allow_auxiliary=1)

    def test_default_decoder_rejects_auxiliary(self):
        enabled = CommandWire(
            session(), allow_auxiliary=True
        )
        disabled = CommandWire(session())
        frame = enabled.sign_order(order(128, 300))
        with self.assertRaises(WireProtocolError):
            disabled.verify_order(
                frame, now_ms=1000100
            )

    def test_hmac_cannot_be_bypassed(self):
        wire = CommandWire(
            session(), allow_auxiliary=True
        )
        frame = wire.sign_order(order(32, 300))
        frame["firma"] = "0" * 64
        with self.assertRaises(WireProtocolError):
            wire.verify_order(
                frame, now_ms=1000100
            )

    def test_original_direction_and_stop(self):
        wire = CommandWire(session())
        for code in (0, 1, 2, 4, 5, 6, 8, 9, 10):
            duration = 0 if code == 0 else 100
            operation = order(code, duration)
            frame = wire.sign_order(operation)
            self.assertEqual(
                wire.verify_order(
                    frame, now_ms=1000100
                ).code,
                code
            )


if __name__ == "__main__":
    unittest.main()
