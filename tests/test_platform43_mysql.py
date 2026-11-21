"""Integración con MySQL aislado. Todos los casos inhiben hardware real."""
from concurrent.futures import ThreadPoolExecutor
from os import getenv
from secrets import token_urlsafe
from threading import Barrier

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from app.config.settings import get_settings
from scripts.local43 import IsolatedDatabase, isolated_app

pytestmark = pytest.mark.skipif(getenv("IOT43_MYSQL_TEST") != "1", reason="Requiere MySQL aislado, puerto 33343.")

P = "/plataforma"
ORIGIN = {"origin": "http://127.0.0.1:4173"}


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def headers(session):
    return {"Authorization": "Bearer " + session["token"]}


@pytest.fixture
def platform(monkeypatch):
    from app.platform43.security import PASSWORDS

    monkeypatch.setenv("PLATFORM43_ENABLED", "true")
    monkeypatch.setenv("PLATFORM43_DISPATCH", "false")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    db = IsolatedDatabase()
    suffix = token_urlsafe(7).lower()
    password = token_urlsafe(18)
    email = f"admin-{suffix}@example.test"
    with db.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO iot_usuario(email,nombre,clave,rol) VALUES(%s,%s,%s,'administrador')",
                       (email, f"Admin {suffix}", PASSWORDS.hash(password)))
    with TestClient(isolated_app(), client=(f"{suffix}.example.test", 50000)) as client:
        admin = ok(client.post(f"{P}/sesion", json={"email": email, "password": password}))
        yield client, db, admin, suffix, password
    get_settings.cache_clear()


def add_client(client, admin, suffix, password, alias):
    email = f"{alias}-{suffix}@example.test"
    record = ok(client.post(f"{P}/usuarios", headers=headers(admin),
                            json={"email": email, "nombre": alias, "password": password}), 201)
    return {**ok(client.post(f"{P}/sesion", json={"email": email, "password": password})), **record}, email


def model(client, admin, suffix):
    data = {"sku": suffix, "nombre": "Montacargas", "publico": True, "capacidades": [
        {"codigo": 0, "nombre": "DETENER"},
        {"codigo": 1, "nombre": "AVANZAR", "invitado": True},
        {"codigo": 8, "nombre": "DERECHA"},
        {"codigo": 64, "nombre": "DEMO_ORIGINAL"},
    ]}
    return ok(client.post(f"{P}/modelos", headers=headers(admin), json=data), 201)["id"]


def new_unit(client, admin, model_id, series, state="inventario"):
    data = {"modelo": model_id, "serie": series, "nombre": series, "estado": state}
    response = client.post(f"{P}/unidades", headers=headers(admin), json=data)
    return ok(response, 201)["id_vehiculo"]


def ticket(client, user, vehicle):
    return ok(client.post(f"{P}/vehiculos/{vehicle}/ticket", headers=headers(user)), 201)["ticket"]


def socket(client, vehicle, value):
    return client.websocket_connect(f"{P}/ws/vehiculos/{vehicle}", subprotocols=["iot43", value], headers=ORIGIN.copy())


def test_identity_password_rate_limit_and_revocation(platform):
    from app.platform43.security import digest

    client, db, admin, suffix, password = platform
    assert ok(client.get(f"{P}/perfil", headers=headers(admin)))["rol"] == "administrador"
    assert client.get(f"{P}/dashboard").status_code == 401
    assert client.get("/vehiculos", headers={"X-API-Key": "public-example"}).status_code == 404
    assert client.post(f"{P}/vehiculos/1/movimientos", headers={"X-API-Key": "public-example"},
                       json={"id_comando": 1}).status_code == 401
    assert client.get("/openapi.json").json()["info"]["version"] == "4.3.0"
    assert ok(client.get("/health/database"))["database"] == "available"
    user, email = add_client(client, admin, suffix, password, "usuario")
    assert client.get(f"{P}/dashboard", headers=headers(user)).status_code == 403
    invalid = client.post(f"{P}/usuarios", headers=headers(admin),
                          json={"email": "z@example.test", "nombre": "Z", "password": "weak123"})
    assert invalid.status_code == 422 and "weak123" not in invalid.text
    with db.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT clave FROM iot_usuario WHERE id=%s", (user["id"],))
        assert cursor.fetchone()["clave"].startswith("$argon2id$")
        cursor.execute("UPDATE iot_sesion SET vence=UTC_TIMESTAMP(6) WHERE huella=%s", (digest(user["token"]),))
    assert client.get(f"{P}/perfil", headers=headers(user)).status_code == 401
    for _ in range(7):
        assert client.post(f"{P}/sesion", json={"email": email, "password": "incorrecta"}).status_code == 401
    assert client.post(f"{P}/sesion", json={"email": email, "password": password}).status_code == 429
    another, email = add_client(client, admin, suffix, password, "otra")
    new_password = token_urlsafe(24)
    ok(client.put(f"{P}/perfil/password", headers=headers(another), json={"actual": password, "nueva": new_password}), 204)
    assert client.get(f"{P}/perfil", headers=headers(another)).status_code == 401
    changed = ok(client.post(f"{P}/sesion", json={"email": email, "password": new_password}))
    ok(client.delete(f"{P}/sesion", headers=headers(changed)), 204)
    assert client.get(f"{P}/perfil", headers=headers(changed)).status_code == 401


