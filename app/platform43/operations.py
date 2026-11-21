"""Contratos de control y monitoreo de 4.2 detrás de autorización por unidad."""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.database.procedures import StoredProcedureExecutor
from app.models.commands import CommandResponse
from app.models.demo_execution import DemoExecutionResponse
from app.models.demos import DemoResponse, DemoMovementResponse
from app.models.history import HistoryResponse
from app.models.movement import MovementRequest, MovementResponse
from app.models.state import StateResponse
from app.models.vehicles import VehicleResponse
from app.repositories.state import StateRepository
from app.repositories.vehicles import VehicleRepository
from app.websocket.publisher import MovementEventPublisher
from .demos import AuthorizedDemo, demo_entry, descriptions, operational_steps
from .models import Id
from .security import Actor, Database, all_rows, audit, authorized_unit, conflict, missing, one

router = APIRouter(prefix="/plataforma", tags=["4.3 Control y monitoreo"])
COMMANDS_SQL = """
    SELECT c.id_comando,c.id_vehiculo,c.nombre,c.codigo,c.descripcion,c.activo
    FROM comandos c JOIN iot_capacidad a ON c.codigo=a.codigo AND c.nombre=a.nombre
    WHERE c.id_vehiculo=%s AND a.modelo=%s AND c.activo
    AND (%s=0 OR c.codigo=0 OR (a.invitado AND c.codigo NOT IN (64,128)))
"""


def allowed_command(cursor, key, vehicle, command_id, *, lock=False):
    actor, row = authorized_unit(cursor, key, vehicle, lock=lock)
    if not row["activo"] or not row["modelo_activo"]:
        raise conflict("Unidad inactiva.")
    command = one(cursor, COMMANDS_SQL + " AND c.id_comando=%s",
                  (vehicle, row["modelo"], actor.role == "invitado", command_id))
    if not command:
        raise missing()
    return actor, command


def command_code(db, key, vehicle, command_id):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        _, command = allowed_command(cursor, key, vehicle, command_id)
        return command["codigo"]


