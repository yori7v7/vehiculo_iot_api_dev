"""Catálogo de fábrica por modelo y DEMOS privadas ligadas a una titularidad."""
from fastapi import APIRouter, HTTPException

from app.models.demo_execution import DemoExecutionPlan
from app.models.demos import DemoMovementResponse, DemoResponse
from app.repositories.state import StateRepository
from app.database.procedures import StoredProcedureExecutor
from app.services.demo_execution import DemoExecutionCancelled
from .admin import admin_transaction
from .models import Demo, HORN_MAX_MS, Id
from .security import Actor, Admin, Database, all_rows, audit, authorized_unit, conflict, missing, one

router = APIRouter(prefix="/plataforma", tags=["4.3 DEMOS"])


def descriptions(cursor, model, vehicle=None, owner=None, version=None):
    return all_rows(cursor, """
        SELECT id,modelo,vehiculo,nombre,descripcion,activo FROM iot_demo WHERE modelo=%s AND
        ((vehiculo IS NULL AND activo) OR (vehiculo=%s AND propietario=%s AND version_unidad=%s))
        ORDER BY id
    """, (model, vehicle, owner, version))


def demo_entry(cursor, row, actor, demo):
    entry = one(cursor, """
        SELECT id,nombre,descripcion,activo FROM iot_demo WHERE id=%s AND modelo=%s AND activo AND
        (vehiculo IS NULL OR (vehiculo=%s AND propietario=%s AND version_unidad=%s))
    """, (demo, row["modelo"], row["vehiculo"], actor.user, row["version"]))
    if actor.role != "usuario" or not entry:
        raise missing()
    return entry


def steps(cursor, demo):
    return all_rows(cursor, "SELECT codigo,duracion_ms,pausa_ms FROM iot_paso WHERE demo=%s ORDER BY orden", (demo,))


def operational_steps(cursor, row, demo):
    plan = all_rows(cursor, """
        SELECT p.id AS id_demo_movimiento,p.orden,p.codigo,p.duracion_ms,p.pausa_ms,
        c.id_comando,c.nombre comando FROM iot_paso p
        LEFT JOIN iot_capacidad a ON a.modelo=%s AND a.codigo=p.codigo
        LEFT JOIN comandos c ON c.id_vehiculo=%s AND c.codigo=p.codigo AND c.nombre=a.nombre AND c.activo
        WHERE p.demo=%s ORDER BY p.orden
    """, (row["modelo"], row["vehiculo"], demo))
    if not plan or any(item["id_comando"] is None or item["codigo"] == 64
                       or (item["codigo"] == 128 and item["duracion_ms"] > HORN_MAX_MS) for item in plan):
        raise conflict("La secuencia no es compatible con los comandos activos de la unidad.")
    return plan


def save(cursor, data, model, *, row=None, owner=None, demo=None):
    caps = {cap["codigo"] for cap in all_rows(cursor, "SELECT codigo FROM iot_capacidad WHERE modelo=%s", (model,))}
    if not {step.codigo for step in data.pasos} <= caps:
        raise HTTPException(422, "La secuencia incluye comandos incompatibles con el modelo.")
    fields = (data.nombre, data.descripcion, data.activo)
    if demo is None:
        cursor.execute("""
            INSERT INTO iot_demo(modelo,vehiculo,propietario,version_unidad,nombre,descripcion,activo)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
        """, (model, row["vehiculo"] if row else None, owner, row["version"] if row else None, *fields))
        demo = cursor.lastrowid
    else:
        expected = one(cursor, """
            SELECT 1 FROM iot_demo WHERE id=%s AND modelo=%s AND vehiculo<=>%s AND propietario<=>%s
            AND version_unidad<=>%s FOR UPDATE
        """, (demo, model, row["vehiculo"] if row else None, owner, row["version"] if row else None))
        if not expected:
            raise missing()
        cursor.execute("UPDATE iot_demo SET nombre=%s,descripcion=%s,activo=%s WHERE id=%s", (*fields, demo))
        cursor.execute("DELETE FROM iot_paso WHERE demo=%s", (demo,))
    cursor.executemany("""
        INSERT INTO iot_paso(demo,orden,codigo,duracion_ms,pausa_ms) VALUES(%s,%s,%s,%s,%s)
    """, [(demo, order, step.codigo, step.duracion_ms, step.pausa_ms) for order, step in enumerate(data.pasos, 1)])
    return demo