def test_device_provisioning_and_revocation(platform, tmp_path):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.platform43.security import digest
    from app.platform43.sockets import verify_device
    from scripts.manage43 import device, revoke_device

    client, db, admin, suffix, _ = platform
    model_id = model(client, admin, suffix)
    vehicle = new_unit(client, admin, model_id, suffix)
    other = new_unit(client, admin, model_id, suffix + "-otra")
    path = tmp_path / "Platform43Secrets.h"
    args = SimpleNamespace(header=str(path), vehicle=vehicle)
    device(db, args)
    token = path.read_text(encoding="ascii").split('"')[1]
    key = digest(token)
    verify_device(db, vehicle, key)
    with pytest.raises(HTTPException):
        verify_device(db, other, key)
    with pytest.raises(FileExistsError):
        device(db, args)
    verify_device(db, vehicle, key)
    # Only the in-process ASGI test socket can connect. No movement requests are made.
    client.app.state.websocket_manager.device_connections = True
    assert client.app.state.websocket_manager.dispatch is False
    url = f"{P}/ws/dispositivos/{vehicle}"
    credential = {"Authorization": f"Bearer {token}"}
    for target, supplied in ((url, headers(admin)), (f"{P}/ws/dispositivos/{other}", credential),
                             (url, {**credential, **ORIGIN})):
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(target, headers=supplied.copy()):
                pytest.fail("Canal de dispositivo accesible sin su credencial y unidad.")
        assert rejected.value.code == 1008
    with client.websocket_connect(url, headers=credential.copy()) as ws:
        revoke_device(db, args)
        with pytest.raises(WebSocketDisconnect) as revoked:
            ws.receive_json()
        assert revoked.value.code == 1008
    with pytest.raises(HTTPException):
        verify_device(db, vehicle, key)


