"""Integración del ciclo de vida sin RDS, sockets ni hardware."""

import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.config.settings import Settings, get_settings
from app.public_control.domain import PublicControlError


def application_for(settings):
    importlib.import_module("app.routers.health")
    importlib.import_module("app.security.api_key")
    with patch("app.config.settings.get_settings", return_value=settings):
        main = importlib.import_module("app.main")
    with patch.object(main, "get_settings", return_value=settings):
        app = main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def simulation_settings(database: Path) -> Settings:
    return Settings(
        _env_file=None, app_env="development", api_key="clave-ficticia-runtime",
        control_publico_enabled=True, control_publico_simulation=True,
        control_publico_sqlite_path=database,
    )


def test_disabled_lifespan_never_instantiates_sqlite_or_the_dispatcher():
    app = application_for(Settings(_env_file=None, app_env="production"))

    async def scenario():
        with (
            patch("app.public_control.runtime.PublicControlRepository") as repository,
            patch("app.public_control.runtime.SimulatedVehicleDispatcher") as dispatcher,
            patch("app.database.connection.pymysql.connect") as mysql,
        ):
            async with app.router.lifespan_context(app):
                assert app.state.public_control is None
                assert not app.state.public_control_simulation
            repository.assert_not_called()
            dispatcher.assert_not_called()
            mysql.assert_not_called()

    asyncio.run(scenario())


def test_second_application_is_blocked_until_exclusive_owner_releases_file(tmp_path):
    settings = simulation_settings(tmp_path / "coordinator.sqlite3")
    first, second = application_for(settings), application_for(settings)

    async def scenario():
        with patch("app.database.connection.pymysql.connect") as mysql:
            async with first.router.lifespan_context(first):
                assert first.state.public_control is not None
                async with second.router.lifespan_context(second):
                    assert second.state.public_control is None
                    assert second.state.public_control_unavailable
                    assert second.state.public_control_simulation
            async with second.router.lifespan_context(second):
                assert second.state.public_control is not None
                assert not second.state.public_control_unavailable
            mysql.assert_not_called()

    asyncio.run(scenario())


def test_runtime_restart_closes_window_and_invalidates_guest_token(tmp_path):
    settings = simulation_settings(tmp_path / "recovery.sqlite3")
    first, replacement = application_for(settings), application_for(settings)

    async def scenario():
        with patch("app.database.connection.pymysql.connect") as mysql:
            async with first.router.lifespan_context(first):
                service = first.state.public_control
                service.enable(1, str(uuid4()), 1200, True)
                turn = service.acquire(1)
                assert turn["token"]
                assert service.status(1)["habilitado"]
            async with replacement.router.lifespan_context(replacement):
                service = replacement.state.public_control
                assert not service.status(1)["habilitado"]
                with pytest.raises(PublicControlError) as error:
                    service.session(1, turn["token"])
                assert error.value.status == 401
            mysql.assert_not_called()

    asyncio.run(scenario())


async def request(app, method, path, *, body=None, headers=()):
    content = b"" if body is None else json.dumps(body).encode("utf-8")
    responses = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": content, "more_body": False}

    async def send(message):
        responses.append(message)

    await app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"content-type", b"application/json"), *headers],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }, receive, send)
    start = next(message for message in responses if message["type"] == "http.response.start")
    raw = b"".join(message.get("body", b"") for message in responses if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), json.loads(raw)


def test_real_asgi_routes_drive_only_the_local_simulator(tmp_path):
    app = application_for(simulation_settings(tmp_path / "api.sqlite3"))
    admin = "/admin/vehiculos/1/control-publico"
    public = "/publico/vehiculos/1"
    owner = [(b"x-api-key", b"clave-ficticia-runtime")]
    origin = [(b"origin", b"https://yori7v7.github.io")]

    async def scenario():
        with patch("app.database.connection.pymysql.connect") as mysql:
            async with app.router.lifespan_context(app):
                status, _, state = await request(app, "PUT", admin + "/ventana", headers=owner, body={
                    "id_solicitud": str(uuid4()), "duracion_seg": 1200, "supervision_confirmada": True,
                })
                assert status == 200 and state["habilitado"] and state["simulado"]
                status, headers, turn = await request(app, "POST", public + "/sesion", headers=origin, body={})
                assert status == 201 and headers[b"cache-control"] == b"no-store"
                assert b"set-cookie" not in headers
                guest = [*origin, (b"authorization", b"Bearer " + turn["token"].encode())]
                status, _, movement = await request(app, "POST", public + "/sesion/acciones", headers=guest, body={
                    "id_solicitud": str(uuid4()), "secuencia": turn["siguiente_secuencia"],
                    "epoca_operacion": turn["epoca_operacion"], "duracion_ms": 500, "accion": "AVANZAR_IZQUIERDA",
                })
                assert status == 202 and movement["simulado"]
                status, _, rejected = await request(app, "POST", "/vehiculos/1/movimientos", headers=owner, body={"id_comando": 2})
                assert status == 503 and "simulación" in rejected["detail"]
                status, _, stopped = await request(app, "POST", public + "/sesion/parada", headers=guest, body={
                    "id_solicitud": str(uuid4()),
                })
                assert status == 202 and stopped["simulado"] and stopped["estado"] == "verificada"
                status, _, audit = await request(app, "GET", admin + "/auditoria", headers=owner)
                assert status == 200 and audit and turn["token"] not in json.dumps(audit)
                status, _, stopped = await request(app, "DELETE", public + "/sesion", headers=guest)
                assert status == 202 and stopped["simulado"]
                status, _, state = await request(app, "GET", public + "/control", headers=origin)
                assert status == 200 and state["estado"] == "disponible"
                status, _, result = await request(app, "DELETE", admin + "/ventana", headers=owner)
                assert status == 202 and result["estado"] == "verificada"
                status, _, state = await request(app, "DELETE", admin + "/ventana", headers=owner)
                assert status == 200 and state["estado"] == "cerrado"
            mysql.assert_not_called()

    asyncio.run(scenario())
