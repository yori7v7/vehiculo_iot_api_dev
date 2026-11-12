"""Contratos del modo simulado probados directamente mediante ASGI."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from pydantic import SecretStr, ValidationError

from app.config.settings import PROJECT_ROOT, Settings, get_settings
from app.public_control.domain import MOVEMENT_CODES, PublicControlError
from app.public_control.http import MAX_BODY_BYTES, PAGES_ORIGIN, ScopedControlMiddleware, router
from app.routers.vehicles import get_vehicle_service, router as vehicles_router


ADMIN = "/admin/vehiculos/1/control-publico"
PUBLIC = "/publico/vehiculos/1"
TEST_KEY = "clave-administrativa-ficticia-pruebas"
FAKE_TOKEN = "T" * 43
NOW = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)
OWNER = [("X-API-Key", TEST_KEY)]
ORIGIN = [("Origin", PAGES_ORIGIN)]
BEARER = [("Authorization", f"Bearer {FAKE_TOKEN}")]


def window_body() -> dict:
    return {
        "id_solicitud": str(uuid4()), "duracion_seg": 1200,
        "supervision_confirmada": True,
    }


def move_body(**values) -> dict:
    return {
        "id_solicitud": str(uuid4()), "secuencia": 1, "epoca_operacion": 1,
        "duracion_ms": 100, "accion": "AVANZAR_DERECHA", **values,
    }


def status_body() -> dict:
    return {
        "id_vehiculo": 1, "habilitado": True, "estado": "disponible",
        "vence_ventana_en": NOW, "hora_servidor": NOW, "revision": 1, "simulado": True,
    }


def turn_body() -> dict:
    return {
        "id_vehiculo": 1, "estado": "activo", "vence_en": NOW,
        "vence_inactividad_en": NOW, "hora_servidor": NOW, "epoca_operacion": 1,
        "siguiente_secuencia": 1, "ultima_operacion": None, "simulado": True,
    }


class PublicControlSettingsTests(unittest.TestCase):
    def test_defaults_and_strict_explicit_flags(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            self.assertFalse(settings.control_publico_enabled)
            self.assertFalse(settings.control_publico_simulation)
            self.assertIsNone(settings.control_publico_sqlite_path)
        for value in ("yes", "1", "on", "true "):
            with self.subTest(value=value), patch.dict(
                os.environ, {"CONTROL_PUBLICO_ENABLED": value}, clear=True,
            ):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None)

    def test_explicit_simulation_only_in_development_with_external_absolute_path(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            path = Path(temp) / "control.sqlite3"
            enabled = Settings(
                _env_file=None, control_publico_enabled=True,
                control_publico_simulation=True, control_publico_sqlite_path=path,
            )
            self.assertTrue(enabled.control_publico_simulation)
            self.assertEqual(enabled.control_publico_sqlite_path, path)
            for overrides in (
                {"control_publico_enabled": False}, {"control_publico_simulation": False},
                {"app_env": "production"}, {"control_publico_sqlite_path": None},
                {"control_publico_sqlite_path": Path("control.sqlite3")},
                {"control_publico_sqlite_path": PROJECT_ROOT / "control.sqlite3"},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                    Settings(_env_file=None, **(enabled.model_dump() | overrides))
            with patch.dict(os.environ, {
                "CONTROL_PUBLICO_ENABLED": "true", "CONTROL_PUBLICO_SIMULATION": "true",
                "CONTROL_PUBLICO_SQLITE_PATH": str(path), "CONTROL_PUBLICO_VEHICLE_IDS": "[1,2]",
            }, clear=True):
                self.assertEqual(Settings(_env_file=None).control_publico_vehicle_ids, (1, 2))


class PublicControlHTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.application = FastAPI()
        self.application.add_middleware(ScopedControlMiddleware)
        self.application.include_router(router)
        self.application.include_router(vehicles_router)
        self.application.state.public_control = None
        self.application.state.public_control_simulation = False
        self.application.state.public_control_unavailable = False
        settings = Settings(_env_file=None, api_key=SecretStr(TEST_KEY))
        self.application.dependency_overrides[get_settings] = lambda: settings
        self.vehicle_service = Mock(side_effect=AssertionError("No se debe resolver el servicio real."))
        self.application.dependency_overrides[get_vehicle_service] = self.vehicle_service
        no_rds = patch("app.database.connection.pymysql.connect", side_effect=AssertionError("RDS"))
        database = no_rds.start()
        self.addCleanup(no_rds.stop)
        self.addCleanup(database.assert_not_called)

    def use_simulation(self) -> Mock:
        service = Mock()
        self.application.state.public_control = service
        self.application.state.public_control_simulation = True
        return service

    async def request(self, method, path, *, headers=(), payload=None, chunks=None, client="127.0.0.1"):
        incoming_headers = [(key.lower().encode(), value.encode()) for key, value in headers]
        if payload is not None:
            incoming_headers.append((b"content-type", b"application/json"))
            chunks = [json.dumps(payload).encode()]
        requests = iter(chunks or [b""])
        chunk = next(requests, None)
        messages = []

        async def receive():
            nonlocal chunk
            if chunk is None:
                return {"type": "http.disconnect"}
            body, chunk = chunk, next(requests, None)
            return {"type": "http.request", "body": body, "more_body": chunk is not None}

        async def send(message):
            messages.append(message)

        path, _, query = path.partition("?")
        await self.application(
            {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
                "query_string": query.encode(), "root_path": "", "headers": incoming_headers,
                "client": (client, 12345), "server": ("test.invalid", 443),
            },
            receive, send,
        )
        start = messages[0]
        body = b"".join(message.get("body", b"") for message in messages[1:])
        result_headers = {key.decode(): value.decode() for key, value in start["headers"]}
        if result_headers.get("content-type") == "application/json":
            body = json.loads(body)
        return start["status"], result_headers, body

    async def test_disabled_reads_closed_and_mutations_unavailable(self):
        status, headers, body = await self.request("GET", PUBLIC + "/control", client="192.0.2.10")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual((body["habilitado"], body["estado"], body["simulado"]), (False, "cerrado", False))
        status, _, body = await self.request("GET", ADMIN, headers=OWNER)
        self.assertEqual((status, body["estado"], body["parada"]), (200, "cerrado", None))
        status, _, body = await self.request("GET", ADMIN + "/auditoria", headers=OWNER)
        self.assertEqual((status, body), (200, []))
        for method, path, headers, payload in (
            ("PUT", ADMIN + "/ventana", OWNER, window_body()),
            ("POST", PUBLIC + "/sesion", ORIGIN, {}),
        ):
            status, headers, body = await self.request(method, path, headers=headers, payload=payload)
            self.assertEqual((status, body["codigo"]), (503, "control_deshabilitado"))
            self.assertEqual(headers["cache-control"], "no-store")
        self.application.state.public_control_unavailable = True
        status, _, body = await self.request("GET", PUBLIC + "/control")
        self.assertEqual((status, body["codigo"]), (503, "servicio_no_disponible"))

    async def test_all_admin_routes_require_existing_key_and_do_not_resolve_service(self):
        service = self.use_simulation()
        for method, path, payload in (
            ("GET", ADMIN, None), ("GET", ADMIN + "/auditoria", None),
            ("PUT", ADMIN + "/ventana", window_body()),
            ("DELETE", ADMIN + "/ventana", None),
            ("POST", ADMIN + "/revocacion", {"id_solicitud": str(uuid4())}),
        ):
            for headers, expected in (
                ([], 401), (BEARER, 401), (OWNER * 2, 403),
                ([("X-API-Key", "incorrecta-ficticia")], 403), (OWNER + BEARER, 403),
            ):
                with self.subTest(method=method, path=path, expected=expected):
                    status, response_headers, body = await self.request(
                        method, path, headers=headers, payload=payload,
                    )
                    self.assertEqual(status, expected)
                    self.assertEqual(set(body), {"detail"})
                    self.assertEqual(response_headers["cache-control"], "no-store")
                    if status == 401:
                        self.assertTrue(response_headers["www-authenticate"].startswith("ApiKey"))
        self.assertEqual(service.mock_calls, [])

    async def test_admin_bindings_and_statuses(self):
        service = self.use_simulation()
        admin = dict(
            status_body(), inicio_ventana_en=NOW, id_turno_auditoria=None,
            turno_vence_en=None, parada=None, motivo_bloqueo=None,
        )
        stop = {
            "id_operacion": uuid4(), "id_vehiculo": 1, "epoca_operacion": 2,
            "estado": "pendiente", "solicitada_en": NOW, "verificada_en": None, "simulado": True,
        }
        service.admin_status.return_value = admin
        service.audit.return_value = []
        service.enable.return_value = admin
        service.disable.side_effect = [(202, stop), (200, admin)]
        service.revoke.return_value = stop
        status, _, _ = await self.request("GET", ADMIN, headers=OWNER)
        self.assertEqual(status, 200)
        service.admin_status.assert_called_once_with(1)
        status, _, _ = await self.request("GET", ADMIN + "/auditoria?limite=2", headers=OWNER)
        self.assertEqual(status, 200)
        service.audit.assert_called_once_with(1, limit=2)
        request = window_body()
        status, _, _ = await self.request("PUT", ADMIN + "/ventana", headers=OWNER, payload=request)
        self.assertEqual(status, 200)
        self.assertEqual(str(service.enable.call_args.args[1]), request["id_solicitud"])
        self.assertEqual(service.enable.call_args.kwargs, {"duration_seconds": 1200, "supervision": True})
        for expected in (202, 200):
            status, _, body = await self.request("DELETE", ADMIN + "/ventana", headers=OWNER)
            self.assertEqual(status, expected)
            self.assertIn("id_operacion" if expected == 202 else "vence_ventana_en", body)
        status, _, _ = await self.request(
            "POST", ADMIN + "/revocacion", headers=OWNER, payload={"id_solicitud": str(uuid4())},
        )
        self.assertEqual(status, 202)

    async def test_guest_routes_require_origin_and_disjoint_credentials(self):
        service = self.use_simulation()
        for headers in ([], [("Origin", "https://otro.invalid")], ORIGIN * 2, ORIGIN + OWNER, ORIGIN + BEARER):
            status, _, _ = await self.request("POST", PUBLIC + "/sesion", headers=headers, payload={})
            self.assertEqual(status, 403)
        for headers in ([], BEARER * 2, [("Authorization", "Bearer ficticio")], BEARER + OWNER):
            status, response_headers, _ = await self.request("GET", PUBLIC + "/sesion", headers=headers)
            self.assertEqual(status, 403 if OWNER[0] in headers else 401)
            if status == 401:
                self.assertEqual(response_headers["www-authenticate"], "Bearer")
        status, _, _ = await self.request("DELETE", PUBLIC + "/sesion", headers=BEARER)
        self.assertEqual(status, 403)
        status, _, _ = await self.request("POST", "/vehiculos", headers=BEARER, payload={"nombre": "Ficticio"})
        self.assertEqual(status, 401)
        self.vehicle_service.assert_not_called()
        self.assertEqual(service.mock_calls, [])

    async def test_guest_successful_bindings_and_allowlist(self):
        service = self.use_simulation()
        service.status.return_value = status_body()
        service.acquire.return_value = dict(turn_body(), token=FAKE_TOKEN)
        service.session.return_value = turn_body()
        stop = {
            "id_operacion": uuid4(), "id_vehiculo": 1, "epoca_operacion": 2,
            "estado": "pendiente", "solicitada_en": NOW, "verificada_en": None, "simulado": True,
        }
        service.stop.return_value = service.release.return_value = stop
        service.move.return_value = {
            "id_operacion": uuid4(), "id_vehiculo": 1, "epoca_operacion": 1,
            "estado": "aceptada", "creada_en": NOW, "simulado": True,
        }
        status, _, body = await self.request("GET", PUBLIC + "/control")
        self.assertEqual((status, body["estado"]), (200, "disponible"))
        status, headers, body = await self.request("POST", PUBLIC + "/sesion", headers=ORIGIN, payload={})
        self.assertEqual((status, body["token"]), (201, FAKE_TOKEN))
        self.assertEqual(headers["cache-control"], "no-store")
        client_key = service.acquire.call_args.kwargs["client_key"]
        self.assertRegex(client_key, r"^[0-9a-f]{64}$")
        self.assertNotIn("127.0.0.1", client_key)
        status, _, body = await self.request("GET", PUBLIC + "/sesion", headers=BEARER)
        self.assertEqual(status, 200)
        self.assertNotIn("token", body)
        service.session.assert_called_once_with(1, FAKE_TOKEN)
        for action in MOVEMENT_CODES:
            request = move_body(accion=action)
            status, _, body = await self.request(
                "POST", PUBLIC + "/sesion/acciones", headers=ORIGIN + BEARER, payload=request,
            )
            self.assertEqual((status, body["simulado"]), (202, True))
            self.assertEqual(service.move.call_args.args[3:], (1, 1, 100, action))
        status, _, body = await self.request(
            "POST", PUBLIC + "/sesion/parada", headers=ORIGIN + BEARER,
            payload={"id_solicitud": str(uuid4())},
        )
        self.assertEqual((status, body["estado"]), (202, "pendiente"))
        status, _, _ = await self.request("DELETE", PUBLIC + "/sesion", headers=ORIGIN + BEARER)
        self.assertEqual(status, 202)
        service.release.assert_called_once_with(1, FAKE_TOKEN)

    async def test_bounded_validation_sanitizes_inputs_and_requires_strict_values(self):
        service = self.use_simulation()
        leaked = "ficticio-secreto-de-entrada"
        for payload in (
            move_body(accion=leaked), move_body(duracion_ms=99), move_body(duracion_ms=501),
            move_body(duracion_ms="100"), move_body(secuencia=True), move_body(epoca_operacion=0),
            move_body(id_comando=1), move_body(accion="DETENER"), move_body(accion="LUZ"),
        ):
            status, headers, body = await self.request(
                "POST", PUBLIC + "/sesion/acciones", headers=ORIGIN + BEARER, payload=payload,
            )
            self.assertEqual((status, body["codigo"]), (422, "entrada_invalida"))
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertNotIn(leaked, repr(body))
        for payload in (
            window_body() | {"duracion_seg": 1199},
            window_body() | {"duracion_seg": "1200"},
            window_body() | {"supervision_confirmada": 1},
            window_body() | {"supervision_confirmada": False},
        ):
            status, _, _ = await self.request("PUT", ADMIN + "/ventana", headers=OWNER, payload=payload)
            self.assertEqual(status, 422)
        status, _, body = await self.request(
            "POST", PUBLIC + "/sesion", headers=ORIGIN + [("Content-Type", "application/json")],
            chunks=[b'{"bad":', b'"' + leaked.encode() + b''],
        )
        self.assertEqual(status, 422)
        self.assertNotIn(leaked, repr(body))
        for headers, chunks in (
            ([("Content-Length", str(MAX_BODY_BYTES + 1))], [b""]),
            ([], [b"a" * MAX_BODY_BYTES, b"b"]),
        ):
            status, response_headers, body = await self.request(
                "POST", PUBLIC + "/sesion", headers=ORIGIN + headers, chunks=chunks,
            )
            self.assertEqual((status, body["codigo"]), (413, "cuerpo_demasiado_grande"))
            self.assertEqual(response_headers["cache-control"], "no-store")
        self.assertEqual(service.mock_calls, [])

    async def test_cors_scoped_and_simulation_loopback_gate(self):
        service = self.use_simulation()
        preflight = [("Access-Control-Request-Method", "POST"),
                     ("Access-Control-Request-Headers", "authorization, content-type")]
        status, headers, _ = await self.request("OPTIONS", PUBLIC + "/sesion", headers=ORIGIN + preflight)
        self.assertEqual(status, 200)
        self.assertEqual(headers["access-control-allow-origin"], PAGES_ORIGIN)
        self.assertIn("Authorization", headers["access-control-allow-headers"])
        self.assertNotIn("X-API-Key", headers["access-control-allow-headers"])
        self.assertNotIn("access-control-allow-credentials", headers)
        self.assertEqual(headers["cache-control"], "no-store")
        status, headers, _ = await self.request("OPTIONS", "/vehiculos", headers=ORIGIN + preflight)
        self.assertEqual(status, 400)
        self.assertIn("X-API-Key", headers["access-control-allow-headers"])
        self.assertNotIn("Authorization", headers["access-control-allow-headers"])
        status, headers, _ = await self.request(
            "OPTIONS", PUBLIC + "/sesion", headers=[("Origin", "https://otro.invalid")] + preflight,
        )
        self.assertEqual(status, 400)
        self.assertNotIn("access-control-allow-origin", headers)
        status, _, body = await self.request(
            "POST", PUBLIC + "/sesion", headers=ORIGIN + [("X-Forwarded-For", "127.0.0.1")],
            payload={}, client="192.0.2.10",
        )
        self.assertEqual((status, body["codigo"]), (403, "solo_simulacion_local"))
        self.assertEqual(service.mock_calls, [])

    async def test_control_errors_and_logs_are_safe(self):
        service = self.use_simulation()
        service.acquire.side_effect = PublicControlError(429, "limite", "Espera antes de pedir otro turno.", 2)
        status, headers, body = await self.request("POST", PUBLIC + "/sesion", headers=ORIGIN, payload={})
        self.assertEqual((status, body["reintentar_en_seg"]), (429, 2))
        self.assertEqual(headers["retry-after"], "2")
        self.assertIn("Retry-After", headers["access-control-expose-headers"])
        service.session.side_effect = RuntimeError(FAKE_TOKEN)
        with self.assertLogs("app.public_control.http", level="ERROR") as logs:
            status, headers, body = await self.request("GET", PUBLIC + "/sesion", headers=BEARER)
        self.assertEqual(status, 503)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertNotIn(FAKE_TOKEN, repr(body))
        self.assertNotIn(FAKE_TOKEN, repr(logs.output))

    def test_openapi_separates_admin_and_guest_authentication(self):
        schema = self.application.openapi()
        paths = schema["paths"]
        admin = [operation for path, methods in paths.items() if path.startswith("/admin/")
                 for operation in methods.values()]
        self.assertEqual(len(admin), 5)
        for operation in admin:
            self.assertEqual(operation["security"], [{"LocalApiKey": []}])
        guest = {f"{method}:{path}": operation for path, methods in paths.items()
                 if path.startswith("/publico/") for method, operation in methods.items()}
        self.assertEqual(len(guest), 6)
        for route, operation in guest.items():
            if route.endswith("/control") or (route.startswith("post:") and route.endswith("/sesion")):
                self.assertFalse(operation.get("security"))
            else:
                self.assertEqual(operation["security"], [{"GuestControlBearer": []}])


if __name__ == "__main__":
    unittest.main()