def test_inventory_access_history_demo_and_websocket(platform):
    client, db, admin, suffix, password = platform
    a, _ = add_client(client, admin, suffix, password, "a")
    b, _ = add_client(client, admin, suffix, password, "b")
    model_id = model(client, admin, suffix)
    vehicle = new_unit(client, admin, model_id, suffix)
    assert ok(client.get(f"{P}/unidades", params={"q": suffix}, headers=headers(admin)))[0]["vehiculo"] == vehicle
    duplicate = client.post(f"{P}/unidades", headers=headers(admin),
                            json={"modelo": model_id, "serie": suffix, "nombre": "Duplicada"})
    assert duplicate.status_code == 409
    base = f"{P}/vehiculos/{vehicle}"
    assignment = f"{P}/unidades/{vehicle}/asignacion"
    ok(client.put(assignment, headers=headers(admin), json={"version": 1, "propietario": a["id"]}))
    assert ok(client.get(f"{P}/vehiculos", headers=headers(a)))[0]["id_vehiculo"] == vehicle
    for outsider in (admin, b):
        for path in (base, base + "/historial", f"{P}/vehiculos/2147483647"):
            assert client.get(path, headers=headers(outsider)).status_code == 404
        assert client.post(base + "/ticket", headers=headers(outsider)).status_code == 404
        assert client.post(base + "/movimientos", headers=headers(outsider), json={"id_comando": 1}).status_code == 404
    commands = {row["codigo"]: row["id_comando"] for row in ok(client.get(base + "/comandos", headers=headers(a)))}
    assert 64 not in commands
    assert ok(client.get(base + "/despacho", headers=headers(a)))["demo_original"] is False
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id_comando FROM comandos WHERE id_vehiculo=%s AND codigo=64", (vehicle,))
        original = cursor.fetchone()["id_comando"]
    response = client.post(base + "/movimientos", headers=headers(a), json={"id_comando": original})
    assert response.status_code == 409
    assert response.json()["detail"] == "DEMO original requiere despacho autorizado y firmware compatible conectado."
    value = ticket(client, a, vehicle)
    demo = {"nombre": "Prueba", "pasos": [{"codigo": 1, "duracion_ms": 35, "pausa_ms": 10}]}
    private = base + "/demos/privadas"
    demo_id = ok(client.post(private, headers=headers(a), json=demo), 201)["id"]
    factory = ok(client.post(f"{P}/modelos/{model_id}/demos", headers=headers(admin), json=demo), 201)["id"]
    assert {row["id_demo"] for row in ok(client.get(base + "/demos", headers=headers(a)))} == {demo_id, factory}
    assert ok(client.get(private, headers=headers(a)))[0]["pasos"] == demo["pasos"]
    with socket(client, vehicle, value) as ws:
        assert ws.receive_json()["tipo_evento"] == "estado_actual"
        move = ok(client.post(base + "/movimientos", headers=headers(a), json={"id_comando": commands[1]}))
        assert move["conectado"] is False and ws.receive_json()["tipo_evento"] == "movimiento"
        path = base + f"/demos/{demo_id}"
        ok(client.post(path + "/ejecutar", headers=headers(a)), 202)
        assert [ws.receive_json()["tipo_evento"] for _ in range(3)] == ["demo_inicio", "demo_movimiento", "demo_fin"]
        demo["pasos"][0]["duracion_ms"] = 3000
        ok(client.put(private + f"/{demo_id}", headers=headers(a), json=demo))
        ok(client.post(path + "/ejecutar", headers=headers(a)), 202)
        assert ws.receive_json()["tipo_evento"] == "demo_inicio"
        ok(client.post(path + "/cancelar", headers=headers(a)))
        events = [ws.receive_json()["tipo_evento"]]
        if events[-1] == "demo_movimiento":
            events.append(ws.receive_json()["tipo_evento"])
        assert events[-1] == "demo_cancelada"
    with pytest.raises(WebSocketDisconnect), socket(client, vehicle, value):
        pytest.fail("El ticket se reutilizó")
    reconnect_ticket = ticket(client, a, vehicle)
    with socket(client, vehicle, reconnect_ticket) as ws:
        assert ws.receive_json()["tipo_evento"] == "estado_actual"
        history = ok(client.get(base + "/historial", headers=headers(a)))
        assert len(history) == 1 and history[0]["codigo"] == 1
        ok(client.put(assignment, headers=headers(admin), json={"version": 2, "propietario": b["id"]}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert client.get(base, headers=headers(a)).status_code == 404
    assert ok(client.get(base + "/historial", headers=headers(b))) == []
    assert ok(client.get(base + "/demos", headers=headers(b)))[0]["id_demo"] == factory
    assert len(ok(client.get(f"{P}/unidades/{vehicle}/titularidad", headers=headers(admin)))) == 2
    assert any(row["accion"] == "titularidad" and row["vehiculo"] == vehicle
               for row in ok(client.get(f"{P}/auditoria", headers=headers(admin))))


def test_update_guest_permissions_on_referenced_model(platform):
    client, _, admin, suffix, password = platform
    buyer, _ = add_client(client, admin, suffix, password, "comprador")
    caps = [
        {"codigo": code, "nombre": name, "invitado": code == 8}
        for code, name in (
            (0, "DETENER"), (1, "AVANZAR"), (2, "RETROCEDER"), (4, "IZQUIERDA"),
            (5, "AVANZAR_IZQUIERDA"), (6, "RETROCEDER_IZQUIERDA"), (8, "DERECHA"),
            (9, "AVANZAR_DERECHA"), (10, "RETROCEDER_DERECHA"), (16, "LUCES"),
            (32, "VELOCIDAD"), (64, "DEMO_ORIGINAL"), (128, "CLAXON"),
        )
    ]
    data = {"sku": suffix, "nombre": "HJ2025-1D", "publico": True, "capacidades": caps}
    model_id = ok(client.post(f"{P}/modelos", headers=headers(admin), json=data), 201)["id"]
    path = f"{P}/modelos/{model_id}"
    sold = new_unit(client, admin, model_id, suffix)
    exhibit = new_unit(client, admin, model_id, suffix + "-exhibicion", "exhibicion")
    ok(client.put(f"{P}/unidades/{sold}/asignacion", headers=headers(admin),
                  json={"propietario": buyer["id"], "version": 1}))
    ok(client.post(path + "/demos", headers=headers(admin), json={
        "nombre": "DEMO de fábrica", "pasos": [{"codigo": 1, "duracion_ms": 1000}],
    }), 201)
    guest = ok(client.post(f"{P}/invitados/{exhibit}"), 201)
    buyer_path = f"{P}/vehiculos/{sold}/comandos"
    guest_path = f"{P}/vehiculos/{exhibit}/comandos"
    buyer_commands = ok(client.get(buyer_path, headers=headers(buyer)))
    assert {row["codigo"] for row in ok(client.get(guest_path, headers=headers(guest)))} == {0, 8}
    units = ok(client.get(f"{P}/unidades", params={"q": suffix}, headers=headers(admin)))
    demos = ok(client.get(path + "/demos", headers=headers(admin)))

    updated = [dict(cap, invitado=True) if cap["codigo"] in (0, 1) else cap for cap in caps]
    payload = {**data, "capacidades": updated}
    assert client.put(path, headers=headers(buyer), json=payload).status_code == 403
    assert client.put(path, headers=headers(guest), json=payload).status_code == 403
    assert ok(client.put(path, headers=headers(admin), json=payload)) == {"id": model_id}
    assert ok(client.put(path, headers=headers(admin), json=payload)) == {"id": model_id}
    edited = next(item for item in ok(client.get(f"{P}/modelos", params={"despues": model_id - 1},
                                                headers=headers(admin))) if item["id"] == model_id)
    assert edited["capacidades"] == updated
    assert ok(client.get(buyer_path, headers=headers(buyer))) == buyer_commands
    assert {row["codigo"] for row in ok(client.get(guest_path, headers=headers(guest)))} == {0, 1, 8}
    assert ok(client.get(f"{P}/unidades", params={"q": suffix}, headers=headers(admin))) == units
    assert ok(client.get(path + "/demos", headers=headers(admin))) == demos
    assert client.app.state.websocket_manager.dispatch is False
    assert (
        ok(client.get(f"{P}/vehiculos/{exhibit}/despacho", headers=headers(guest)))["estado"] == "inhibido"
    )

    removed = [cap for cap in updated if cap["codigo"] != 1]
    renamed = [dict(cap, nombre="AVANCE") if cap["codigo"] == 1 else cap for cap in updated]
    private = [dict(cap, invitado=True) if cap["codigo"] == 128 else cap for cap in updated]
    for changed, status in ((removed, 409), (renamed, 409), (private, 422)):
        assert client.put(path, headers=headers(admin), json={**data, "capacidades": changed}).status_code == status


def test_guests_exclusivity_expiration_and_cleanup(platform):
    from app.platform43.security import digest

    client, db, admin, suffix, _ = platform
    model_id = model(client, admin, suffix)
    vehicle = new_unit(client, admin, model_id, suffix, "exhibicion")
    private = new_unit(client, admin, model_id, suffix + "-privada")
    public = ok(client.get(f"{P}/catalogo"))["unidades"]
    assert vehicle in {row["vehiculo"] for row in public} and private not in {row["vehiculo"] for row in public}
    assert client.post(f"{P}/invitados/{private}").status_code == 404
    gate = Barrier(2)

    def claim(_):
        gate.wait(timeout=5)
        return client.post(f"{P}/invitados/{vehicle}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sorted(result.status_code for result in results) == [201, 409]
    guest = next(result.json() for result in results if result.status_code == 201)
    base = f"{P}/vehiculos/{vehicle}"
    commands = ok(client.get(base + "/comandos", headers=headers(guest)))
    assert {row["codigo"] for row in commands} == {0, 1}
    assert all(row["activo"] is True for row in commands)
    with db.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id_comando FROM comandos WHERE id_vehiculo=%s AND codigo=64", (vehicle,))
        original = cursor.fetchone()["id_comando"]
    assert client.post(base + "/movimientos", headers=headers(guest), json={"id_comando": original}).status_code == 404
    assert ok(client.get(base + "/historial", headers=headers(guest))) == []
    assert client.get(f"{P}/vehiculos/{private}", headers=headers(guest)).status_code == 404
    value = ticket(client, guest, vehicle)
    with socket(client, vehicle, value) as ws:
        assert ws.receive_json()["estado"] is None
        with db.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE iot_sesion SET vence=UTC_TIMESTAMP(6) WHERE huella=%s", (digest(guest["token"]),))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert client.get(base, headers=headers(guest)).status_code == 401
    second = ok(client.post(f"{P}/invitados/{vehicle}"), 201)
    ok(client.delete(f"{P}/reservas/{vehicle}", headers=headers(admin)), 204)
    assert client.get(base, headers=headers(second)).status_code == 401
    assert any(item["accion"] == "reserva_liberada_stop" and item["resultado"] == "inhibido"
               for item in ok(client.get(f"{P}/auditoria", headers=headers(admin))))
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{P}/ws/dispositivos/{vehicle}"):
        pytest.fail("El despacho físico debía permanecer inhibido")
