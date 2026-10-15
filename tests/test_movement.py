"""Movimiento con routers, repositorios, ejecutor y transacción reales sin red."""

from copy import deepcopy
from datetime import datetime
import json
import ssl
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from pydantic import ValidationError
import pymysql

from app.config.settings import Settings
from app.database.connection import MySQLDatabase
from app.dependencies import get_database
from app.errors.database import (
    DatabaseConflictError,
    DatabaseResultError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.errors.handlers import register_exception_handlers
from app.models.common import INT_MAX
from app.models.movement import MovementRequest
from app.routers.movement import router
from app.services.movement import MovementService
from app.security.api_key import require_api_key


DATABASE_TIMESTAMP = datetime(2026, 10, 14, 12, 30, 45)
INITIAL_TIMESTAMP = datetime(2026, 10, 13, 8, 0, 0)


class MovementCursor:
    """Distinguir sets tabulares y terminales CALL, con errores de drenaje."""

    def __init__(self, connection):
        self.connection = connection
        self.result_sets = [None]
        self.index = 0
        self.procedure = None
        self.occurrence = 0
        self.drained = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def callproc(self, procedure, parameters):
        self.procedure = procedure
        self.connection.calls.append((procedure, tuple(parameters)))
        self.connection.events.append(("call", procedure))
        self.occurrence = sum(name == procedure for name, _ in self.connection.calls)
        error = self.connection.failures.get(("call", procedure, self.occurrence))
        if error is not None:
            raise error
        result = self.connection.run_procedure(procedure, tuple(parameters))
        self.result_sets = [result, None] if result is not None else [None]

    @property
    def description(self):
        return (("column",),) if self.result_sets[self.index] is not None else None

    def fetchall(self):
        return deepcopy(self.result_sets[self.index])

    def nextset(self):
        error = self.connection.failures.get(("drain", self.procedure, self.occurrence))
        if error is not None:
            raise error
        if self.index + 1 < len(self.result_sets):
            self.index += 1
            return True
        self.drained = True
        return None


class MovementConnection:
    """Modelo transaccional de los cinco SP usados, con estado persistido aparte."""

    def __init__(self):
        self.vehicle = {
            "id_vehiculo": 3, "nombre": "Vehículo simulado", "modelo": None,
            "descripcion": None, "microcontrolador": None, "fecha_registro": None,
            "activo": 1,
        }
        self.commands = [
            {"id_comando": 1, "id_vehiculo": 3, "nombre": "DETENER", "codigo": 0,
             "descripcion": None, "activo": 1},
            {"id_comando": 7, "id_vehiculo": 3, "nombre": "REVERSA", "codigo": -5,
             "descripcion": None, "activo": 1},
            {"id_comando": 8, "id_vehiculo": 4, "nombre": "OTRO", "codigo": 10,
             "descripcion": None, "activo": 1},
        ]
        self.state = {
            "id_vehiculo": 3, "id_comando": 1,
            "fecha_actualizacion": INITIAL_TIMESTAMP, "conectado": 0,
        }
        self.history = [{"id_vehiculo": 3, "id_comando": 1, "origen": "MANUAL"}]
        self.working_state = None
        self.working_history = []
        self.calls = []
        self.cursors = []
        self.events = []
        self.failures = {}
        self.state_overrides = {}
        self.command_rows_override = None
        self.generated_timestamp = DATABASE_TIMESTAMP
        self.begin_count = 0
        self.commit_attempts = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.commit_error = None

    def begin(self):
        self.begin_count += 1
        self.events.append(("begin",))
        self.working_state = deepcopy(self.state)
        self.working_history = deepcopy(self.history)

    def commit(self):
        self.commit_attempts += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.state = deepcopy(self.working_state)
        self.history = deepcopy(self.working_history)
        self.commits += 1
        self.events.append(("commit",))

    def rollback(self):
        self.rollbacks += 1
        self.working_state = deepcopy(self.state)
        self.working_history = deepcopy(self.history)
        self.events.append(("rollback",))

    def close(self):
        self.closed += 1
        self.events.append(("close",))

    def cursor(self):
        if self.cursors and not self.cursors[-1].drained:
            raise AssertionError("El CALL anterior debe drenar todos sus result sets.")
        cursor = MovementCursor(self)
        self.cursors.append(cursor)
        return cursor

    def state_result(self):
        if self.working_state is None:
            return []
        value = deepcopy(self.working_state)
        command = next(
            (item for item in self.commands if item["id_comando"] == value["id_comando"]),
            None,
        )
        value.update(
            vehiculo=self.vehicle["nombre"],
            comando=command["nombre"] if command else None,
            codigo=command["codigo"] if command else None,
        )
        return [value]

    def run_procedure(self, name, parameters):
        if name == "sp_obtener_vehiculo":
            (vehicle_id,) = parameters
            return [deepcopy(self.vehicle)] if self.vehicle is not None else []
        if name == "sp_obtener_comandos_vehiculo":
            (vehicle_id,) = parameters
            if self.command_rows_override is not None:
                return deepcopy(self.command_rows_override)
            return deepcopy([value for value in self.commands if value["id_vehiculo"] == vehicle_id])
        if name == "sp_obtener_estado":
            (vehicle_id,) = parameters
            occurrence = sum(procedure == name for procedure, _ in self.calls)
            if occurrence in self.state_overrides:
                return deepcopy(self.state_overrides[occurrence])
            return self.state_result()
        if name == "sp_actualizar_estado":
            vehicle_id, command_id, connected = parameters
            self.working_state = {
                "id_vehiculo": vehicle_id, "id_comando": command_id,
                "fecha_actualizacion": self.generated_timestamp, "conectado": int(connected),
            }
            return None
        if name == "sp_registrar_historial":
            vehicle_id, command_id, origin = parameters
            self.working_history.append(
                {"id_vehiculo": vehicle_id, "id_comando": command_id, "origen": origin}
            )
            return None
        raise AssertionError(f"SP no permitido en movimiento: {name}")


class MovementFixture:
    """MySQLDatabase conserva su contexto real; sólo TLS y connect son dobles."""

    def setUp(self):
        self.connection = MovementConnection()
        settings = Settings(
            _env_file=None,
            db_host="database.example.invalid", db_name="movement_test",
            db_user="test_user", db_password="test-only-nonfunctional",
            db_ssl_ca="tests/fake-ca.pem",
        )
        self.tls_patch = patch(
            "app.database.connection.ssl.create_default_context",
            return_value=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        self.tls_patch.start()
        self.addCleanup(self.tls_patch.stop)
        self.connect_patch = patch(
            "app.database.connection.pymysql.connect", return_value=self.connection
        )
        self.connect = self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.database = MySQLDatabase(settings)
        self.service = MovementService(self.database)
        self.request = MovementRequest(id_comando=7)
        self.original_state = deepcopy(self.connection.state)
        self.original_history = deepcopy(self.connection.history)

    def assert_reverted_and_closed(self):
        self.assertEqual(self.connection.state, self.original_state)
        self.assertEqual(self.connection.history, self.original_history)
        self.assertEqual(self.connection.commits, 0)
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertEqual(self.connection.closed, 1)


class MovementModelTests(unittest.TestCase):
    def test_command_id_is_the_only_required_field(self):
        self.assertEqual(MovementRequest(id_comando=1).model_dump(), {"id_comando": 1})
        with self.assertRaises(ValidationError):
            MovementRequest()

    def test_identifier_accepts_positive_int_limit_without_coercion(self):
        self.assertEqual(MovementRequest(id_comando=INT_MAX).id_comando, INT_MAX)
        for value in (True, False, "1", 1.0, 0, -1, INT_MAX + 1, None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    MovementRequest(id_comando=value)

    def test_request_rejects_origin_connected_code_and_other_extra_fields(self):
        for extra in (
            {"origen": "DEMO"}, {"conectado": True}, {"codigo": 5},
            {"id_vehiculo": 4}, {"nombre": "Nueva orden"},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    MovementRequest(id_comando=7, **extra)


class MovementTransactionTests(MovementFixture, unittest.TestCase):
    def test_success_preserves_false_and_commits_both_changes_once(self):
        response = self.service.execute(3, self.request)
        self.connection.events.append(("response",))
        self.assertEqual(response.model_dump(), {
            "resultado": "ok", "id_vehiculo": 3, "id_comando": 7,
            "comando": "REVERSA", "codigo": -5, "fecha_actualizacion": DATABASE_TIMESTAMP,
            "conectado": False, "origen": "API",
        })
        self.assertEqual(self.connection.state["id_comando"], 7)
        self.assertEqual(self.connection.history, self.original_history + [
            {"id_vehiculo": 3, "id_comando": 7, "origen": "API"}
        ])
        self.assertEqual(self.connection.calls, [
            ("sp_obtener_vehiculo", (3,)),
            ("sp_obtener_comandos_vehiculo", (3,)),
            ("sp_obtener_estado", (3,)),
            ("sp_actualizar_estado", (3, 7, False)),
            ("sp_registrar_historial", (3, 7, "API")),
            ("sp_obtener_estado", (3,)),
        ])
        self.connect.assert_called_once()
        self.assertEqual((self.connection.begin_count, self.connection.commits, self.connection.rollbacks), (1, 1, 0))
        self.assertEqual(self.connection.events[-3:], [("commit",), ("close",), ("response",)])
        self.assertTrue(all(cursor.drained and cursor.closed for cursor in self.connection.cursors))

    def test_success_preserves_existing_true(self):
        self.connection.state["conectado"] = 1
        response = self.service.execute(3, self.request)
        self.assertIs(response.conectado, True)
        self.assertIn(("sp_actualizar_estado", (3, 7, True)), self.connection.calls)

    def test_missing_state_creates_false_without_rejecting_a_disconnected_vehicle(self):
        self.connection.state = None
        response = self.service.execute(3, self.request)
        self.assertIs(response.conectado, False)
        self.assertEqual(self.connection.state["conectado"], 0)
        self.assertEqual(self.connection.commits, 1)

    def test_response_timestamp_is_the_database_value_and_nullable(self):
        self.connection.generated_timestamp = None
        response = self.service.execute(3, self.request)
        self.assertIsNone(response.fecha_actualizacion)
        self.assertEqual(self.connection.commits, 1)

    def test_missing_vehicle_is_404_domain_error_before_command_lookup(self):
        self.connection.vehicle = None
        with self.assertRaises(ResourceNotFoundError):
            self.service.execute(3, self.request)
        self.assertEqual(self.connection.calls, [("sp_obtener_vehiculo", (3,))])
        self.assert_reverted_and_closed()

    def test_vehicle_id_mismatch_is_a_database_result_error(self):
        self.connection.vehicle["id_vehiculo"] = 4
        with self.assertRaises(DatabaseResultError):
            self.service.execute(3, self.request)
        self.assertEqual(len(self.connection.calls), 1)
        self.assert_reverted_and_closed()

    def test_inactive_vehicle_is_conflict_before_any_write(self):
        self.connection.vehicle["activo"] = 0
        with self.assertRaises(ResourceConflictError) as raised:
            self.service.execute(3, self.request)
        self.assertEqual(str(raised.exception), "El vehículo está inactivo.")
        self.assertEqual(len(self.connection.calls), 1)
        self.assert_reverted_and_closed()

    def test_absent_command_is_404_before_state_read_and_writes(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.execute(3, MovementRequest(id_comando=99))
        self.assertEqual(len(self.connection.calls), 2)
        self.assert_reverted_and_closed()

    def test_existing_command_owned_by_another_vehicle_is_404(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.execute(3, MovementRequest(id_comando=8))
        self.assertEqual(len(self.connection.calls), 2)
        self.assert_reverted_and_closed()

    def test_command_with_wrong_owner_in_an_unexpected_result_cannot_be_used(self):
        self.connection.command_rows_override = [self.connection.commands[2]]
        with self.assertRaises(ResourceNotFoundError):
            self.service.execute(3, MovementRequest(id_comando=8))
        self.assert_reverted_and_closed()

    def test_inactive_command_is_conflict_without_writes(self):
        self.connection.commands[1]["activo"] = 0
        with self.assertRaises(ResourceConflictError) as raised:
            self.service.execute(3, self.request)
        self.assertEqual(str(raised.exception), "El comando está inactivo.")
        self.assertEqual(len(self.connection.calls), 2)
        self.assert_reverted_and_closed()

    def test_wrong_vehicle_in_initial_state_cannot_update_state(self):
        initial = self.connection.state_result()[0] if self.connection.working_state else {
            **self.original_state, "vehiculo": "Otro", "comando": "DETENER", "codigo": 0,
        }
        initial["id_vehiculo"] = 4
        self.connection.state_overrides[1] = [initial]
        with self.assertRaises(DatabaseResultError):
            self.service.execute(3, self.request)
        self.assertEqual(len(self.connection.calls), 3)
        self.assert_reverted_and_closed()

    def test_state_update_error_prevents_history_and_rolls_back(self):
        self.connection.failures[("call", "sp_actualizar_estado", 1)] = pymysql.OperationalError(
            1644, "detalle privado de estado"
        )
        with self.assertRaises(StoredProcedureExecutionError) as raised:
            self.service.execute(3, self.request)
        self.assertNotIn("detalle privado", str(raised.exception))
        self.assertNotIn("sp_registrar_historial", [name for name, _ in self.connection.calls])
        self.assert_reverted_and_closed()

    def test_history_error_after_state_update_rolls_back_the_state(self):
        self.connection.failures[("call", "sp_registrar_historial", 1)] = pymysql.OperationalError(
            1644, "detalle privado de historial"
        )
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.execute(3, self.request)
        self.assertIn(("sp_actualizar_estado", (3, 7, False)), self.connection.calls)
        self.assert_reverted_and_closed()

    def test_late_history_result_failure_rolls_back_both_mutations(self):
        self.connection.failures[("drain", "sp_registrar_historial", 1)] = pymysql.OperationalError(
            1644, "fallo tardío privado"
        )
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.execute(3, self.request)
        self.assert_reverted_and_closed()
        self.assertTrue(self.connection.cursors[-1].closed)

    def test_late_state_result_failure_does_not_run_history(self):
        self.connection.failures[("drain", "sp_actualizar_estado", 1)] = pymysql.OperationalError(
            1644, "fallo tardío privado"
        )
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.execute(3, self.request)
        self.assertNotIn("sp_registrar_historial", [name for name, _ in self.connection.calls])
        self.assert_reverted_and_closed()

    def test_failure_on_final_state_read_rolls_back_state_and_history(self):
        self.connection.failures[("call", "sp_obtener_estado", 2)] = pymysql.OperationalError(
            1644, "fallo privado de relectura"
        )
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.execute(3, self.request)
        self.assert_reverted_and_closed()

    def test_absent_final_state_rolls_back_both_writes(self):
        self.connection.state_overrides[2] = []
        with self.assertRaises(DatabaseResultError):
            self.service.execute(3, self.request)
        self.assert_reverted_and_closed()

    def test_incoherent_final_state_is_rejected_before_commit(self):
        valid = {
            "id_vehiculo": 3, "vehiculo": "Vehículo simulado", "id_comando": 7,
            "comando": "REVERSA", "codigo": -5, "conectado": 0,
            "fecha_actualizacion": DATABASE_TIMESTAMP,
        }
        for changes in (
            {"id_vehiculo": 4}, {"id_comando": 1}, {"comando": "OTRO"},
            {"codigo": 0}, {"conectado": 1}, {"id_comando": None, "comando": None, "codigo": None},
        ):
            with self.subTest(changes=changes):
                # Una conexión independiente para cada subcaso evita reutilizar
                # el estado, el contador de lecturas o los snapshots previos.
                self.connection = MovementConnection()
                self.connect.return_value = self.connection
                self.connection.state_overrides[2] = [{**valid, **changes}]
                with self.assertRaises(DatabaseResultError):
                    self.service.execute(3, self.request)
                self.assert_reverted_and_closed()

    def test_malformed_final_state_is_sanitized_and_reverted(self):
        self.connection.state_overrides[2] = [{"dato_privado": "no exponer"}]
        with self.assertRaises(DatabaseResultError) as raised:
            self.service.execute(3, self.request)
        self.assertNotIn("dato_privado", str(raised.exception))
        self.assert_reverted_and_closed()

    def test_integrity_conflict_after_state_change_rolls_back(self):
        self.connection.failures[("call", "sp_registrar_historial", 1)] = pymysql.IntegrityError(
            1452, "detalle privado FK"
        )
        with self.assertRaises(DatabaseConflictError):
            self.service.execute(3, self.request)
        self.assert_reverted_and_closed()

    def test_connection_loss_after_state_change_is_sanitized_and_reverted(self):
        self.connection.failures[("drain", "sp_registrar_historial", 1)] = pymysql.OperationalError(
            2013, "detalle privado conexión"
        )
        with self.assertRaises(DatabaseUnavailableError):
            self.service.execute(3, self.request)
        self.assert_reverted_and_closed()

    def test_commit_failure_propagates_error_and_never_returns_success(self):
        self.connection.commit_error = pymysql.OperationalError(2013, "detalle privado de commit")
        with self.assertRaises(DatabaseTransactionError) as raised:
            self.service.execute(3, self.request)
        self.assertNotIn("detalle privado", str(raised.exception))
        self.assertEqual(self.connection.commit_attempts, 1)
        self.assertEqual([name for name, _ in self.connection.calls].count("sp_obtener_estado"), 2)
        self.assert_reverted_and_closed()


class MovementHttpTests(MovementFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.application = FastAPI()
        self.application.include_router(router)
        register_exception_handlers(self.application)
        self.application.dependency_overrides[get_database] = lambda: self.database
        self.application.dependency_overrides[require_api_key] = lambda: None

    async def request_http(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
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

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        response = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return response["status"], json.loads(content)

    async def test_post_returns_200_only_after_real_transaction_commit(self):
        status, content = await self.request_http("/vehiculos/3/movimientos", {"id_comando": 7})
        self.assertEqual(status, 200)
        self.assertEqual(content, {
            "resultado": "ok", "id_vehiculo": 3, "id_comando": 7,
            "comando": "REVERSA", "codigo": -5, "fecha_actualizacion": "2026-10-14T12:30:45",
            "conectado": False, "origen": "API",
        })
        self.assertEqual(self.connection.commits, 1)
        self.assertEqual(self.connection.closed, 1)

    async def test_path_and_body_validation_return_422_without_connecting(self):
        cases = [
            ("/vehiculos/0/movimientos", {"id_comando": 7}),
            (f"/vehiculos/{INT_MAX + 1}/movimientos", {"id_comando": 7}),
            ("/vehiculos/3/movimientos", {"id_comando": True}),
            ("/vehiculos/3/movimientos", {"id_comando": "7"}),
            ("/vehiculos/3/movimientos", {"id_comando": 7, "conectado": True}),
            ("/vehiculos/3/movimientos", {"id_comando": 7, "origen": "MANUAL"}),
        ]
        for path, payload in cases:
            with self.subTest(path=path, payload=payload):
                status, _ = await self.request_http(path, payload)
                self.assertEqual(status, 422)
        self.connect.assert_not_called()

    async def test_wrong_parent_command_returns_safe_404(self):
        status, content = await self.request_http("/vehiculos/3/movimientos", {"id_comando": 8})
        self.assertEqual(status, 404)
        self.assertEqual(content, {"detail": "El comando no existe para este vehículo."})
        self.assert_reverted_and_closed()

    async def test_inactive_command_returns_safe_409(self):
        self.connection.commands[1]["activo"] = 0
        status, content = await self.request_http("/vehiculos/3/movimientos", {"id_comando": 7})
        self.assertEqual(status, 409)
        self.assertEqual(content, {"detail": "El comando está inactivo."})
        self.assert_reverted_and_closed()

    async def test_commit_failure_returns_503_without_a_success_payload(self):
        self.connection.commit_error = pymysql.OperationalError(2013, "detalle privado")
        status, content = await self.request_http("/vehiculos/3/movimientos", {"id_comando": 7})
        self.assertEqual(status, 503)
        self.assertNotIn("resultado", content)
        self.assertNotIn("detalle privado", str(content))
        self.assert_reverted_and_closed()

    async def test_openapi_documents_the_exact_body_procedures_and_response(self):
        schema = self.application.openapi()
        operation = schema["paths"]["/vehiculos/{id_vehiculo}/movimientos"]["post"]
        self.assertEqual(operation["tags"], ["Movimientos"])
        self.assertEqual(set(operation["responses"]), {"200", "401", "403", "404", "409", "422", "500", "503"})
        for name in (
            "sp_obtener_vehiculo", "sp_obtener_comandos_vehiculo", "sp_obtener_estado",
            "sp_actualizar_estado", "sp_registrar_historial",
        ):
            self.assertIn(name, operation["description"])
        request_schema = schema["components"]["schemas"]["MovementRequest"]
        self.assertEqual(set(request_schema["properties"]), {"id_comando"})
        self.assertIs(request_schema["additionalProperties"], False)
        response_fields = schema["components"]["schemas"]["MovementResponse"]["properties"]
        self.assertEqual(set(response_fields), {
            "resultado", "id_vehiculo", "id_comando", "comando", "codigo",
            "fecha_actualizacion", "conectado", "origen",
        })
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
