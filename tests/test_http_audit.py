"""Auditoría transversal de OpenAPI y errores sin importar main ni cargar .env."""

import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.errors.database import (
    DatabaseConfigurationError, DatabaseConflictError, DatabaseError,
    DatabaseResultError, DatabaseTransactionError, DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.errors.handlers import register_exception_handlers
from app.routers import commands, demo_execution, demos, health, history, movement, state, vehicles


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VEHICLE = "/vehiculos/{id_vehiculo}"
DEMO = VEHICLE + "/demos/{id_demo}"
MOVEMENT = DEMO + "/movimientos/{id_demo_movimiento}"
PROTECTED_OPERATIONS = {
    ("post", VEHICLE + "/movimientos"),
    ("post", DEMO + "/ejecutar"),
    ("post", DEMO + "/cancelar"),
    ("delete", VEHICLE),
    ("delete", VEHICLE + "/comandos/{id_comando}"),
    ("delete", DEMO),
    ("delete", MOVEMENT),
}
SP_ARITY = {
    "sp_crear_vehiculo": 4, "sp_obtener_vehiculos": 0, "sp_obtener_vehiculo": 1,
    "sp_actualizar_vehiculo": 6, "sp_eliminar_vehiculo": 1,
    "sp_crear_comando": 4, "sp_obtener_comandos_vehiculo": 1,
    "sp_actualizar_comando": 5, "sp_eliminar_comando": 1,
    "sp_actualizar_estado": 3, "sp_obtener_estado": 1,
    "sp_registrar_historial": 3, "sp_obtener_historial": 1,
    "sp_crear_demo": 3, "sp_obtener_demos": 1,
    "sp_actualizar_demo": 4, "sp_eliminar_demo": 1,
    "sp_agregar_movimiento_demo": 5, "sp_obtener_movimientos_demo": 1,
    "sp_actualizar_movimiento_demo": 5, "sp_eliminar_movimiento_demo": 1,
}


def isolated_application():
    application = FastAPI()
    for module in (health, vehicles, commands, state, history, movement, demos, demo_execution):
        application.include_router(module.router)
    register_exception_handlers(application)
    return application


class HttpSchemaAuditTests(unittest.TestCase):
    def setUp(self):
        self.settings_patch = patch(
            "app.config.settings.Settings", side_effect=AssertionError("La auditoría no debe leer .env.")
        )
        self.settings_guard = self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.connection_patch = patch(
            "app.database.connection.pymysql.connect", side_effect=AssertionError("La auditoría no debe abrir sockets.")
        )
        self.connection_guard = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.application = isolated_application()
        self.schema = self.application.openapi()

    def tearDown(self):
        self.settings_guard.assert_not_called()
        self.connection_guard.assert_not_called()

    def operations(self):
        return [
            (method, path, operation)
            for path, methods in self.schema["paths"].items()
            for method, operation in methods.items()
        ]

    def test_all_24_operations_have_tags_descriptions_and_unique_operation_ids(self):
        operations = self.operations()
        self.assertEqual(len(operations), 24)
        self.assertEqual({method: sum(item[0] == method for item in operations) for method in ("get", "post", "put", "delete")}, {
            "get": 9, "post": 7, "put": 4, "delete": 4,
        })
        self.assertEqual(len({operation["operationId"] for _, _, operation in operations}), 24)
        self.assertEqual({tag for _, _, operation in operations for tag in operation["tags"]}, {
            "Salud", "Vehículos", "Comandos", "Estado", "Historial", "Movimientos", "DEMO",
        })
        for method, path, operation in operations:
            with self.subTest(method=method, path=path):
                self.assertTrue(operation["summary"].strip())
                self.assertTrue(operation["description"].strip())

    def test_exactly_seven_operations_require_the_header_security_scheme(self):
        secured = {
            (method, path) for method, path, operation in self.operations()
            if operation.get("security")
        }
        self.assertEqual(secured, PROTECTED_OPERATIONS)
        scheme = self.schema["components"]["securitySchemes"]["LocalApiKey"]
        self.assertEqual((scheme["type"], scheme["in"], scheme["name"]), ("apiKey", "header", "X-API-Key"))
        for method, path, operation in self.operations():
            with self.subTest(method=method, path=path):
                if (method, path) in PROTECTED_OPERATIONS:
                    self.assertTrue({"401", "403", "503"}.issubset(operation["responses"]))
                else:
                    self.assertFalse({"401", "403"} & set(operation["responses"]))

    def test_four_delete_successes_have_no_json_or_response_body_schema(self):
        for method, path, operation in self.operations():
            if method == "delete":
                with self.subTest(path=path):
                    self.assertIn("204", operation["responses"])
                    self.assertNotIn("content", operation["responses"]["204"])
                    self.assertNotIn("200", operation["responses"])

    def test_all_documented_errors_have_json_models_including_automatic_422(self):
        for method, path, operation in self.operations():
            with self.subTest(method=method, path=path):
                self.assertIn("500", operation["responses"])
                for code, response in operation["responses"].items():
                    if int(code) >= 400:
                        self.assertIn("application/json", response["content"])
                        self.assertTrue(response["content"]["application/json"]["schema"])
                if "{" in path or "requestBody" in operation:
                    self.assertEqual(
                        operation["responses"]["422"]["content"]["application/json"]["schema"],
                        {"$ref": "#/components/schemas/HTTPValidationError"},
                    )

    def test_codes_follow_the_flow_without_inventing_400_or_unrelated_conflicts(self):
        for _, _, operation in self.operations():
            self.assertNotIn("400", operation["responses"])
        for method, path in (("put", DEMO), ("delete", DEMO), ("delete", MOVEMENT), ("post", DEMO + "/cancelar")):
            with self.subTest(method=method, path=path):
                self.assertNotIn("409", self.schema["paths"][path][method]["responses"])
        for path, methods in self.schema["paths"].items():
            if "get" in methods:
                self.assertFalse(methods["get"].get("security"))
                self.assertNotIn("409", methods["get"]["responses"])

    def test_descriptions_name_persistence_procedures_and_cancel_has_no_new_procedure(self):
        for method, path, operation in self.operations():
            if path != "/" and not path.endswith("/cancelar"):
                with self.subTest(method=method, path=path):
                    self.assertRegex(operation["description"], r"\bsp_[a-z_]+")
        self.assertIn("Sin cuerpo ni SP propio", self.schema["paths"][DEMO + "/cancelar"]["post"]["description"])


class StoredProcedureAuditTests(unittest.TestCase):
    def test_all_sp_calls_use_literal_sql_names_and_exact_parameter_counts(self):
        called = []
        for directory in ("repositories", "services"):
            for path in (PROJECT_ROOT / "app" / directory).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"):
                        continue
                    with self.subTest(path=path.name, line=node.lineno):
                        self.assertIsInstance(node.args[0], ast.Constant)
                        name = node.args[0].value
                        self.assertIn(name, SP_ARITY)
                        if len(node.args) == 1:
                            arity = 0
                        else:
                            self.assertIsInstance(node.args[1], (ast.Tuple, ast.List))
                            arity = len(node.args[1].elts)
                        self.assertEqual(arity, SP_ARITY[name])
                        called.append(name)
        self.assertEqual(set(called), set(SP_ARITY))
        self.assertEqual(len(called), 22)

    def test_sp_audit_document_lists_exactly_the_21_sql_procedures(self):
        document = (PROJECT_ROOT / "docs" / "auditoria_sp.md").read_text(encoding="utf-8-sig")
        documented = re.findall(r"^\| \d+ \| `(sp_\w+)`", document, flags=re.MULTILINE)
        self.assertEqual(len(documented), 21)
        self.assertEqual(set(documented), set(SP_ARITY))


class SafeErrorAuditTests(unittest.IsolatedAsyncioTestCase):
    async def request_error(self, error):
        application = FastAPI()
        register_exception_handlers(application)

        @application.get("/fault")
        def fail():
            raise error

        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "GET", "scheme": "http", "path": "/fault",
            "raw_path": b"/fault", "root_path": "", "query_string": b"", "headers": [],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        propagated = None
        try:
            await application(scope, receive, send)
        except Exception as caught:
            # ServerErrorMiddleware repropaga después de enviar el JSON del
            # handler genérico; ASGI permite comprobar esa respuesta sin red.
            propagated = caught
        response = next(message for message in messages if message["type"] == "http.response.start")
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        self.assertIn((b"content-type", b"application/json"), response["headers"])
        return response["status"], json.loads(content), propagated

    async def test_unexpected_500_is_static_json_and_does_not_expose_exception_text(self):
        error = RuntimeError("host privado password privado SQL privado")
        status, content, propagated = await self.request_error(error)
        self.assertEqual(status, 500)
        self.assertEqual(content, {"detail": "No fue posible procesar la solicitud."})
        self.assertIs(propagated, error)

    async def test_controlled_errors_preserve_their_real_status_and_public_shape(self):
        for error, expected in (
            (ResourceNotFoundError("El recurso no existe."), 404),
            (ResourceConflictError("El recurso está inactivo."), 409),
            (DatabaseConflictError(), 409), (DatabaseConfigurationError(), 503),
            (DatabaseUnavailableError(), 503), (DatabaseTransactionError(), 503),
            (StoredProcedureExecutionError(), 500), (DatabaseResultError(), 500),
            (DatabaseError(), 500),
        ):
            with self.subTest(error_type=type(error).__name__):
                status, content, propagated = await self.request_error(error)
                self.assertEqual(status, expected)
                self.assertEqual(content, {"detail": str(error)})
                self.assertIsNone(propagated)


if __name__ == "__main__":
    unittest.main()
