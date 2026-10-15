"""Contratos HTTP con servicios reales y datos ficticios, sin .env ni RDS."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.database.procedures import ProcedureResult
from app.dependencies import get_database
from app.errors.database import (
    DatabaseConflictError,
    DatabaseError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.handlers import register_exception_handlers
from app.routers.commands import router as command_router
from app.routers.vehicles import router as vehicle_router
from app.security.api_key import require_api_key


class MemoryDatabase:
    """Doble transaccional exclusivo de estas pruebas; no construye Settings."""

    def __init__(self) -> None:
        self.vehicles: dict[int, dict] = {}
        self.commands: dict[int, dict] = {}
        self.next_vehicle_id = 1
        self.next_command_id = 1
        self.read_only: bool | None = None
        self.transactions: list[bool] = []
        self.calls: list[tuple[str, tuple]] = []
        self.transaction_error: DatabaseError | None = None
        self.procedure_errors: dict[str, DatabaseError] = {}

    @contextmanager
    def transaction(self, *, read_only: bool = False) -> Iterator["MemoryDatabase"]:
        if self.transaction_error is not None:
            raise self.transaction_error
        snapshot = deepcopy((self.vehicles, self.commands))
        self.transactions.append(read_only)
        self.read_only = read_only
        try:
            yield self
        except BaseException:
            self.vehicles, self.commands = snapshot
            raise
        finally:
            self.read_only = None


class MemoryProcedureExecutor:
    """Simular sólo los nueve SP SQL; el router y las capas superiores son reales."""

    READ_PROCEDURES = {
        "sp_obtener_vehiculos",
        "sp_obtener_vehiculo",
        "sp_obtener_comandos_vehiculo",
    }

    def __init__(self, connection: MemoryDatabase) -> None:
        self.database = connection

    def execute(
        self, procedure: str, parameters: Sequence[object] = ()
    ) -> ProcedureResult:
        parameters = tuple(parameters)
        self.database.calls.append((procedure, parameters))
        if procedure in self.database.procedure_errors:
            raise self.database.procedure_errors[procedure]
        if self.database.read_only and procedure not in self.READ_PROCEDURES:
            raise AssertionError("Una lectura no debe ejecutar un SP de escritura.")
        operation = getattr(self, procedure, None)
        if operation is None:
            raise AssertionError(f"Stored Procedure fuera de esta etapa: {procedure}")
        rows = operation(*parameters)
        if rows is None:
            return ProcedureResult(result_sets=())
        return ProcedureResult(result_sets=(tuple(deepcopy(rows)),))

    def sp_crear_vehiculo(self, nombre, modelo, descripcion, microcontrolador):
        identifier = self.database.next_vehicle_id
        self.database.next_vehicle_id += 1
        self.database.vehicles[identifier] = {
            "id_vehiculo": identifier,
            "nombre": nombre,
            "modelo": modelo,
            "descripcion": descripcion,
            "microcontrolador": microcontrolador,
            "fecha_registro": datetime(2026, 10, 14, 12, 0),
            "activo": 1,
        }
        return [{"id_vehiculo": identifier}]

    def sp_obtener_vehiculos(self):
        return [self.database.vehicles[key] for key in sorted(self.database.vehicles)]

    def sp_obtener_vehiculo(self, identifier):
        row = self.database.vehicles.get(identifier)
        return [row] if row is not None else []

    def sp_actualizar_vehiculo(
        self, identifier, nombre, modelo, descripcion, microcontrolador, activo
    ):
        row = self.database.vehicles.get(identifier)
        if row is not None:
            row.update(
                nombre=nombre,
                modelo=modelo,
                descripcion=descripcion,
                microcontrolador=microcontrolador,
                activo=activo,
            )

    def sp_eliminar_vehiculo(self, identifier):
        self.database.vehicles.pop(identifier, None)
        self.database.commands = {
            key: row
            for key, row in self.database.commands.items()
            if row["id_vehiculo"] != identifier
        }

    def _assert_unique_command(self, vehicle_id, nombre, codigo, excluded_id=None):
        for row in self.database.commands.values():
            if row["id_vehiculo"] == vehicle_id and row["id_comando"] != excluded_id:
                if row["nombre"] == nombre or row["codigo"] == codigo:
                    raise DatabaseConflictError()

    def sp_crear_comando(self, vehicle_id, nombre, codigo, descripcion):
        self._assert_unique_command(vehicle_id, nombre, codigo)
        identifier = self.database.next_command_id
        self.database.next_command_id += 1
        self.database.commands[identifier] = {
            "id_comando": identifier,
            "id_vehiculo": vehicle_id,
            "nombre": nombre,
            "codigo": codigo,
            "descripcion": descripcion,
            "activo": 1,
        }
        return [{"id_comando": identifier}]

    def sp_obtener_comandos_vehiculo(self, vehicle_id):
        return sorted(
            (row for row in self.database.commands.values() if row["id_vehiculo"] == vehicle_id),
            key=lambda row: row["codigo"],
        )

    def sp_actualizar_comando(self, identifier, nombre, codigo, descripcion, activo):
        row = self.database.commands.get(identifier)
        if row is not None:
            self._assert_unique_command(row["id_vehiculo"], nombre, codigo, identifier)
            row.update(nombre=nombre, codigo=codigo, descripcion=descripcion, activo=activo)

    def sp_eliminar_comando(self, identifier):
        self.database.commands.pop(identifier, None)


class ResourceHTTPTests(unittest.IsolatedAsyncioTestCase):
    """ASGI directo: no TestClient/httpx, sockets ni aplicación global."""

    def setUp(self) -> None:
        self.database = MemoryDatabase()
        self.application = FastAPI()
        register_exception_handlers(self.application)
        self.application.include_router(vehicle_router)
        self.application.include_router(command_router)
        self.application.dependency_overrides[get_database] = lambda: self.database
        self.application.dependency_overrides[require_api_key] = lambda: None

        for module in ("vehicles", "commands"):
            executor_patch = patch(
                f"app.services.{module}.StoredProcedureExecutor", MemoryProcedureExecutor
            )
            executor_patch.start()
            self.addCleanup(executor_patch.stop)

        # Si un cambio pierde el override, debe fallar en vez de abrir un socket.
        connection_patch = patch(
            "app.database.connection.pymysql.connect",
            side_effect=AssertionError("Estas pruebas no pueden conectarse a RDS."),
        )
        self.connection_guard = connection_patch.start()
        self.addCleanup(connection_patch.stop)
        settings_patch = patch(
            "app.config.settings.Settings",
            side_effect=AssertionError("Estas pruebas no pueden cargar el archivo .env."),
        )
        self.settings_guard = settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def tearDown(self) -> None:
        self.connection_guard.assert_not_called()
        self.settings_guard.assert_not_called()

    async def request(self, method: str, path: str, payload=None):
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
        return response["status"], response_body

    async def request_json(self, method: str, path: str, payload=None, *, expected=200):
        status, body = await self.request(method, path, payload)
        self.assertEqual(status, expected, body.decode("utf-8"))
        return json.loads(body)

    async def create_vehicle(self, nombre="Vehículo ficticio", **fields):
        return await self.request_json(
            "POST", "/vehiculos", {"nombre": nombre, **fields}, expected=201
        )

    async def test_nine_crud_operations_preserve_nulls_inactive_and_empty_lists(self):
        self.assertEqual(await self.request_json("GET", "/vehiculos"), [])
        vehicle = await self.create_vehicle(
            modelo="Modelo ficticio", descripcion="Descripción", microcontrolador="Simulado"
        )
        vehicle_path = f"/vehiculos/{vehicle['id_vehiculo']}"
        commands_path = f"{vehicle_path}/comandos"
        self.assertIs(vehicle["activo"], True)
        self.assertEqual(await self.request_json("GET", "/vehiculos"), [vehicle])
        self.assertEqual(await self.request_json("GET", vehicle_path), vehicle)
        self.assertEqual(await self.request_json("GET", commands_path), [])

        same_vehicle = {key: vehicle[key] for key in (
            "nombre", "modelo", "descripcion", "microcontrolador", "activo"
        )}
        self.assertEqual(await self.request_json("PUT", vehicle_path, same_vehicle), vehicle)
        inactive_vehicle = await self.request_json(
            "PUT", vehicle_path, {"nombre": vehicle["nombre"], "activo": False}
        )
        for field in ("modelo", "descripcion", "microcontrolador"):
            self.assertIsNone(inactive_vehicle[field])
        self.assertIs(inactive_vehicle["activo"], False)
        self.assertEqual(await self.request_json("GET", vehicle_path), inactive_vehicle)

        command = await self.request_json(
            "POST", commands_path,
            {"nombre": "Comando ficticio", "codigo": -(2**31), "descripcion": None},
            expected=201,
        )
        command_path = f"{commands_path}/{command['id_comando']}"
        self.assertIs(command["activo"], True)
        self.assertIsNone(command["descripcion"])
        same_command = {key: command[key] for key in ("nombre", "codigo", "descripcion", "activo")}
        self.assertEqual(await self.request_json("PUT", command_path, same_command), command)
        inactive_command = await self.request_json(
            "PUT", command_path,
            {"nombre": command["nombre"], "codigo": 2**31 - 1, "activo": False},
        )
        self.assertIsNone(inactive_command["descripcion"])
        self.assertIs(inactive_command["activo"], False)
        self.assertEqual(await self.request_json("GET", commands_path), [inactive_command])

        self.assertEqual(await self.request("DELETE", command_path), (204, b""))
        self.assertEqual(await self.request_json("GET", commands_path), [])
        self.assertEqual(await self.request("DELETE", vehicle_path), (204, b""))
        self.assertEqual(await self.request_json("GET", "/vehiculos"), [])
        self.assertEqual({name for name, _ in self.database.calls}, {
            "sp_crear_vehiculo", "sp_obtener_vehiculos", "sp_obtener_vehiculo",
            "sp_actualizar_vehiculo", "sp_eliminar_vehiculo", "sp_crear_comando",
            "sp_obtener_comandos_vehiculo", "sp_actualizar_comando", "sp_eliminar_comando",
        })

    async def test_missing_parents_commands_and_foreign_commands_return_404(self):
        missing_parent = [
            ("GET", "/vehiculos/999", None),
            ("PUT", "/vehiculos/999", {"nombre": "Ficticio", "activo": True}),
            ("DELETE", "/vehiculos/999", None),
            ("GET", "/vehiculos/999/comandos", None),
            ("POST", "/vehiculos/999/comandos", {"nombre": "Ficticio", "codigo": 0}),
            ("PUT", "/vehiculos/999/comandos/1", {"nombre": "Ficticio", "codigo": 0, "activo": True}),
            ("DELETE", "/vehiculos/999/comandos/1", None),
        ]
        for method, path, payload in missing_parent:
            with self.subTest(method=method, path=path):
                result = await self.request_json(method, path, payload, expected=404)
                self.assertIn("detail", result)

        first = await self.create_vehicle("Primero ficticio")
        second = await self.create_vehicle("Segundo ficticio")
        own_path = f"/vehiculos/{first['id_vehiculo']}/comandos"
        other_path = f"/vehiculos/{second['id_vehiculo']}/comandos"
        command = await self.request_json(
            "POST", other_path, {"nombre": "Ajeno ficticio", "codigo": 0}, expected=201
        )
        for command_id in (999, command["id_comando"]):
            for method, payload in (
                ("PUT", {"nombre": "Cambio", "codigo": 5, "activo": True}),
                ("DELETE", None),
            ):
                with self.subTest(method=method, command_id=command_id):
                    await self.request_json(
                        method, f"{own_path}/{command_id}", payload, expected=404
                    )
        self.assertEqual(await self.request_json("GET", own_path), [])
        self.assertEqual(await self.request_json("GET", other_path), [command])

    async def test_request_validation_rejects_coercion_ranges_and_extra_fields(self):
        cases = [
            ("POST", "/vehiculos", {"nombre": "X", "id_vehiculo": 1}),
            ("POST", "/vehiculos", {"nombre": "x" * 81}),
            ("PUT", "/vehiculos/1", {"nombre": "X"}),
            ("PUT", "/vehiculos/1", {"nombre": "X", "activo": 1}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": True}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": "7"}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": 7.0}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": 2**31}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": -(2**31) - 1}),
            ("POST", "/vehiculos/1/comandos", {"nombre": "X", "codigo": 0, "activo": True}),
            ("PUT", "/vehiculos/1/comandos/1", {"nombre": "X", "codigo": 0}),
            ("GET", "/vehiculos/0", None),
            ("GET", f"/vehiculos/{2**31}", None),
            ("GET", "/vehiculos/1.5/comandos", None),
            ("DELETE", "/vehiculos/1/comandos/0", None),
        ]
        for method, path, payload in cases:
            with self.subTest(method=method, path=path, payload=payload):
                result = await self.request_json(method, path, payload, expected=422)
                self.assertTrue(result["detail"])
        self.assertEqual(self.database.transactions, [])

    async def test_duplicate_commands_return_safe_409_without_changing_collection(self):
        vehicle = await self.create_vehicle()
        path = f"/vehiculos/{vehicle['id_vehiculo']}/comandos"
        command = await self.request_json(
            "POST", path, {"nombre": "Original ficticio", "codigo": 7}, expected=201
        )
        for payload in (
            {"nombre": "Otro ficticio", "codigo": 7},
            {"nombre": "Original ficticio", "codigo": 8},
        ):
            with self.subTest(payload=payload):
                result = await self.request_json("POST", path, payload, expected=409)
                self.assertEqual(result, {"detail": str(DatabaseConflictError())})
        self.assertEqual(await self.request_json("GET", path), [command])

    async def test_database_errors_have_safe_503_and_500_responses(self):
        for error, expected in (
            (DatabaseUnavailableError(), 503),
            (StoredProcedureExecutionError(), 500),
        ):
            with self.subTest(error=type(error).__name__):
                error.__cause__ = RuntimeError("DETALLE_INTERNO_FICTICIO")
                self.database.transaction_error = None
                self.database.procedure_errors.clear()
                if isinstance(error, DatabaseUnavailableError):
                    self.database.transaction_error = error
                else:
                    self.database.procedure_errors["sp_obtener_vehiculos"] = error
                status, body = await self.request("GET", "/vehiculos")
                self.assertEqual(status, expected)
                self.assertEqual(json.loads(body), {"detail": str(error)})
                self.assertNotIn(b"DETALLE_INTERNO_FICTICIO", body)

    async def test_openapi_documents_all_nine_operations_tags_and_real_procedures(self):
        schema = await self.request_json("GET", "/openapi.json")
        expected = {
            ("/vehiculos", "get"): ("Vehículos", "sp_obtener_vehiculos"),
            ("/vehiculos", "post"): ("Vehículos", "sp_crear_vehiculo"),
            ("/vehiculos/{id_vehiculo}", "get"): ("Vehículos", "sp_obtener_vehiculo"),
            ("/vehiculos/{id_vehiculo}", "put"): ("Vehículos", "sp_actualizar_vehiculo"),
            ("/vehiculos/{id_vehiculo}", "delete"): ("Vehículos", "sp_eliminar_vehiculo"),
            ("/vehiculos/{id_vehiculo}/comandos", "post"): ("Comandos", "sp_crear_comando"),
            ("/vehiculos/{id_vehiculo}/comandos", "get"): ("Comandos", "sp_obtener_comandos_vehiculo"),
            ("/vehiculos/{id_vehiculo}/comandos/{id_comando}", "put"): ("Comandos", "sp_actualizar_comando"),
            ("/vehiculos/{id_vehiculo}/comandos/{id_comando}", "delete"): ("Comandos", "sp_eliminar_comando"),
        }
        documented = {(path, method) for path, operations in schema["paths"].items() for method in operations}
        self.assertEqual(documented, set(expected))
        for (path, method), (tag, procedure) in expected.items():
            with self.subTest(path=path, method=method):
                operation = schema["paths"][path][method]
                self.assertEqual(operation["tags"], [tag])
                self.assertIn(procedure, operation["description"])
                self.assertIn("503", operation["responses"])
                if method in ("post", "put"):
                    self.assertIn("requestBody", operation)
                if method == "delete":
                    self.assertNotIn("content", operation["responses"]["204"])
                    self.assertIn("401", operation["responses"])
                    self.assertIn("403", operation["responses"])


if __name__ == "__main__":
    unittest.main()