@router.get("/vehiculos")
def my_vehicles(actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        if actor.role == "invitado":
            _, row = authorized_unit(cursor, actor.key, actor.vehicle)
            return [{"id_vehiculo": actor.vehicle, "nombre": row["nombre"]}]
        return all_rows(cursor, """
            SELECT u.vehiculo AS id_vehiculo,v.nombre FROM iot_unidad u
            JOIN vehiculos v ON v.id_vehiculo=u.vehiculo WHERE u.propietario=%s AND u.estado='vendida'
            ORDER BY u.vehiculo
        """, (actor.user,))


@router.get("/vehiculos/{vehicle}", response_model=VehicleResponse)
def get_vehicle(vehicle: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        result = VehicleRepository(StoredProcedureExecutor(connection)).get(vehicle)
        if current.role == "invitado":
            return {"id_vehiculo": vehicle, "nombre": row["nombre"], "activo": row["activo"], "modelo": None,
                    "descripcion": None, "microcontrolador": None, "fecha_registro": None}
        return result


@router.get("/vehiculos/{vehicle}/comandos", response_model=list[CommandResponse])
def get_commands(vehicle: Id, actor: Actor, db: Database, request: Request):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        ready = request.app.state.websocket_manager.dispatch_status(vehicle)["demo_original"]
        return all_rows(cursor, COMMANDS_SQL + " AND (%s OR c.codigo<>64) ORDER BY c.id_comando",
                        (vehicle, row["modelo"], current.role == "invitado", ready))


@router.get("/vehiculos/{vehicle}/despacho")
def dispatch_status(vehicle: Id, actor: Actor, db: Database, request: Request):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
    status = request.app.state.websocket_manager.dispatch_status(vehicle)
    if current.role != "usuario" or not (row["activo"] and row["modelo_activo"]):
        status["demo_original"] = False
    return status


def state(connection, vehicle, actor):
    if actor.role == "invitado":
        return None
    result = StateRepository(StoredProcedureExecutor(connection)).get(vehicle)
    return result.model_copy(update={"conectado": False}) if result else None


@router.get("/vehiculos/{vehicle}/estado", response_model=StateResponse | None)
def get_state(vehicle: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, _row = authorized_unit(cursor, actor.key, vehicle)
        return state(connection, vehicle, current)


@router.get("/vehiculos/{vehicle}/historial", response_model=list[HistoryResponse])
def history(vehicle: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        if current.role == "invitado":
            return []
        return all_rows(cursor, """
            SELECT h.id_historial,h.id_vehiculo,c.nombre AS comando,c.codigo,h.fecha_hora,h.origen
            FROM historial_comandos h LEFT JOIN comandos c ON h.id_comando=c.id_comando AND c.id_vehiculo=h.id_vehiculo
            WHERE h.id_vehiculo=%s AND h.id_historial>%s AND h.origen NOT IN ('DEMO','INVITADO')
            ORDER BY h.fecha_hora DESC,h.id_historial DESC LIMIT 10
        """, (vehicle, row["historial_desde"]))


def save_movement(db, key, vehicle, command_id, demos_active):
    with db.transaction() as connection, connection.cursor() as cursor:
        actor, command = allowed_command(cursor, key, vehicle, command_id, lock=True)
        if demos_active and command["codigo"] != 0:
            raise conflict("Hay una DEMO activa. Pulsa DETENER.")
        executor = StoredProcedureExecutor(connection)
        repository = StateRepository(executor)
        repository.update(vehicle, command_id, False)
        cursor.execute("INSERT INTO historial_comandos(id_vehiculo,id_comando,origen) VALUES(%s,%s,%s)",
                       (vehicle, command_id, "INVITADO" if actor.role == "invitado" else "API"))
        written = repository.get(vehicle)
        audit(cursor, "movimiento", user=actor.user, vehicle=vehicle)
        return MovementResponse(resultado="ok", id_vehiculo=vehicle, id_comando=command_id,
                                comando=written.comando, codigo=written.codigo, conectado=False,
                                fecha_actualizacion=written.fecha_actualizacion, origen="API")


@router.post("/vehiculos/{vehicle}/movimientos", response_model=MovementResponse)
async def move(vehicle: Id, data: MovementRequest, actor: Actor, db: Database, request: Request):
    app = request.app.state
    async with app.platform_lock:
        code = await run_in_threadpool(command_code, db, actor.key, vehicle, data.id_comando)
        dispatch = app.websocket_manager.dispatch_status(vehicle)
        if dispatch["demo_original_pendiente"] and code not in (0, 128):
            raise conflict("Interrumpe la DEMO original con CLAXON. DETENER sólo libera las salidas.")
        if code == 64 and not dispatch["demo_original"]:
            raise conflict("DEMO original requiere despacho autorizado y firmware compatible conectado.")
        if code == 0 and app.demo_execution_manager.is_active(vehicle):
            await app.demo_execution_manager.cancel_vehicle(vehicle)
        response = await run_in_threadpool(save_movement, db, actor.key, vehicle, data.id_comando,
                                           app.demo_execution_manager.is_active(vehicle))
        await MovementEventPublisher(app.websocket_manager).publish(response)
        return response


@router.get("/vehiculos/{vehicle}/demos", response_model=list[DemoResponse])
def available_demos(vehicle: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        if current.role != "usuario":
            return []
        return [dict(id_demo=item["id"], id_vehiculo=vehicle, nombre=item["nombre"],
                     descripcion=item["descripcion"], activo=item["activo"])
                for item in descriptions(cursor, row["modelo"], vehicle, current.user, row["version"])]


@router.get("/vehiculos/{vehicle}/demos/{demo}/movimientos", response_model=list[DemoMovementResponse])
def demo_steps(vehicle: Id, demo: Id, actor: Actor, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle)
        demo_entry(cursor, row, current, demo)
        return operational_steps(cursor, row, demo)


def verify_demo(db, actor, vehicle, demo, action, original_pending=False):
    with db.transaction() as connection, connection.cursor() as cursor:
        current, row = authorized_unit(cursor, actor.key, vehicle, lock=True)
        if current.role != "usuario":
            raise missing()
        if action == "demo_inicio":
            if original_pending:
                raise conflict("Antes de iniciar una secuencia, interrumpe la DEMO original con CLAXON.")
            demo_entry(cursor, row, current, demo)
        audit(cursor, action, user=actor.user, vehicle=vehicle)


@router.post("/vehiculos/{vehicle}/demos/{demo}/ejecutar", response_model=DemoExecutionResponse, status_code=202)
async def start_demo(vehicle: Id, demo: Id, actor: Actor, db: Database, request: Request):
    app = request.app.state
    async with app.platform_lock:
        pending = app.websocket_manager.dispatch_status(vehicle)["demo_original_pendiente"]
        await run_in_threadpool(verify_demo, db, actor, vehicle, demo, "demo_inicio", pending)
        return await app.demo_execution_manager.start(vehicle, demo, AuthorizedDemo(db, actor))


@router.post("/vehiculos/{vehicle}/demos/{demo}/cancelar", response_model=DemoExecutionResponse)
async def cancel_demo(vehicle: Id, demo: Id, actor: Actor, db: Database, request: Request):
    app = request.app.state
    async with app.platform_lock:
        await run_in_threadpool(verify_demo, db, actor, vehicle, demo, "demo_cancelacion_solicitada")
        return await app.demo_execution_manager.cancel(vehicle, demo)
