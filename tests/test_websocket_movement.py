"""POST simulado, transacción real de Python y publicación WS después del commit."""

from copy import deepcopy
import json
from threading import get_ident
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
import pymysql

from app.dependencies import get_database
from app.errors.handlers import register_exception_handlers
from app.models.movement import MovementResponse
from app.routers.movement import router
from app.security.api_key import require_api_key
from app.websocket.events import MovementEvent
from app.websocket.manager import WebSocketManager

# unittest discover -s tests incorpora esa carpeta a sys.path. Importar el
# módulo evita descubrir otra vez sus clases TestCase en este archivo.
import test_movement as movement_tests


class ObservedSocket:
    """Cliente en memoria que observa la transacción al recibir cada movimiento."""

    def __init__(self, connection) -> None:
        self.connection = connection
        self.accepted = 0
        self.messages = []
        self.observations = []
        self.close_calls = []
        self.fail_movement = False
        self.movement_attempts = 0

    async def accept(self, **_kwargs):
        self.accepted += 1

    async def send_json(self, event, **_kwargs):
        if event.get("tipo_evento") == "movimiento":
            self.movement_attempts += 1
            if self.fail_movement:
                raise OSError("Fallo de envío ficticio")
            self.observations.append({
                "commits": self.connection.commits,
                "closed": self.connection.closed,
                "thread": get_ident(),
            })
            self.connection.events.append(("websocket_send",))
        # La copia/serialización también detecta datetime sin convertir a JSON.
        self.messages.append(json.loads(json.dumps(event)))

    async def close(self, code=1000, reason=""):
        self.close_calls.append((code, reason))


