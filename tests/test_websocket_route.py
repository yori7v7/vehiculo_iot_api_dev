"""Ruta WebSocket ASGI en memoria, con manager real y sin clientes ni RDS."""

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, WebSocketDisconnect
from starlette.requests import HTTPConnection

from app.errors.database import (
    DatabaseConfigurationError,
    DatabaseError,
    DatabaseResultError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.domain import ResourceNotFoundError
from app.models.state import StateResponse
from app.routers.state import get_state_service
from app.services.state import StateService
from app.websocket.dependencies import get_websocket_manager
from app.websocket.manager import WebSocketManager
from app.websocket.router import router


def state_for_test(vehicle_id=3, **changes):
    values = {
        "id_vehiculo": vehicle_id, "vehiculo": "Vehículo simulado",
        "id_comando": 1, "comando": "DETENER", "codigo": 0,
        "conectado": False, "fecha_actualizacion": datetime(2026, 10, 14, 10, 20, 30),
    }
    values.update(changes)
    return StateResponse(**values)


class ASGIWebSocketSession:
    """Conectar la aplicación directamente mediante colas de mensajes ASGI."""

    def __init__(self, application, path, *, fail_send=None):
        self.application = application
        self.path = path
        self.fail_send = fail_send
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.sent = []
        self.task = None

    async def start(self):
        scope = {
            "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "scheme": "ws", "path": self.path,
            "raw_path": self.path.encode("utf-8"), "root_path": "", "query_string": b"",
            "headers": [], "subprotocols": [],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(self.application(scope, self.receive, self.send))

    async def receive(self):
        message = await self.incoming.get()
        if isinstance(message, BaseException):
            raise message
        return message

    async def send(self, message):
        if message["type"] == self.fail_send:
            raise RuntimeError("detalle privado del envío simulado")
        self.sent.append(deepcopy(message))
        self.outgoing.put_nowait(deepcopy(message))

    async def next_message(self):
        return await asyncio.wait_for(self.outgoing.get(), timeout=1.0)

    async def initial_event(self):
        accepted = await self.next_message()
        if accepted["type"] != "websocket.accept":
            raise AssertionError(f"Se esperaba accept, se recibió {accepted}")
        event = await self.next_message()
        if event["type"] != "websocket.send":
            raise AssertionError(f"Se esperaba el estado inicial, se recibió {event}")
        return json.loads(event["text"])

    async def disconnect(self, code=1000):
        if self.task is not None and not self.task.done():
            self.incoming.put_nowait({"type": "websocket.disconnect", "code": code})
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=1.0)


class WebSocketDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_manager_is_reused_for_the_same_application(self):
        application = FastAPI()
        first = await get_websocket_manager(HTTPConnection({"type": "http", "app": application}))
        second = await get_websocket_manager(HTTPConnection({"type": "websocket", "app": application}))
        self.assertIsInstance(first, WebSocketManager)
        self.assertIs(first, second)
        self.assertIs(application.state.websocket_manager, first)
        await first.close_all()

    async def test_existing_application_manager_is_reused(self):
        application = FastAPI()
        manager = WebSocketManager()
        application.state.websocket_manager = manager
        dependency = await get_websocket_manager(HTTPConnection({"type": "http", "app": application}))
        self.assertIs(dependency, manager)
        await manager.close_all()

    async def test_different_applications_get_independent_managers(self):
        first = await get_websocket_manager(HTTPConnection({"type": "http", "app": FastAPI()}))
        second = await get_websocket_manager(HTTPConnection({"type": "http", "app": FastAPI()}))
        self.assertIsNot(first, second)
        await first.close_all()
        await second.close_all()


class WebSocketRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.application = FastAPI()
        self.application.include_router(router)
        self.service = Mock(spec=StateService)
        self.service.get.return_value = state_for_test()
        self.application.dependency_overrides[get_state_service] = lambda: self.service
        self.manager = WebSocketManager(send_timeout=0.25, close_timeout=0.25)
        self.application.state.websocket_manager = self.manager
        self.sessions = []
        self.connection_patch = patch(
            "app.database.connection.pymysql.connect",
            side_effect=AssertionError("Estas pruebas no pueden conectarse a RDS."),
        )
        self.connection_guard = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.settings_patch = patch(
            "app.config.settings.Settings",
            side_effect=AssertionError("Estas pruebas no pueden cargar .env."),
        )
        self.settings_guard = self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    async def asyncTearDown(self):
        try:
            for session in self.sessions:
                await session.disconnect()
            await self.manager.close_all()
        finally:
            self.connection_guard.assert_not_called()
            self.settings_guard.assert_not_called()

    async def open_session(self, vehicle_id="3", **kwargs):
        session = ASGIWebSocketSession(self.application, f"/ws/vehiculos/{vehicle_id}", **kwargs)
        self.sessions.append(session)
        await session.start()
        return session

    async def assert_rejected(self, session, code, reason, *, empty_manager=True):
        message = await session.next_message()
        self.assertEqual(message, {"type": "websocket.close", "code": code, "reason": reason})
        await asyncio.wait_for(session.task, timeout=1.0)
        self.assertNotIn("websocket.accept", [value["type"] for value in session.sent])
        if empty_manager:
            self.assertEqual(self.manager.vehicle_count, 0)

    async def test_valid_connection_sends_current_persisted_state_then_registers(self):
        session = await self.open_session()
        event = await session.initial_event()
        self.assertEqual(event, {
            "tipo_evento": "estado_actual", "id_vehiculo": 3,
            "comando": "DETENER", "codigo": 0, "timestamp": "2026-10-14T10:20:30",
            "estado": self.service.get.return_value.model_dump(mode="json"),
        })
        self.service.get.assert_called_once_with(3)
        self.assertEqual(self.manager.connection_count(3), 1)
        await session.disconnect()
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_existing_vehicle_without_state_sends_nullable_initial_event(self):
        self.service.get.return_value = None
        session = await self.open_session()
        self.assertEqual(await session.initial_event(), {
            "tipo_evento": "estado_actual", "id_vehiculo": 3,
            "comando": None, "codigo": None, "timestamp": None, "estado": None,
        })
        self.assertEqual(self.manager.connection_count(3), 1)

    async def test_missing_vehicle_is_rejected_before_accept_with_static_reason(self):
        self.service.get.side_effect = ResourceNotFoundError("detalle privado que no debe exponerse")
        session = await self.open_session()
        await self.assert_rejected(session, 1008, "El vehículo no existe.")
        self.service.get.assert_called_once_with(3)

    async def test_invalid_identifiers_are_rejected_without_database_read(self):
        for value in ("0", "-1", "+1", "1.0", "abc", "2147483648", " 1", "１", "9" * 1000):
            with self.subTest(value=value):
                session = await self.open_session(value)
                await self.assert_rejected(session, 1008, "El identificador del vehículo no es válido.")
        self.service.get.assert_not_called()

    async def test_maximum_signed_integer_identifier_is_supported(self):
        self.service.get.return_value = state_for_test(vehicle_id=2147483647)
        session = await self.open_session("2147483647")
        event = await session.initial_event()
        self.assertEqual(event["id_vehiculo"], 2147483647)
        self.service.get.assert_called_once_with(2147483647)

    async def test_database_errors_close_1011_without_exposing_internal_details(self):
        for error_type in (
            DatabaseError, DatabaseConfigurationError, DatabaseUnavailableError,
            DatabaseTransactionError, StoredProcedureExecutionError, DatabaseResultError,
        ):
            with self.subTest(error_type=error_type.__name__):
                error = error_type()
                error.args = ("detalle privado de credenciales y conexión",)
                self.service.get.side_effect = error
                session = await self.open_session()
                await self.assert_rejected(session, 1011, "No fue posible consultar el estado del vehículo.")

    async def test_unexpected_initial_load_failure_is_closed_without_hanging(self):
        self.service.get.side_effect = RuntimeError("detalle privado inesperado")
        session = await self.open_session()
        await self.assert_rejected(session, 1011, "No fue posible mantener la conexión WebSocket.")

    async def test_initial_send_failure_leaves_no_subscription_or_pending_route(self):
        session = await self.open_session(fail_send="websocket.send")
        accepted = await session.next_message()
        self.assertEqual(accepted["type"], "websocket.accept")
        closed = await session.next_message()
        self.assertEqual(closed["type"], "websocket.close")
        self.assertEqual(closed["code"], 1011)
        self.assertNotIn("detalle privado", closed.get("reason", ""))
        await asyncio.wait_for(session.task, timeout=1.0)
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_accept_failure_cleans_up_without_waiting_for_client_messages(self):
        session = await self.open_session(fail_send="websocket.accept")
        closed = await session.next_message()
        self.assertEqual(closed["type"], "websocket.close")
        self.assertEqual(closed["code"], 1011)
        await asyncio.wait_for(session.task, timeout=1.0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_unexpected_receive_failure_removes_subscription(self):
        session = await self.open_session()
        await session.initial_event()
        session.incoming.put_nowait(RuntimeError("detalle privado de recepción"))
        closed = await session.next_message()
        self.assertEqual(closed, {
            "type": "websocket.close", "code": 1011,
            "reason": "No fue posible mantener la conexión WebSocket.",
        })
        await asyncio.wait_for(session.task, timeout=1.0)
        self.assertEqual(self.manager.connection_count(3), 0)

    async def test_websocket_disconnect_exception_also_removes_subscription(self):
        session = await self.open_session()
        await session.initial_event()
        session.incoming.put_nowait(WebSocketDisconnect(code=1006))
        await asyncio.wait_for(session.task, timeout=1.0)
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_client_messages_do_not_execute_actions_or_write_connected_state(self):
        session = await self.open_session()
        await session.initial_event()
        original_state = self.service.get.return_value.model_dump()
        session.incoming.put_nowait({
            "type": "websocket.receive",
            "text": '{"id_comando":99,"conectado":true,"origen":"API"}',
        })
        session.incoming.put_nowait({"type": "websocket.receive", "bytes": b"arbitrary bytes"})
        await session.disconnect()
        self.assertEqual(sum(message["type"] == "websocket.send" for message in session.sent), 1)
        self.assertEqual(sum(message["type"] == "websocket.accept" for message in session.sent), 1)
        self.service.get.assert_called_once_with(3)
        self.assertEqual(self.service.get.return_value.model_dump(), original_state)

    async def test_reconnect_reads_a_new_snapshot_without_retaining_old_socket(self):
        first = await self.open_session()
        await first.initial_event()
        await first.disconnect()
        self.service.get.return_value = state_for_test(id_comando=2, comando="AVANZAR", codigo=1)
        second = await self.open_session()
        event = await second.initial_event()
        self.assertEqual(event["comando"], "AVANZAR")
        self.assertEqual(event["codigo"], 1)
        self.assertEqual(self.service.get.call_count, 2)
        self.assertEqual(self.manager.connection_count(3), 1)

    async def test_registered_route_receives_broadcasts_only_for_its_vehicle(self):
        self.service.get.side_effect = lambda vehicle_id: state_for_test(vehicle_id=vehicle_id)
        first = await self.open_session("3")
        second = await self.open_session("4")
        await first.initial_event()
        await second.initial_event()
        event = {"tipo_evento": "movimiento", "id_vehiculo": 3, "codigo": 1}
        await self.manager.broadcast(3, event)
        self.assertEqual(json.loads((await first.next_message())["text"]), event)
        self.assertEqual(len(second.sent), 2)

    async def test_synchronous_state_read_runs_off_event_loop_and_other_route_remains_responsive(self):
        entered = threading.Event()
        release = threading.Event()
        worker_ids = []
        main_thread = threading.get_ident()

        def slow_read(vehicle_id):
            worker_ids.append(threading.get_ident())
            entered.set()
            release.wait(timeout=1.0)
            return state_for_test(vehicle_id=vehicle_id)

        self.service.get.side_effect = slow_read
        first = await self.open_session()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.005)
            self.assertTrue(entered.is_set())
            self.assertNotEqual(worker_ids, [main_thread])
            invalid = await self.open_session("0")
            await self.assert_rejected(
                invalid, 1008, "El identificador del vehículo no es válido.", empty_manager=False
            )
            self.assertFalse(release.is_set())
        finally:
            release.set()
        await first.initial_event()
        self.assertEqual(self.manager.connection_count(3), 1)


if __name__ == "__main__":
    unittest.main()
