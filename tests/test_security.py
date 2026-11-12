"""API key local con ASGI real y servicios ficticios, sin .env ni RDS."""

from datetime import datetime
from hmac import compare_digest
import json
import logging
from types import SimpleNamespace
from typing import NamedTuple
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from pydantic import SecretStr

from app.config.settings import Settings, get_settings
from app.errors.handlers import register_exception_handlers
from app.execution.dependencies import get_demo_execution_manager
from app.models.commands import CommandResponse
from app.models.demo_execution import DemoExecutionResponse
from app.models.demos import DemoMovementResponse, DemoResponse
from app.models.movement import MovementRequest, MovementResponse
from app.models.vehicles import VehicleResponse
from app.routers import commands, demo_execution, demos, health, history, movement, state, vehicles
from app.services.commands import CommandService
from app.services.database_health import DatabaseHealthService
from app.services.demo_execution import DemoExecutionService
from app.services.demos import DemoMovementService, DemoService
from app.services.history import HistoryService
from app.services.movement import MovementService
from app.services.state import StateService
from app.services.vehicles import VehicleService
from app.websocket.publisher import get_movement_publisher


TEST_KEY = "ficticio-api-key-solo-pruebas-7e2c"
CONTROL_AND_DELETE_ROUTES = (
    ("POST", "/vehiculos/3/movimientos", {"id_comando": 7}, 200),
    ("POST", "/vehiculos/3/demos/5/ejecutar", None, 202),
    ("POST", "/vehiculos/3/demos/5/cancelar", None, 200),
    ("DELETE", "/vehiculos/3", None, 204),
    ("DELETE", "/vehiculos/3/comandos/7", None, 204),
    ("DELETE", "/vehiculos/3/demos/5", None, 204),
    ("DELETE", "/vehiculos/3/demos/5/movimientos/11", None, 204),
)


class AdministrativeRoute(NamedTuple):
    method: str
    path: str
    payload: dict
    status: int
    service: str
    action: str
    identifiers: tuple[int, ...]


ADMINISTRATIVE_ROUTES = (
    AdministrativeRoute("POST", "/vehiculos", {"nombre": "Vehículo ficticio"},
                        201, "vehicle", "create", ()),
    AdministrativeRoute("PUT", "/vehiculos/3", {"nombre": "Vehículo ficticio", "activo": False},
                        200, "vehicle", "update", (3,)),
    AdministrativeRoute("POST", "/vehiculos/3/comandos", {"nombre": "Comando ficticio", "codigo": 5},
                        201, "command", "create", (3,)),
    AdministrativeRoute("PUT", "/vehiculos/3/comandos/7",
                        {"nombre": "Comando ficticio", "codigo": 5, "activo": False},
                        200, "command", "update", (3, 7)),
    AdministrativeRoute("POST", "/vehiculos/3/demos", {"nombre": "DEMO ficticia"},
                        201, "demo", "create", (3,)),
    AdministrativeRoute("PUT", "/vehiculos/3/demos/5", {"nombre": "DEMO ficticia", "activo": False},
                        200, "demo", "update", (3, 5)),
    AdministrativeRoute("POST", "/vehiculos/3/demos/5/movimientos",
                        {"id_comando": 7, "orden": 2, "duracion_ms": 100},
                        201, "demo_movement", "create", (3, 5)),
    AdministrativeRoute("PUT", "/vehiculos/3/demos/5/movimientos/11",
                        {"id_comando": 7, "orden": 2, "duracion_ms": 100, "pausa_ms": 25},
                        200, "demo_movement", "update", (3, 5, 11)),
)
MUTATION_REQUESTS = CONTROL_AND_DELETE_ROUTES + tuple(
    (route.method, route.path, route.payload, route.status) for route in ADMINISTRATIVE_ROUTES
)


def fake_settings(key: str) -> Settings:
    return Settings(
        _env_file=None, app_name="API de pruebas", app_env="development",
        db_host="database.example.invalid", db_port=3306, db_name="security_test",
        db_user="test_user", db_password=SecretStr("db-ficticio-no-utilizable"),
        api_key=SecretStr(key),
    )


class SecurityHTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = fake_settings(TEST_KEY)
        self.service_resolutions = []
        self.application = FastAPI()
        for module in (health, vehicles, commands, state, history, movement, demos, demo_execution):
            self.application.include_router(module.router)
        register_exception_handlers(self.application)
        self.application.dependency_overrides[get_settings] = lambda: self.settings
        self.vehicle = Mock(spec=VehicleService)
        self.vehicle.list.return_value = []
        self.vehicle.get.return_value = VehicleResponse(
            id_vehiculo=3, nombre="Vehículo ficticio", modelo=None, descripcion=None,
            microcontrolador=None, fecha_registro=None, activo=True,
        )
        self.vehicle.create.return_value = self.vehicle.get.return_value
        self.vehicle.update.return_value = self.vehicle.get.return_value.model_copy(update={"activo": False})
        self.vehicle.delete.return_value = None
        self.command = Mock(spec=CommandService)
        self.command.list_for_vehicle.return_value = []
        self.command.create.return_value = CommandResponse(
            id_comando=7, id_vehiculo=3, nombre="Comando ficticio", codigo=5,
            descripcion=None, activo=True,
        )
        self.command.update.return_value = self.command.create.return_value.model_copy(update={"activo": False})
        self.command.delete.return_value = None
        self.demo = Mock(spec=DemoService)
        self.demo.list_for_vehicle.return_value = []
        self.demo.create.return_value = DemoResponse(
            id_demo=5, id_vehiculo=3, nombre="DEMO ficticia", descripcion=None, activo=True,
        )
        self.demo.update.return_value = self.demo.create.return_value.model_copy(update={"activo": False})
        self.demo.delete.return_value = None
        self.demo_movement = Mock(spec=DemoMovementService)
        self.demo_movement.list_for_demo.return_value = []
        self.demo_movement.create.return_value = DemoMovementResponse(
            id_demo_movimiento=11, orden=2, id_comando=7, comando="Comando ficticio",
            codigo=5, duracion_ms=100, pausa_ms=0,
        )
        self.demo_movement.update.return_value = self.demo_movement.create.return_value.model_copy(update={"pausa_ms": 25})
        self.demo_movement.delete.return_value = None
        self.state = Mock(spec=StateService)
        self.state.get.return_value = None
        self.history = Mock(spec=HistoryService)
        self.history.list_for_vehicle.return_value = []
        self.health = Mock(spec=DatabaseHealthService)
        self.health.check.return_value = None
        self.movement = Mock(spec=MovementService)
        self.movement.execute.return_value = MovementResponse(
            resultado="ok", id_vehiculo=3, id_comando=7, comando="REVERSA", codigo=-5,
            fecha_actualizacion=datetime(2026, 10, 14, 12, 30), conectado=False, origen="API",
        )
        self.publisher = SimpleNamespace(publish=AsyncMock())
        self.execution_service = Mock(spec=DemoExecutionService)
        self.execution_manager = SimpleNamespace(
            start=AsyncMock(return_value=DemoExecutionResponse(id_vehiculo=3, id_demo=5, estado="iniciada")),
            cancel=AsyncMock(return_value=DemoExecutionResponse(id_vehiculo=3, id_demo=5, estado="cancelada")),
        )
        overrides = {
            vehicles.get_vehicle_service: self.vehicle,
            commands.get_command_service: self.command,
            demos.get_demo_service: self.demo,
            demos.get_demo_movement_service: self.demo_movement,
            state.get_state_service: self.state,
            history.get_history_service: self.history,
            health.get_database_health_service: self.health,
            movement.get_movement_service: self.movement,
            get_movement_publisher: self.publisher,
            demo_execution.get_demo_execution_service: self.execution_service,
            get_demo_execution_manager: self.execution_manager,
        }
        for dependency, value in overrides.items():
            self.application.dependency_overrides[dependency] = self.provider(value)
        for target in ("app.config.settings.Settings", "app.database.connection.pymysql.connect"):
            guard = patch(target, side_effect=AssertionError("La prueba no puede cargar .env ni usar RDS."))
            guarded = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(guarded.assert_not_called)

    def provider(self, value):
        def dependency():
            self.service_resolutions.append(value)
            return value
        return dependency

    def business_mocks(self):
        return (
            self.vehicle, self.command, self.demo, self.demo_movement, self.state,
            self.history, self.health, self.movement, self.execution_service,
            self.publisher.publish, self.execution_manager.start, self.execution_manager.cancel,
        )

    def reset_business_mocks(self):
        self.service_resolutions.clear()
        for mock in self.business_mocks():
            mock.reset_mock()

    def assert_no_business_calls(self):
        self.assertEqual(self.service_resolutions, [])
        for mock in self.business_mocks():
            self.assertEqual(mock.mock_calls, [])

    async def request(self, method, path, payload=None, headers=()):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        response_messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            response_messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method, "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"application/json"), *((name.lower(), value) for name, value in headers)],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        start = next(message for message in response_messages if message["type"] == "http.response.start")
        self.response_headers = dict(start["headers"])
        content = b"".join(message.get("body", b"") for message in response_messages if message["type"] == "http.response.body")
        return start["status"], content

    async def test_all_mutations_require_header_and_skip_business_execution(self):
        for method, path, payload, _ in MUTATION_REQUESTS:
            with self.subTest(path=path, method=method):
                status, content = await self.request(method, path, payload)
                self.assertEqual(status, 401)
                self.assertTrue(self.response_headers[b"www-authenticate"].startswith(b"ApiKey"))
                self.assertEqual(set(json.loads(content)), {"detail"})
                self.assertNotIn(TEST_KEY.encode(), content)
        self.assert_no_business_calls()

    async def test_incorrect_and_present_empty_headers_are_403_on_all_mutations(self):
        for value in (b"incorrecta-ficticia", b""):
            for method, path, payload, _ in MUTATION_REQUESTS:
                with self.subTest(path=path, value=value):
                    status, content = await self.request(method, path, payload, [(b"x-api-key", value)])
                    self.assertEqual(status, 403)
                    self.assertEqual(set(json.loads(content)), {"detail"})
                    self.assertNotIn(TEST_KEY.encode(), content)
                    self.assertNotIn(b"incorrecta-ficticia", content)
        self.assert_no_business_calls()

    async def test_correct_key_preserves_control_and_delete_operations(self):
        for method, path, payload, expected in CONTROL_AND_DELETE_ROUTES:
            with self.subTest(path=path):
                self.reset_business_mocks()
                status, content = await self.request(method, path, payload, [(b"X-API-Key", TEST_KEY.encode())])
                self.assertEqual(status, expected)
                if method == "DELETE":
                    self.assertEqual(content, b"")
                elif path.endswith("/movimientos"):
                    self.assertEqual(json.loads(content)["resultado"], "ok")
                    self.movement.execute.assert_called_once()
                    self.publisher.publish.assert_awaited_once()
                elif path.endswith("/ejecutar"):
                    self.assertEqual(json.loads(content)["estado"], "iniciada")
                    self.execution_manager.start.assert_awaited_once_with(3, 5, self.execution_service)
                else:
                    self.assertEqual(json.loads(content)["estado"], "cancelada")
                    self.execution_manager.cancel.assert_awaited_once_with(3, 5)
                if method == "DELETE":
                    self.assertEqual(sum(mock.delete.call_count for mock in (self.vehicle, self.command, self.demo, self.demo_movement)), 1)

    async def test_correct_key_preserves_stop_response_and_publication(self):
        stop_response = self.movement.execute.return_value.model_copy(
            update={"id_comando": 1, "comando": "DETENER", "codigo": 0},
        )
        self.movement.execute.return_value = stop_response
        status, content = await self.request(
            "POST", "/vehiculos/3/movimientos", {"id_comando": 1}, [(b"x-api-key", TEST_KEY.encode())],
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), stop_response.model_dump(mode="json"))
        self.movement.execute.assert_called_once_with(3, MovementRequest(id_comando=1))
        self.publisher.publish.assert_awaited_once_with(stop_response)

    async def test_correct_key_preserves_all_eight_administrative_contracts(self):
        for route in ADMINISTRATIVE_ROUTES:
            with self.subTest(method=route.method, path=route.path):
                self.reset_business_mocks()
                service = getattr(self, route.service)
                action = getattr(service, route.action)
                status, content = await self.request(
                    route.method, route.path, route.payload, [(b"x-api-key", TEST_KEY.encode())],
                )
                self.assertEqual(status, route.status)
                self.assertEqual(json.loads(content), action.return_value.model_dump(mode="json"))
                self.assertEqual(self.service_resolutions, [service])
                self.assertEqual(sum(len(mock.mock_calls) for mock in self.business_mocks()), 1)
                action.assert_called_once()
                args, kwargs = action.call_args
                self.assertEqual(kwargs, {})
                self.assertEqual(args[:-1], route.identifiers)
                self.assertEqual(args[-1].model_dump(exclude_unset=True), route.payload)

    async def test_local_simulation_blocks_legacy_actuation_after_administrative_auth(self):
        self.application.state.public_control_simulation = True
        for method, path, payload, _ in CONTROL_AND_DELETE_ROUTES[:3]:
            with self.subTest(path=path):
                status, _ = await self.request(method, path, payload)
                self.assertEqual(status, 401)
                status, content = await self.request(
                    method, path, payload, [(b"x-api-key", TEST_KEY.encode())],
                )
                self.assertEqual(status, 503)
                self.assertIn("simulación", json.loads(content)["detail"])
        self.assert_no_business_calls()

    async def test_guest_bearer_cannot_authorize_any_existing_write(self):
        guest_header = [(b"authorization", b"Bearer " + b"A" * 43)]
        for method, path, payload, _ in MUTATION_REQUESTS:
            with self.subTest(method=method, path=path):
                status, _ = await self.request(method, path, payload, guest_header)
                self.assertEqual(status, 401)
        self.assert_no_business_calls()

    async def test_duplicate_headers_are_rejected_even_when_both_values_are_correct(self):
        for values in ((TEST_KEY.encode(), TEST_KEY.encode()), (TEST_KEY.encode(), b"incorrecta")):
            for method, path, payload, _ in MUTATION_REQUESTS:
                with self.subTest(path=path, values=values):
                    status, _ = await self.request(method, path, payload, [(b"x-api-key", value) for value in values])
                    self.assertEqual(status, 403)
        self.assert_no_business_calls()

    async def test_non_ascii_and_whitespace_candidates_fail_safely_without_normalization(self):
        for value in (b"\xff", b" ", b" " + TEST_KEY.encode(), TEST_KEY.encode() + b" "):
            with self.subTest(value=value):
                status, content = await self.request("DELETE", "/vehiculos/3", headers=[(b"x-api-key", value)])
                self.assertEqual(status, 403)
                self.assertNotIn(TEST_KEY.encode(), content)
        self.assert_no_business_calls()

    async def test_missing_or_placeholder_server_configuration_fails_closed_before_business_calls(self):
        for key in ("", "   ", "change-me", "changeme"):
            self.settings = fake_settings(key)
            for method, path, payload, _ in MUTATION_REQUESTS:
                with self.subTest(configured=key, path=path):
                    status, content = await self.request(method, path, payload, [(b"x-api-key", TEST_KEY.encode())])
                    self.assertEqual(status, 503)
                    self.assertNotIn(TEST_KEY.encode(), content)
                    self.assertNotIn(b"change-me", content)
        self.assert_no_business_calls()

    async def test_public_gets_remain_accessible_without_key_even_when_not_configured(self):
        self.settings = fake_settings("")
        paths = (
            "/", "/health/database", "/vehiculos", "/vehiculos/3", "/vehiculos/3/comandos",
            "/vehiculos/3/estado", "/vehiculos/3/historial", "/vehiculos/3/demos",
            "/vehiculos/3/demos/5/movimientos", "/docs", "/openapi.json",
        )
        for path in paths:
            with self.subTest(path=path):
                status, _ = await self.request("GET", path)
                self.assertEqual(status, 200)

    async def test_openapi_applies_header_scheme_to_all_mutations(self):
        schema = self.application.openapi()
        scheme = schema["components"]["securitySchemes"]["LocalApiKey"]
        self.assertEqual({name: scheme[name] for name in ("type", "in", "name")}, {
            "type": "apiKey", "in": "header", "name": "X-API-Key",
        })
        secured_count = 0
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                with self.subTest(path=path, method=method):
                    if method not in {"post", "put", "delete"}:
                        self.assertFalse(operation.get("security"))
                        continue
                    secured_count += 1
                    self.assertEqual(operation["security"], [{"LocalApiKey": []}])
                    responses = operation["responses"]
                    self.assertTrue({"401", "403", "503"}.issubset(responses))
                    self.assertIn("WWW-Authenticate", responses["401"]["headers"])
        self.assertEqual(secured_count, 15)
        self.assert_no_business_calls()

    async def test_administrative_credentials_are_not_exposed_in_responses_or_logs(self):
        incorrect_key = b"credencial-incorrecta-solo-pruebas"
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger(__name__).debug("Comprobación de registro de autorización")
            for value, expected in ((incorrect_key, 403), (TEST_KEY.encode(), 201)):
                status, content = await self.request(
                    "POST", "/vehiculos", {"nombre": "Vehículo ficticio"}, [(b"x-api-key", value)],
                )
                self.assertEqual(status, expected)
                self.assertNotIn(incorrect_key, content)
                self.assertNotIn(TEST_KEY.encode(), content)
        self.assertNotIn(incorrect_key.decode(), "\n".join(logs.output))
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))

    async def test_authorization_uses_constant_time_comparison_of_bytes(self):
        with patch("app.security.api_key.compare_digest", wraps=compare_digest) as compare:
            status, _ = await self.request("DELETE", "/vehiculos/3", headers=[(b"x-api-key", TEST_KEY.encode())])
            self.assertEqual(status, 204)
            compare.assert_called_once_with(TEST_KEY.encode("utf-8"), TEST_KEY.encode("utf-8"))
            self.reset_business_mocks()
            compare.reset_mock()
            status, _ = await self.request("DELETE", "/vehiculos/3", headers=[(b"x-api-key", b"\xff")])
            self.assertEqual(status, 403)
            compare.assert_called_once_with("ÿ".encode("utf-8"), TEST_KEY.encode("utf-8"))
            self.assert_no_business_calls()

    def test_configured_api_key_is_not_exposed_by_settings_representation(self):
        self.assertNotIn(TEST_KEY, repr(self.settings))
        self.assertNotIn(TEST_KEY, str(self.settings))
        self.assertEqual(Settings.model_fields["api_key"].default.get_secret_value(), "")


if __name__ == "__main__":
    unittest.main()
