import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.platform43 import demos, operations
from app.platform43.models import Demo
from app.platform43.sockets import PlatformEvents
from scripts.catalog43_hj2025 import ADDITIONS, BASE, change


class DemoContractTests(unittest.TestCase):
    def test_only_horn_step_is_bounded_and_original_is_rejected(self):
        def demo(code, duration):
            return Demo(nombre="Prueba", pasos=[{"codigo": code, "duracion_ms": duration, "pausa_ms": 1000}])

        self.assertEqual(demo(128, 300).pasos[0].duracion_ms, 300)
        self.assertEqual(demo(1, 1000).pasos[0].duracion_ms, 1000)
        for code, duration in [(128, 301), (64, 30)]:
            with self.assertRaises(ValidationError):
                demo(code, duration)

    def test_persisted_horn_timing_is_checked_before_execution(self):
        plan = [{"codigo": 128, "id_comando": 9, "duracion_ms": 301}]
        with patch.object(demos, "all_rows", return_value=plan):
            with self.assertRaises(HTTPException) as error:
                demos.operational_steps(Mock(), {"modelo": 1, "vehiculo": 1}, 1)
        self.assertEqual(error.exception.status_code, 409)


class PhysicalDispatchTests(unittest.IsolatedAsyncioTestCase):
    def event(self, code, kind="movimiento"):
        return {"id_vehiculo": 1, "codigo": code, "tipo_evento": kind, "id_evento": "fixture"}

    async def test_dispatch_requires_opted_in_firmware_and_horn_releases_request(self):
        events = PlatformEvents(dispatch=False, device_connections=True)
        socket = SimpleNamespace(send_json=AsyncMock())
        events.devices[1] = (socket, lambda: None, True)
        self.assertFalse(events.dispatch_status(1)["demo_original"])
        self.assertEqual(await events.to_device(1, self.event(64)), "inhibido")
        socket.send_json.assert_not_called()
        events.dispatch = True
        events.devices[1] = (socket, lambda: None, False)
        self.assertEqual(await events.to_device(1, self.event(64)), "inhibido")
        events.devices[1] = (socket, lambda: None, True)
        self.assertEqual(await events.to_device(1, self.event(64, "demo_movimiento")), "inhibido")
        self.assertEqual(await events.to_device(1, self.event(64)), "enviado_sin_ack")
        self.assertEqual(await events.to_device(1, self.event(0)), "enviado_sin_ack")
        self.assertTrue(events.dispatch_status(1)["demo_original_pendiente"])
        self.assertEqual(await events.to_device(1, self.event(1)), "inhibido")
        self.assertEqual(await events.to_device(1, self.event(128)), "enviado_sin_ack")
        self.assertFalse(events.dispatch_status(1)["demo_original_pendiente"])
        self.assertEqual([call.args[0]["codigo"] for call in socket.send_json.await_args_list], [64, 0, 128])

    async def test_original_is_rejected_before_sql_writes_when_inhibited(self):
        import asyncio

        app = SimpleNamespace(platform_lock=asyncio.Lock(), websocket_manager=PlatformEvents(
            dispatch=False, device_connections=False))
        request = SimpleNamespace(app=SimpleNamespace(state=app))
        with patch.object(operations, "command_code", return_value=64), patch.object(operations, "save_movement") as save:
            with self.assertRaises(HTTPException) as error:
                await operations.move(1, SimpleNamespace(id_comando=4), SimpleNamespace(key=b"fixture"), Mock(), request)
        self.assertEqual(error.exception.status_code, 409)
        save.assert_not_called()


class CatalogChangeTests(unittest.TestCase):
    def setUp(self):
        self.base = {code: (str(code), False) for code in BASE}
        self.expanded = self.base | {code: (name, False) for code, name in ADDITIONS.items()}

    def test_apply_only_inserts_two_rows_and_audits_then_noops(self):
        cursor = Mock()
        with patch("scripts.catalog43_hj2025.inventory", side_effect=[self.base, self.expanded]):
            change(cursor, "apply")
        cursor.executemany.assert_called_once()
        self.assertEqual(cursor.executemany.call_args.args[1], [(1, 64, "DEMO_ORIGINAL"), (1, 128, "CLAXON")])
        self.assertIn("INSERT INTO iot_auditoria", cursor.execute.call_args.args[0])
        cursor.reset_mock()
        with patch("scripts.catalog43_hj2025.inventory", return_value=self.expanded):
            change(cursor, "apply")
        self.assertEqual(cursor.mock_calls, [])

    def test_rollback_keeps_a_demo_using_horn(self):
        cursor = Mock()
        with patch("scripts.catalog43_hj2025.inventory", return_value=self.expanded), patch(
            "scripts.catalog43_hj2025.one", side_effect=[{"accion": "catalogo_hj2025_ampliado"}, {"id": 3}],
        ):
            with self.assertRaisesRegex(SystemExit, "Una DEMO depende"):
                change(cursor, "rollback")
        cursor.execute.assert_not_called()