@router.get("/modelos/{model}/demos")
def factory_list(model: Id, actor: Admin, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        if not one(cursor, "SELECT 1 FROM iot_modelo WHERE id=%s", (model,)):
            raise missing()
        rows = all_rows(cursor, "SELECT id,nombre,descripcion,activo FROM iot_demo WHERE modelo=%s AND vehiculo IS NULL ORDER BY id", (model,))
        for row in rows:
            row["pasos"] = steps(cursor, row["id"])
        return rows


def write_factory(db, actor, model, data, demo=None):
    with admin_transaction(db, actor) as cursor:
        if not one(cursor, "SELECT 1 FROM iot_modelo WHERE id=%s AND activo FOR UPDATE", (model,)):
            raise missing()
        demo = save(cursor, data, model, demo=demo)
        audit(cursor, "demo_fabrica_guardada", user=actor.user)
    return {"id": demo}


@router.post("/modelos/{model}/demos", status_code=201)
def factory_new(model: Id, data: Demo, actor: Admin, db: Database):
    return write_factory(db, actor, model, data)


@router.put("/modelos/{model}/demos/{demo}")
def factory_edit(model: Id, demo: Id, data: Demo, actor: Admin, db: Database):
    return write_factory(db, actor, model, data, demo)


@router.get("/vehiculos/{vehicle}/demos/privadas")
def private_list(vehicle: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        if current.role != "usuario":
            raise missing()
        rows = all_rows(cursor, """
            SELECT id,nombre,descripcion,activo FROM iot_demo
            WHERE vehiculo=%s AND propietario=%s AND version_unidad=%s ORDER BY id
        """, (vehicle, actor.user, row["version"]))
        for demo in rows:
            demo["pasos"] = steps(cursor, demo["id"])
        return rows


def write_private(db, actor, vehicle, data, demo=None):
    with db.transaction() as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle, lock=True)
        if current.role != "usuario":
            raise missing()
        demo = save(cursor, data, row["modelo"], demo=demo, row=row, owner=current.user)
        audit(cursor, "demo_privada_guardada", user=current.user, vehicle=vehicle)
    return {"id": demo}


@router.post("/vehiculos/{vehicle}/demos/privadas", status_code=201)
def private_new(vehicle: Id, data: Demo, actor: Actor, db: Database):
    return write_private(db, actor, vehicle, data)


@router.put("/vehiculos/{vehicle}/demos/privadas/{demo}")
def private_edit(vehicle: Id, demo: Id, data: Demo, actor: Actor, db: Database):
    return write_private(db, actor, vehicle, data, demo)


class AuthorizedDemo:
    """Adaptador del ejecutor de 4.2 con revalidación de cada paso."""
    def __init__(self, db, actor):
        self.db = db
        self.actor = actor
        self.version = None

    def prepare(self, vehicle, demo):
        with self.db.transaction(read_only=True) as connection, connection.cursor() as cursor:
            actor, row = authorized_unit(cursor, self.actor.key, vehicle)
            if not row["activo"] or not row["modelo_activo"]:
                raise conflict("Unidad inactiva.")
            self.version = row["version"]
            entry = demo_entry(cursor, row, actor, demo)
            return DemoExecutionPlan(
                demo=DemoResponse(id_demo=demo, id_vehiculo=vehicle, nombre=entry["nombre"],
                                  descripcion=entry["descripcion"], activo=True),
                movimientos=tuple(DemoMovementResponse(**step) for step in operational_steps(cursor, row, demo)),
            )

    def apply_step(self, plan, movement, *, should_cancel):
        vehicle = plan.demo.id_vehiculo
        with self.db.transaction() as connection, connection.cursor() as cursor:
            actor, row = authorized_unit(cursor, self.actor.key, vehicle, lock=True)
            if self.version != row["version"]:
                raise DemoExecutionCancelled()
            demo_entry(cursor, row, actor, plan.demo.id_demo)
            if movement.model_dump() not in operational_steps(cursor, row, plan.demo.id_demo):
                raise conflict("La secuencia cambió durante la ejecución.")
            if should_cancel():
                raise DemoExecutionCancelled()
            repository = StateRepository(StoredProcedureExecutor(connection))
            repository.update(vehicle, movement.id_comando, False)
            state = repository.get(vehicle)
            if should_cancel():
                raise DemoExecutionCancelled()
            return state
