"""Entornos y aplicación completa con configuración ficticia, sin .env ni RDS."""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.models.health import HealthResponse


class EnvironmentSettingsTests(unittest.TestCase):
    def test_development_remains_the_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings(_env_file=None).app_env, "development")

    def test_production_is_loaded_from_environment_without_a_dotenv_file(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.app_env, "production")

    def test_unknown_environment_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, app_env="invalid-environment")

    def test_health_schema_accepts_both_supported_environments(self):
        for environment in ("development", "production"):
            with self.subTest(environment=environment):
                response = HealthResponse(status="ok", service="API de pruebas", environment=environment)
                self.assertEqual(response.model_dump()["environment"], environment)
        self.assertEqual(
            HealthResponse.model_json_schema()["properties"]["environment"]["enum"],
            ["development", "production"],
        )


class ProductionApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.dict(os.environ, {}, clear=True):
            self.settings = Settings(_env_file=None, app_env="production", app_name="API de pruebas")
        # Ejecutar el punto de entrada con get_settings sustituido ANTES de
        # importarlo evita abrir .env, incluso durante app = create_app().
        self.settings_patch = patch("app.config.settings.get_settings", return_value=self.settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        for target in ("app.config.settings.Settings", "app.database.connection.pymysql.connect"):
            guard = patch(target, side_effect=AssertionError("No cargar .env ni abrir RDS en pruebas."))
            guarded = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(guarded.assert_not_called)
        source = Path(__file__).resolve().parents[1] / "app" / "main.py"
        specification = importlib.util.spec_from_file_location("production_main_test", source)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        self.application = module.app
        self.application.dependency_overrides[get_settings] = lambda: self.settings

    async def test_production_root_returns_200_without_database_access(self):
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await self.application(
            {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "GET", "scheme": "https", "path": "/", "raw_path": b"/",
                "query_string": b"", "root_path": "", "headers": [],
                "client": ("127.0.0.1", 12345), "server": ("test.invalid", 443),
            },
            receive, send,
        )
        self.assertEqual(messages[0]["status"], 200)
        body = b"".join(message.get("body", b"") for message in messages)
        self.assertEqual(json.loads(body), {
            "status": "ok", "service": "API de pruebas", "environment": "production",
        })

    def test_production_schema_keeps_api_key_contract_and_public_health(self):
        schema = self.application.openapi()
        self.assertIn("desarrollo y producción", schema["info"]["description"])
        scheme = schema["components"]["securitySchemes"]["LocalApiKey"]
        self.assertEqual(scheme["name"], "X-API-Key")
        self.assertNotIn("local", scheme["description"].lower())
        self.assertFalse(schema["paths"]["/"]["get"].get("security"))
        self.assertEqual(
            schema["paths"]["/vehiculos/{id_vehiculo}/movimientos"]["post"]["security"],
            [{"LocalApiKey": []}],
        )


if __name__ == "__main__":
    unittest.main()
