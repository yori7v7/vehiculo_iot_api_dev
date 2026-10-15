"""Estado, historial y movimiento por ASGI con datos ficticios, sin .env ni RDS."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.database.procedures import ProcedureResult
from app.dependencies import get_database
from app.errors.database import (
    DatabaseError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.handlers import register_exception_handlers
from app.routers.history import router as history_router
from app.routers.movement import router as movement_router
from app.routers.state import router as state_router
from app.security.api_key import require_api_key


class MovementDatabase:
    """Doble con snapshots para observar rollback sin hacer escrituras reales."""

    def __init__(self) -> None:
        self.clock = datetime(2026, 10, 14, 12, 0)
        self.vehicles = {
            identifier: {
                "id_vehiculo": identifier,
                "nombre": f"Vehículo ficticio {identifier}",
                "modelo": None,
                "descripcion": None,
                "microcontrolador": None,
                "fecha_registro": self.clock,
                "activo": 1,
            }
            for identifier in (1, 2)
        }
        self.commands = {
            identifier: {
                "id_comando": identifier,
                "id_vehiculo": identifier,
                "nombre": f"Comando ficticio {identifier}",
                "codigo": -identifier,
                "descripcion": None,
                "activo": 1,
            }
            for identifier in (1, 2)
        }
        self.states: dict[int, dict] = {}
        self.history: list[dict] = []
        self.modes: list[bool] = []
        self.calls: list[tuple[str, tuple]] = []
        self.read_only: bool | None = None
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.state_updates = 0
        self.transaction_error: DatabaseError | None = None
        self.procedure_errors: dict[str, DatabaseError] = {}
        self.commit_error: DatabaseError | None = None
        self.write_timestamp: datetime | None = self.clock + timedelta(seconds=1)

    def snapshot(self):
        return deepcopy((self.vehicles, self.commands, self.states, self.history))

    def seed_state(self, *, connected=False, command_id=None):
        command = self.commands.get(command_id)
        self.states[1] = {
            "id_vehiculo": 1,
            "vehiculo": self.vehicles[1]["nombre"],
            "id_comando": command_id,
            "comando": command["nombre"] if command is not None else None,
            "codigo": command["codigo"] if command is not None else None,
            "conectado": int(connected),
            "fecha_actualizacion": None,
        }

    def seed_history(self, count, origins=("WORKBENCH",)):
        self.history = [
            {
                "id_historial": 2**31 + index,
                "id_vehiculo": 1,
                "comando": "Comando ficticio" if index % 2 else None,
                "codigo": -1 if index % 2 else None,
                "fecha_hora": self.clock + timedelta(seconds=index // 3),
                "origen": origins[index % len(origins)],
            }
            for index in range(1, count + 1)
        ]

    @contextmanager
    def transaction(self, *, read_only=False) -> Iterator["MovementDatabase"]:
        if self.transaction_error is not None:
            raise self.transaction_error
        before = self.snapshot()
        self.modes.append(read_only)
        self.read_only = read_only
        try:
            yield self
            if read_only:
                if self.snapshot() != before:
                    raise AssertionError("Un GET no puede modificar los datos simulados.")
                self.rollbacks += 1
            else:
                if self.commit_error is not None:
                    raise self.commit_error
                self.commits += 1
        except BaseException:
            self.vehicles, self.commands, self.states, self.history = before
            self.rollbacks += 1
            raise
        finally:
            self.closes += 1
            self.read_only = None


class MovementProcedureExecutor:
    """Resultados con los alias exactos del SQL; nunca SQL ni sockets reales."""

    READ_PROCEDURES = {
        "sp_obtener_vehiculo",
        "sp_obtener_comandos_vehiculo",
        "sp_obtener_estado",
        "sp_obtener_historial",
    }
    WRITE_PROCEDURES = {"sp_actualizar_estado", "sp_registrar_historial"}

    def __init__(self, connection: MovementDatabase) -> None:
        self.database = connection

    def execute(self, procedure: str, parameters: Sequence[object] = ()) -> ProcedureResult:
        parameters = tuple(parameters)
        self.database.calls.append((procedure, parameters))
        if self.database.read_only and procedure not in self.READ_PROCEDURES:
            raise AssertionError("Una transacción READ ONLY no admite escrituras.")
        if procedure in self.database.procedure_errors:
            raise self.database.procedure_errors[procedure]
        operation = getattr(self, procedure, None)
        if operation is None:
            raise AssertionError(f"Procedimiento no previsto en estas pruebas: {procedure}")
        rows = operation(*parameters)
        return ProcedureResult(
            result_sets=() if rows is None else (tuple(deepcopy(rows)),)
        )

    def sp_obtener_vehiculo(self, vehicle_id):
        row = self.database.vehicles.get(vehicle_id)
        return [] if row is None else [row]

    def sp_obtener_comandos_vehiculo(self, vehicle_id):
        return sorted(
            (row for row in self.database.commands.values() if row["id_vehiculo"] == vehicle_id),
            key=lambda row: row["codigo"],
        )

    def sp_obtener_estado(self, vehicle_id):
        row = self.database.states.get(vehicle_id)
        return [] if row is None else [row]

    def sp_obtener_historial(self, vehicle_id):
        return sorted(
            (row for row in self.database.history if row["id_vehiculo"] == vehicle_id),
            key=lambda row: (
                row["fecha_hora"] is not None,
                row["fecha_hora"] or datetime.min,
                row["id_historial"],
            ),
            reverse=True,
        )

    def sp_actualizar_estado(self, vehicle_id, command_id, connected):
        command = self.database.commands[command_id]
        self.database.states[vehicle_id] = {
            "id_vehiculo": vehicle_id,
            "vehiculo": self.database.vehicles[vehicle_id]["nombre"],
            "id_comando": command_id,
            "comando": command["nombre"],
            "codigo": command["codigo"],
            "conectado": connected,
            "fecha_actualizacion": self.database.write_timestamp,
        }
        self.database.state_updates += 1

    def sp_registrar_historial(self, vehicle_id, command_id, origin):
        command = self.database.commands[command_id]
        self.database.history.append({
            "id_historial": max((row["id_historial"] for row in self.database.history), default=0) + 1,
            "id_vehiculo": vehicle_id,
            "comando": command["nombre"],
            "codigo": command["codigo"],
            "fecha_hora": self.database.write_timestamp,
            "origen": origin,
        })


class MovementHTTPTests(unittest.IsolatedAsyncioTestCase):
    """Ejercer las rutas, los servicios y los repositorios sin aplicación global."""

    def setUp(self) -> None:
        self.database = MovementDatabase()
        self.application = FastAPI()
        register_exception_handlers(self.application)
        for router in (state_router, history_router, movement_router):
            self.application.include_router(router)
        self.application.dependency_overrides[get_database] = lambda: self.database
        self.application.dependency_overrides[require_api_key] = lambda: None
        for module in ("state", "history", "movement"):
            executor_patch = patch(
                f"app.services.{module}.StoredProcedureExecutor", MovementProcedureExecutor
            )
            executor_patch.start()
            self.addCleanup(executor_patch.stop)

        connection_patch = patch(
            "app.database.connection.pymysql.connect",
            side_effect=AssertionError("Estas pruebas no pueden conectarse a RDS."),
        )
        self.connection_guard = connection_patch.start()
        self.addCleanup(connection_patch.stop)
        settings_patch = patch(
            "app.config.settings.Settings",
            side_effect=AssertionError("Estas pruebas no pueden cargar .env."),
        )
        self.settings_guard = settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def tearDown(self) -> None:
        self.connection_guard.assert_not_called()
        self.settings_guard.assert_not_called()

    async def request(self, method, path, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
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
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test.invalid", 50000),
            "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        response = next(message for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return response["status"], json.loads(response_body)

    async def request_json(self, method, path, payload=None, *, expected=200):
        status, response = await self.request(method, path, payload)
        self.assertEqual(status, expected, response)
        return response

    def assert_no_write_calls(self):
        self.assertFalse(
            {procedure for procedure, _ in self.database.calls}
            & MovementProcedureExecutor.WRITE_PROCEDURES
        )

    async def test_state_absence_and_nullable_sql_aliases_are_read_only(self):
        before = self.database.snapshot()
        self.assertIsNone(await self.request_json("GET", "/vehiculos/1/estado"))
        self.assertEqual(self.database.snapshot(), before)

        self.database.seed_state(connected=True)
        self.database.vehicles[1]["activo"] = 0
        before = self.database.snapshot()
        response = await self.request_json("GET", "/vehiculos/1/estado")
        self.assertEqual(set(response), {
            "id_vehiculo", "vehiculo", "id_comando", "comando", "codigo",
            "conectado", "fecha_actualizacion",
        })
        self.assertIs(response["conectado"], True)
        for field in ("id_comando", "comando", "codigo", "fecha_actualizacion"):
            self.assertIsNone(response[field])
        self.assertEqual(self.database.snapshot(), before)
        self.assertEqual(self.database.modes, [True, True])
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 2))
        self.assert_no_write_calls()

    async def test_history_retains_workbench_other_origins_order_and_maximum_ten(self):
        self.assertEqual(await self.request_json("GET", "/vehiculos/1/historial"), [])
        self.database.seed_history(5)
        self.database.history[0]["fecha_hora"] = None
        before = self.database.snapshot()
        response = await self.request_json("GET", "/vehiculos/1/historial")
        self.assertEqual(len(response), 5)
        self.assertEqual([row["id_historial"] for row in response], [2**31 + index for index in (5, 4, 3, 2, 1)])
        self.assertEqual({row["origen"] for row in response}, {"WORKBENCH"})
        self.assertIsNone(response[-1]["fecha_hora"])
        self.assertTrue(any(row["comando"] is None and row["codigo"] is None for row in response))
        self.assertTrue(all("id_comando" not in row for row in response))
        self.assertEqual(self.database.snapshot(), before)

        self.database.seed_history(20, origins=("WORKBENCH", "MANUAL", "API", "IMPORTADO"))
        before = self.database.snapshot()
        response = await self.request_json("GET", "/vehiculos/1/historial")
        self.assertEqual(len(response), 10)
        self.assertEqual([row["id_historial"] for row in response], [2**31 + index for index in range(20, 10, -1)])
        self.assertEqual({row["origen"] for row in response}, {"WORKBENCH", "MANUAL", "API", "IMPORTADO"})
        self.assertEqual(len(self.database.history), 20)
        self.assertEqual(self.database.snapshot(), before)
        self.assertEqual(self.database.modes, [True, True, True])
        self.assertEqual(self.database.commits, 0)
        self.assert_no_write_calls()

    async def test_movement_preserves_connectivity_and_commits_state_and_api_history(self):
        for connected in (None, False, True):
            with self.subTest(existing_connected=connected):
                self.database = MovementDatabase()
                self.database.seed_history(1)
                if connected is not None:
                    self.database.seed_state(connected=connected)
                if connected is False:
                    self.database.write_timestamp = None
                expected_connected = connected if connected is not None else False
                vehicles_before = deepcopy(self.database.vehicles)
                commands_before = deepcopy(self.database.commands)
                old_history = deepcopy(self.database.history)
                response = await self.request_json(
                    "POST", "/vehiculos/1/movimientos", {"id_comando": 1}
                )
                self.assertEqual(response, {
                    "resultado": "ok",
                    "id_vehiculo": 1,
                    "id_comando": 1,
                    "comando": "Comando ficticio 1",
                    "codigo": -1,
                    "fecha_actualizacion": (
                        self.database.write_timestamp.isoformat()
                        if self.database.write_timestamp is not None else None
                    ),
                    "conectado": expected_connected,
                    "origen": "API",
                })
                self.assertEqual(self.database.vehicles, vehicles_before)
                self.assertEqual(self.database.commands, commands_before)
                self.assertEqual(self.database.history[:-1], old_history)
                self.assertEqual(self.database.history[-1]["origen"], "API")
                self.assertEqual(self.database.states[1]["id_comando"], 1)
                self.assertIs(self.database.states[1]["conectado"], expected_connected)
                self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closes), (1, 0, 1))
                self.assertEqual(self.database.modes, [False])
                self.assertEqual(self.database.calls, [
                    ("sp_obtener_vehiculo", (1,)),
                    ("sp_obtener_comandos_vehiculo", (1,)),
                    ("sp_obtener_estado", (1,)),
                    ("sp_actualizar_estado", (1, 1, expected_connected)),
                    ("sp_registrar_historial", (1, 1, "API")),
                    ("sp_obtener_estado", (1,)),
                ])

    async def test_missing_or_inactive_resources_return_errors_without_writes(self):
        cases = (
            ("missing_vehicle", 999, 1, 404),
            ("inactive_vehicle", 1, 1, 409),
            ("missing_command", 1, 999, 404),
            ("foreign_command", 1, 2, 404),
            ("inactive_command", 1, 1, 409),
        )
        for case, vehicle_id, command_id, expected in cases:
            with self.subTest(case=case):
                self.database = MovementDatabase()
                self.database.seed_state()
                self.database.seed_history(1)
                if case == "inactive_vehicle":
                    self.database.vehicles[1]["activo"] = 0
                elif case == "inactive_command":
                    self.database.commands[1]["activo"] = 0
                before = self.database.snapshot()
                response = await self.request_json(
                    "POST", f"/vehiculos/{vehicle_id}/movimientos",
                    {"id_comando": command_id}, expected=expected,
                )
                self.assertEqual(set(response), {"detail"})
                self.assertEqual(self.database.snapshot(), before)
                self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))
                self.assert_no_write_calls()

        for path in ("/vehiculos/999/estado", "/vehiculos/999/historial"):
            with self.subTest(path=path):
                await self.request_json("GET", path, expected=404)
        self.assert_no_write_calls()

    async def test_write_or_commit_failure_rolls_back_and_never_returns_success(self):
        for failed_operation in ("sp_actualizar_estado", "sp_registrar_historial", "commit"):
            with self.subTest(failed_operation=failed_operation):
                self.database = MovementDatabase()
                self.database.seed_state(connected=True)
                self.database.seed_history(1)
                before = self.database.snapshot()
                if failed_operation == "commit":
                    error = DatabaseTransactionError()
                    self.database.commit_error = error
                    expected = 503
                else:
                    error = StoredProcedureExecutionError()
                    self.database.procedure_errors[failed_operation] = error
                    expected = 500
                error.__cause__ = RuntimeError("DETALLE_INTERNO_FICTICIO")
                response = await self.request_json(
                    "POST", "/vehiculos/1/movimientos", {"id_comando": 1}, expected=expected
                )
                self.assertEqual(response, {"detail": str(error)})
                self.assertNotIn("DETALLE_INTERNO_FICTICIO", json.dumps(response))
                self.assertEqual(self.database.snapshot(), before)
                self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closes), (0, 1, 1))
                if failed_operation == "sp_actualizar_estado":
                    self.assertNotIn("sp_registrar_historial", [name for name, _ in self.database.calls])
                    self.assertEqual(self.database.state_updates, 0)
                else:
                    self.assertEqual(self.database.state_updates, 1)

    async def test_movement_request_rejects_invalid_ids_and_server_managed_fields(self):
        invalid_payloads = (
            {}, {"id_comando": 0}, {"id_comando": -1}, {"id_comando": 2**31},
            {"id_comando": True}, {"id_comando": 1.0}, {"id_comando": "1"},
            {"id_comando": None}, {"id_comando": 1, "origen": "WORKBENCH"},
            {"id_comando": 1, "conectado": True}, {"id_comando": 1, "codigo": 5},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                await self.request_json(
                    "POST", "/vehiculos/1/movimientos", payload, expected=422
                )
        for method, suffix, vehicle_id in (
            ("GET", "estado", "0"),
            ("GET", "historial", str(2**31)),
            ("POST", "movimientos", "-1"),
            ("POST", "movimientos", "1.5"),
        ):
            with self.subTest(method=method, suffix=suffix, vehicle_id=vehicle_id):
                await self.request_json(
                    method, f"/vehiculos/{vehicle_id}/{suffix}",
                    {"id_comando": 1} if method == "POST" else None, expected=422,
                )
        self.assertEqual(self.database.modes, [])
        self.assertEqual(self.database.calls, [])

    async def test_unavailable_database_returns_safe_503_for_all_three_routes(self):
        error = DatabaseUnavailableError()
        error.__cause__ = RuntimeError("DETALLE_INTERNO_FICTICIO")
        self.database.transaction_error = error
        for method, suffix, payload in (
            ("GET", "estado", None),
            ("GET", "historial", None),
            ("POST", "movimientos", {"id_comando": 1}),
        ):
            with self.subTest(method=method, suffix=suffix):
                response = await self.request_json(
                    method, f"/vehiculos/1/{suffix}", payload, expected=503
                )
                self.assertEqual(response, {"detail": str(error)})
                self.assertNotIn("DETALLE_INTERNO_FICTICIO", json.dumps(response))
        self.assertEqual(self.database.calls, [])
        self.assertEqual(self.database.commits, 0)

    async def test_openapi_documents_three_routes_real_sp_and_sql_response_aliases(self):
        schema = await self.request_json("GET", "/openapi.json")
        expected = {
            ("/vehiculos/{id_vehiculo}/estado", "get"): (
                "Estado", ("sp_obtener_vehiculo", "sp_obtener_estado")
            ),
            ("/vehiculos/{id_vehiculo}/historial", "get"): (
                "Historial", ("sp_obtener_vehiculo", "sp_obtener_historial")
            ),
            ("/vehiculos/{id_vehiculo}/movimientos", "post"): (
                "Movimientos", ("sp_obtener_vehiculo", "sp_obtener_comandos_vehiculo",
                                "sp_obtener_estado", "sp_actualizar_estado", "sp_registrar_historial")
            ),
        }
        documented = {(path, method) for path, operations in schema["paths"].items() for method in operations}
        self.assertEqual(documented, set(expected))
        for (path, method), (tag, procedures) in expected.items():
            with self.subTest(path=path, method=method):
                operation = schema["paths"][path][method]
                self.assertEqual(operation["tags"], [tag])
                self.assertIn("200", operation["responses"])
                for error in ("404", "422", "500", "503"):
                    self.assertIn(error, operation["responses"])
                for procedure in procedures:
                    self.assertIn(procedure, operation["description"])
        movement = schema["paths"]["/vehiculos/{id_vehiculo}/movimientos"]["post"]
        self.assertIn("409", movement["responses"])
        self.assertIn("401", movement["responses"])
        self.assertIn("403", movement["responses"])
        self.assertNotIn("201", movement["responses"])
        for phrase in ("misma conexión", "transacción", "revierte"):
            self.assertIn(phrase, movement["description"])
        models = schema["components"]["schemas"]
        self.assertEqual(set(models["StateResponse"]["properties"]), {
            "id_vehiculo", "vehiculo", "id_comando", "comando", "codigo",
            "conectado", "fecha_actualizacion",
        })
        self.assertEqual(set(models["HistoryResponse"]["properties"]), {
            "id_historial", "id_vehiculo", "comando", "codigo", "fecha_hora", "origen",
        })
        self.assertEqual(set(models["MovementRequest"]["properties"]), {"id_comando"})
        self.assertIs(models["MovementRequest"]["additionalProperties"], False)
        self.assertEqual(models["MovementResponse"]["properties"]["origen"]["const"], "API")


if __name__ == "__main__":
    unittest.main()