class MovementWebSocketTests(movement_tests.MovementFixture, unittest.IsolatedAsyncioTestCase):
    """Sin app.main, .env, red ni escrituras en MySQL; sin nuevos paquetes."""

    def setUp(self):
        super().setUp()
        self.manager = WebSocketManager()
        self.application = FastAPI()
        self.application.state.websocket_manager = self.manager
        self.application.include_router(router)
        register_exception_handlers(self.application)
        self.application.dependency_overrides[get_database] = lambda: self.database
        self.application.dependency_overrides[require_api_key] = lambda: None
        self.addAsyncCleanup(self.manager.close_all)
        # MovementFixture crea Settings(_env_file=None) con datos ficticios.
        # Ninguna dependencia HTTP debe volver a cargar Settings desde .env.
        settings_patch = patch(
            "app.config.settings.Settings",
            side_effect=AssertionError("Estas pruebas no pueden cargar .env."),
        )
        self.settings_guard = settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def tearDown(self):
        self.settings_guard.assert_not_called()

    async def subscribe(self, vehicle_id=3):
        socket = ObservedSocket(self.connection)

        async def initial_event():
            return {
                "tipo_evento": "estado_actual",
                "id_vehiculo": vehicle_id,
                "comando": None,
                "codigo": None,
                "timestamp": None,
            }

        await self.manager.connect(vehicle_id, socket, initial_event)
        self.assertEqual(socket.accepted, 1)
        self.assertEqual(len(socket.messages), 1)
        socket.messages.clear()
        return socket

    async def request_movement(self, command_id=7):
        body = json.dumps({"id_comando": command_id}).encode("utf-8")
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        path = "/vehiculos/3/movimientos"
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        response = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(
            item.get("body", b"") for item in messages if item["type"] == "http.response.body"
        )
        return response["status"], json.loads(content)

    async def reset_transaction_and_manager(self):
        await self.manager.close_all()
        self.connection = movement_tests.MovementConnection()
        self.connect.return_value = self.connection
        self.manager = WebSocketManager()
        self.application.state.websocket_manager = self.manager
        self.addAsyncCleanup(self.manager.close_all)

    async def test_broadcast_occurs_once_after_commit_and_close_only_for_matching_vehicle(self):
        loop_thread = get_ident()
        database_threads = []

        def connect_fake(**_kwargs):
            database_threads.append(get_ident())
            return self.connection

        self.connect.side_effect = connect_fake
        first = await self.subscribe(3)
        second = await self.subscribe(3)
        other = await self.subscribe(4)
        with patch.object(self.manager, "broadcast", wraps=self.manager.broadcast) as broadcast:
            status, response = await self.request_movement()

        self.assertEqual(status, 200)
        self.assertEqual(response["resultado"], "ok")
        broadcast.assert_awaited_once()
        self.assertEqual(broadcast.await_args.args[0], 3)
        self.assertEqual(len(first.messages), 1)
        self.assertEqual(second.messages, first.messages)
        self.assertEqual(other.messages, [])
        self.assertEqual(first.messages[0], {
            "tipo_evento": "movimiento",
            "id_vehiculo": 3,
            "id_comando": 7,
            "comando": "REVERSA",
            "codigo": -5,
            "timestamp": movement_tests.DATABASE_TIMESTAMP.isoformat(),
            "conectado": False,
            "origen": "API",
        })
        for socket in (first, second):
            self.assertEqual(socket.observations, [{
                "commits": 1, "closed": 1, "thread": loop_thread,
            }])
        self.assertEqual(len(database_threads), 1)
        self.assertNotEqual(database_threads[0], loop_thread)
        events = self.connection.events
        self.assertLess(events.index(("commit",)), events.index(("close",)))
        self.assertLess(events.index(("close",)), events.index(("websocket_send",)))
        self.assertEqual((self.connection.commits, self.connection.rollbacks), (1, 0))
        self.assertEqual(len(self.connection.history), len(self.original_history) + 1)

    async def test_sp_result_or_commit_failure_rolls_back_without_a_websocket_event(self):
        for failure in ("state", "history", "history_drain", "commit"):
            with self.subTest(failure=failure):
                await self.reset_transaction_and_manager()
                socket = await self.subscribe()
                error = pymysql.OperationalError(1644, "DETALLE_INTERNO_FICTICIO")
                if failure == "state":
                    self.connection.failures[("call", "sp_actualizar_estado", 1)] = error
                elif failure == "history":
                    self.connection.failures[("call", "sp_registrar_historial", 1)] = error
                elif failure == "history_drain":
                    self.connection.failures[("drain", "sp_registrar_historial", 1)] = error
                else:
                    self.connection.commit_error = pymysql.OperationalError(
                        2013, "DETALLE_INTERNO_FICTICIO"
                    )
                with patch.object(self.manager, "broadcast", wraps=self.manager.broadcast) as broadcast:
                    status, response = await self.request_movement()

                self.assertEqual(status, 503 if failure == "commit" else 500)
                self.assertEqual(set(response), {"detail"})
                self.assertNotIn("DETALLE_INTERNO_FICTICIO", json.dumps(response))
                broadcast.assert_not_awaited()
                self.assertEqual(socket.messages, [])
                self.assertEqual(socket.movement_attempts, 0)
                self.assertEqual(self.manager.connection_count(3), 1)
                self.assert_reverted_and_closed()

    async def test_no_subscribers_still_returns_http_200_and_confirms_once(self):
        status, response = await self.request_movement()
        self.assertEqual(status, 200)
        self.assertEqual(response["resultado"], "ok")
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)
        self.assertEqual((self.connection.commit_attempts, self.connection.commits), (1, 1))
        self.assertEqual(self.connection.rollbacks, 0)
        self.assertEqual(len(self.connection.history), len(self.original_history) + 1)
        self.connect.assert_called_once()

    async def test_failed_client_is_removed_while_other_client_receives_committed_movement(self):
        broken = await self.subscribe(3)
        healthy = await self.subscribe(3)
        other_vehicle = await self.subscribe(4)
        broken.fail_movement = True

        status, response = await self.request_movement()

        self.assertEqual(status, 200)
        self.assertEqual(response["resultado"], "ok")
        self.assertEqual(broken.messages, [])
        self.assertEqual(broken.movement_attempts, 1)
        self.assertEqual(len(healthy.messages), 1)
        self.assertEqual(other_vehicle.messages, [])
        self.assertEqual(self.manager.connection_count(3), 1)
        self.assertEqual(self.manager.connection_count(4), 1)
        self.assertEqual(healthy.observations[0]["commits"], 1)
        self.assertEqual(healthy.observations[0]["closed"], 1)
        self.assertEqual((self.connection.commits, self.connection.rollbacks), (1, 0))
        self.assertEqual(len(self.connection.history), len(self.original_history) + 1)

    async def test_unexpected_broadcast_failure_never_retries_or_changes_committed_http_result(self):
        socket = await self.subscribe()
        with patch.object(
            self.manager, "broadcast",
            new=AsyncMock(side_effect=RuntimeError("DETALLE_INTERNO_FICTICIO")),
        ) as broadcast, self.assertLogs("app.websocket.publisher", level="WARNING") as logs:
            status, response = await self.request_movement()

        self.assertEqual(status, 200)
        self.assertEqual(response["resultado"], "ok")
        self.assertEqual(socket.messages, [])
        broadcast.assert_awaited_once()
        self.connect.assert_called_once()
        self.assertEqual((self.connection.commit_attempts, self.connection.commits), (1, 1))
        self.assertEqual(self.connection.rollbacks, 0)
        self.assertEqual(self.connection.closed, 1)
        self.assertEqual(len(self.connection.history), len(self.original_history) + 1)
        self.assertNotIn("DETALLE_INTERNO_FICTICIO", "\n".join(logs.output))

    async def test_nullable_database_timestamp_is_preserved_in_json_event(self):
        self.connection.generated_timestamp = None
        socket = await self.subscribe()

        status, response = await self.request_movement()

        self.assertEqual(status, 200)
        self.assertIsNone(response["fecha_actualizacion"])
        self.assertEqual(len(socket.messages), 1)
        self.assertIn("timestamp", socket.messages[0])
        self.assertIsNone(socket.messages[0]["timestamp"])
        self.assertEqual(socket.observations[0]["commits"], 1)

    def test_movement_event_uses_committed_response_without_mutating_it(self):
        response = MovementResponse(
            resultado="ok", id_vehiculo=3, id_comando=7, comando="REVERSA", codigo=-5,
            fecha_actualizacion=movement_tests.DATABASE_TIMESTAMP, conectado=False, origen="API",
        )
        before = deepcopy(response.model_dump())

        event = MovementEvent.from_movement(response).model_dump(mode="json")

        self.assertEqual(event, {
            "tipo_evento": "movimiento", "id_vehiculo": 3, "id_comando": 7,
            "comando": "REVERSA", "codigo": -5,
            "timestamp": movement_tests.DATABASE_TIMESTAMP.isoformat(),
            "conectado": False, "origen": "API",
        })
        self.assertEqual(response.model_dump(), before)
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
