"""Operaciones comerciales, bajas lógicas y titularidad."""
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pymysql.err import IntegrityError

from .models import Access, Client, Id, Model, NewUnit, Transfer, Unit
from .security import (Admin, Database, GUEST_CODES, PASSWORDS, all_rows, audit,
                       conflict, identity, login_email, missing, one, unit)

router = APIRouter(prefix="/plataforma", tags=["4.3 Administración"])
UNIT_COLUMNS = "u.vehiculo,u.serie,u.modelo,u.propietario,u.estado,u.version,v.nombre,m.nombre AS nombre_modelo"


def execute(cursor, sql, params):
    try:
        cursor.execute(sql, params)
    except IntegrityError as error:
        if error.args[0] == 1062:
            raise conflict("El identificador ya existe.") from None
        raise


@contextmanager
def admin_transaction(db, actor):
    with db.transaction() as connection, connection.cursor() as cursor:
        if identity(cursor, actor.key).role != "administrador":
            raise HTTPException(403, "Se requiere el rol administrador.")
        yield cursor


@router.get("/dashboard")
def dashboard(actor: Admin, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return one(cursor, """
            SELECT (SELECT COUNT(*) FROM iot_modelo WHERE activo) modelos,
             (SELECT COUNT(*) FROM iot_unidad WHERE estado<>'baja') unidades,
             (SELECT COUNT(*) FROM iot_unidad WHERE estado='vendida') vendidas,
             (SELECT COUNT(*) FROM iot_unidad u JOIN iot_modelo m ON u.modelo=m.id
              WHERE u.estado='exhibicion' AND m.publico AND m.activo AND NOT EXISTS(
                SELECT 1 FROM iot_reserva r WHERE r.vehiculo=u.vehiculo)) exhibicion,
             (SELECT COUNT(*) FROM iot_usuario WHERE rol='usuario' AND activo) clientes,
             (SELECT COUNT(*) FROM iot_demo WHERE activo) demos
        """)


@router.get("/usuarios")
def clients(actor: Admin, db: Database, despues: int = 0):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return all_rows(cursor, "SELECT id,email,nombre,rol,activo FROM iot_usuario WHERE id>%s ORDER BY id LIMIT 100", (despues,))


@router.post("/usuarios", status_code=201)
def register_client(data: Client, actor: Admin, db: Database):
    encoded = PASSWORDS.hash(data.password.get_secret_value())
    with admin_transaction(db, actor) as cursor:
        execute(cursor, "INSERT INTO iot_usuario(email,nombre,clave,rol) VALUES(%s,%s,%s,'usuario')",
                (login_email(data.email), data.nombre, encoded))
        client = cursor.lastrowid
        audit(cursor, "cliente_creado", user=actor.user)
    return {"id": client}


@router.put("/usuarios/{client}/acceso", status_code=204)
def client_access(client: Id, data: Access, actor: Admin, db: Database):
    with admin_transaction(db, actor) as cursor:
        if not one(cursor, "SELECT id FROM iot_usuario WHERE id=%s AND rol='usuario' FOR UPDATE", (client,)):
            raise missing()
        cursor.execute("UPDATE iot_usuario SET activo=%s WHERE id=%s", (data.activo, client))
        if not data.activo:
            cursor.execute("UPDATE iot_sesion SET revocada=UTC_TIMESTAMP(6) WHERE usuario=%s AND revocada IS NULL", (client,))
        audit(cursor, "cliente_acceso", "activo" if data.activo else "bloqueado", user=actor.user)


def capabilities(cursor, model, *, lock=False):
    return all_rows(cursor, "SELECT codigo,nombre,invitado FROM iot_capacidad WHERE modelo=%s ORDER BY codigo"
                    + (" FOR UPDATE" if lock else ""), (model,))


@router.get("/modelos")
def models(actor: Admin, db: Database, despues: int = 0):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        rows = all_rows(cursor, "SELECT * FROM iot_modelo WHERE id>%s ORDER BY id LIMIT 100", (despues,))
        for row in rows:
            row["capacidades"] = capabilities(cursor, row["id"])
        return rows


def save_model(cursor, data, model=None):
    caps = {item.codigo: (item.nombre, item.invitado) for item in data.capacidades}
    if (len(caps) != len(data.capacidades) or len({name.casefold() for name, _ in caps.values()}) != len(caps)
            or caps.get(0, ("", False))[0] != "DETENER"
            or any(guest and code not in GUEST_CODES for code, (_, guest) in caps.items())):
        raise HTTPException(422, "Capacidades duplicadas, DETENER ausente o comando no autorizado para invitados.")
    fields = (data.sku, data.nombre, data.descripcion, data.publico, data.activo)
    if model is None:
        execute(cursor, "INSERT INTO iot_modelo(sku,nombre,descripcion,publico,activo) VALUES(%s,%s,%s,%s,%s)", fields)
        model = cursor.lastrowid
    else:
        if not one(cursor, "SELECT id FROM iot_modelo WHERE id=%s FOR UPDATE", (model,)):
            raise missing()
        previous = {row["codigo"]: (row["nombre"], bool(row["invitado"]))
                    for row in capabilities(cursor, model, lock=True)}
        same_catalog = {code: name for code, (name, _) in previous.items()} == {
            code: name for code, (name, _) in caps.items()
        }
        if not same_catalog and (
            one(cursor, "SELECT 1 FROM iot_unidad WHERE modelo=%s LIMIT 1 FOR UPDATE", (model,))
            or one(cursor, "SELECT 1 FROM iot_demo WHERE modelo=%s LIMIT 1 FOR UPDATE", (model,))
        ):
            raise conflict("Las capacidades del modelo ya tienen referencias.")
        if not data.activo and one(cursor, "SELECT 1 FROM iot_unidad WHERE modelo=%s AND estado<>'baja' LIMIT 1", (model,)):
            raise conflict("El modelo aún tiene unidades activas.")
        if not data.publico and one(cursor, "SELECT 1 FROM iot_unidad WHERE modelo=%s AND estado='exhibicion' LIMIT 1", (model,)):
            raise conflict("Retira las unidades de exhibición primero.")
        execute(cursor, "UPDATE iot_modelo SET sku=%s,nombre=%s,descripcion=%s,publico=%s,activo=%s WHERE id=%s", (*fields, model))
        if same_catalog:
            changed_permissions = [(guest, model, code) for code, (_, guest) in caps.items()
                                   if guest != previous[code][1]]
            if changed_permissions:
                cursor.executemany("UPDATE iot_capacidad SET invitado=%s WHERE modelo=%s AND codigo=%s",
                                   changed_permissions)
            return model
        cursor.execute("DELETE FROM iot_capacidad WHERE modelo=%s", (model,))
    cursor.executemany("INSERT INTO iot_capacidad(modelo,codigo,nombre,invitado) VALUES(%s,%s,%s,%s)",
                       [(model, code, name, guest) for code, (name, guest) in caps.items()])
    return model


@router.post("/modelos", status_code=201)
def add_model(data: Model, actor: Admin, db: Database):
    with admin_transaction(db, actor) as cursor:
        model = save_model(cursor, data)
        audit(cursor, "modelo_creado", user=actor.user)
    return {"id": model}


@router.put("/modelos/{model}")
def update_model(model: Id, data: Model, actor: Admin, db: Database):
    with admin_transaction(db, actor) as cursor:
        save_model(cursor, data, model)
        audit(cursor, "modelo_actualizado", user=actor.user)
    return {"id": model}


@router.get("/unidades")
def units(actor: Admin, db: Database, q: str = "", estado: str = "", despues: int = 0):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return all_rows(cursor, f"""
            SELECT {UNIT_COLUMNS} FROM iot_unidad u JOIN vehiculos v ON v.id_vehiculo=u.vehiculo
            JOIN iot_modelo m ON m.id=u.modelo WHERE u.vehiculo>%s
            AND (%s='' OR u.estado=%s) AND (LOCATE(%s,u.serie)>0 OR LOCATE(%s,v.nombre)>0 OR %s='')
            ORDER BY u.vehiculo LIMIT 100
        """, (despues, estado, estado, q, q, q))


def validate_model(cursor, data):
    model = one(cursor, "SELECT activo,publico FROM iot_modelo WHERE id=%s FOR UPDATE", (data.modelo,))
    if not model:
        raise missing()
    if (data.estado != "baja" and not model["activo"]) or (data.estado == "exhibicion" and not model["publico"]):
        raise conflict("El estado no es compatible con el modelo.")


def check_commands(cursor, vehicle, model):
    counts = one(cursor, """
        SELECT COUNT(*) AS total,COUNT(c.id_comando) AS compatibles FROM iot_capacidad a
        LEFT JOIN comandos c ON c.id_vehiculo=%s AND c.codigo=a.codigo AND c.nombre=a.nombre AND c.activo
        WHERE a.modelo=%s
    """, (vehicle, model))
    if not counts["total"] or counts["total"] != counts["compatibles"]:
        raise conflict("El catálogo operativo de la unidad no coincide con el modelo.")


def history_boundary(cursor, vehicle):
    return one(cursor, "SELECT COALESCE(MAX(id_historial),0) n FROM historial_comandos WHERE id_vehiculo=%s", (vehicle,))["n"]


@router.post("/unidades", status_code=201)
def add_unit(data: NewUnit, actor: Admin, db: Database):
    with admin_transaction(db, actor) as cursor:
        validate_model(cursor, data)
        vehicle = data.id_vehiculo_existente
        active = data.estado != "baja"
        if vehicle is None:
            cursor.execute("INSERT INTO vehiculos(nombre,activo) VALUES(%s,%s)", (data.nombre, active))
            vehicle = cursor.lastrowid
            cursor.execute("""
                INSERT INTO comandos(id_vehiculo,nombre,codigo)
                SELECT %s,nombre,codigo FROM iot_capacidad WHERE modelo=%s
            """, (vehicle, data.modelo))
        elif not one(cursor, "SELECT id_vehiculo FROM vehiculos WHERE id_vehiculo=%s FOR UPDATE", (vehicle,)):
            raise missing()
        check_commands(cursor, vehicle, data.modelo)
        execute(cursor, "INSERT INTO iot_unidad(vehiculo,serie,modelo,estado,historial_desde) VALUES(%s,%s,%s,%s,%s)",
                (vehicle, data.serie, data.modelo, data.estado, history_boundary(cursor, vehicle)))
        cursor.execute("UPDATE vehiculos SET nombre=%s,activo=%s WHERE id_vehiculo=%s", (data.nombre, active, vehicle))
        audit(cursor, "unidad_creada", user=actor.user, vehicle=vehicle)
    return {"id_vehiculo": vehicle}


@router.put("/unidades/{vehicle}")
def update_unit(vehicle: Id, data: Unit, actor: Admin, db: Database):
    with admin_transaction(db, actor) as cursor:
        row = unit(cursor, vehicle, lock=True)
        if row["propietario"] or one(cursor, "SELECT 1 FROM iot_reserva WHERE vehiculo=%s", (vehicle,)):
            raise conflict("Retira la asignación o reserva antes de editar la unidad.")
        validate_model(cursor, data)
        check_commands(cursor, vehicle, data.modelo)
        execute(cursor, "UPDATE iot_unidad SET serie=%s,modelo=%s,estado=%s,version=version+1 WHERE vehiculo=%s",
                (data.serie, data.modelo, data.estado, vehicle))
        cursor.execute("UPDATE vehiculos SET nombre=%s,activo=%s WHERE id_vehiculo=%s",
                       (data.nombre, data.estado != "baja", vehicle))
        audit(cursor, "unidad_actualizada", user=actor.user, vehicle=vehicle)
    return {"id_vehiculo": vehicle}


def check_transfer(cursor, vehicle, data, *, lock=False):
    row = unit(cursor, vehicle, lock=lock)
    if row["version"] != data.version or row["estado"] not in ("inventario", "vendida"):
        raise conflict("La unidad cambió o no está disponible para asignar.")
    if data.propietario and not one(cursor,
        "SELECT id FROM iot_usuario WHERE id=%s AND rol='usuario' AND activo" + (" FOR UPDATE" if lock else ""),
        (data.propietario,)):
        raise missing()
    return row


def changing_owner(vehicle, data, actor, db):
    with admin_transaction(db, actor) as cursor:
        return check_transfer(cursor, vehicle, data)["propietario"] != data.propietario


def transfer_owner(vehicle, data, actor, db):
    with admin_transaction(db, actor) as cursor:
        row = check_transfer(cursor, vehicle, data, lock=True)
        if row["propietario"] == data.propietario:
            return {"version": row["version"]}
        boundary = history_boundary(cursor, vehicle)
        cursor.execute("UPDATE estado_vehiculo SET id_comando=NULL,conectado=FALSE WHERE id_vehiculo=%s", (vehicle,))
        cursor.execute("UPDATE iot_unidad SET propietario=%s,estado=%s,version=version+1,historial_desde=%s WHERE vehiculo=%s",
                       (data.propietario, "vendida" if data.propietario else "inventario", boundary, vehicle))
        cursor.execute("INSERT INTO iot_titularidad(vehiculo,propietario,anterior,actor) VALUES(%s,%s,%s,%s)",
                       (vehicle, data.propietario, row["propietario"], actor.user))
        audit(cursor, "titularidad", user=actor.user, vehicle=vehicle)
    return {"version": row["version"] + 1}


@router.put("/unidades/{vehicle}/asignacion")
async def transfer(vehicle: Id, data: Transfer, actor: Admin, db: Database, request: Request):
    state = request.app.state
    async with state.platform_lock:
        if await run_in_threadpool(changing_owner, vehicle, data, actor, db):
            if state.websocket_manager.dispatch_status(vehicle)["demo_original_pendiente"]:
                raise conflict("Interrumpe la DEMO original con CLAXON antes de transferir la unidad.")
            await state.demo_execution_manager.cancel_vehicle(vehicle)
            await state.websocket_manager.stop_device(vehicle)
        return await run_in_threadpool(transfer_owner, vehicle, data, actor, db)


@router.get("/unidades/{vehicle}/titularidad")
def ownership(vehicle: Id, actor: Admin, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        unit(cursor, vehicle)
        return all_rows(cursor, "SELECT id,propietario,anterior,actor,fecha FROM iot_titularidad WHERE vehiculo=%s ORDER BY id DESC LIMIT 100", (vehicle,))


@router.get("/auditoria")
def audit_log(actor: Admin, db: Database, antes: int = 0):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return all_rows(cursor, """
            SELECT id,fecha,actor,vehiculo,accion,resultado FROM iot_auditoria
            WHERE %s=0 OR id<%s ORDER BY id DESC LIMIT 100
        """, (antes, antes))
