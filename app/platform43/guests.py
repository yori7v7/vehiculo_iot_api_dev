"""Catálogo público y reservas exclusivas coordinadas por la fila de unidad."""
import asyncio
import logging

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from .models import Id
from .security import (Actor, Admin, Database, all_rows, audit, client_address,
                       conflict, issue, missing, one, rate_limit, unit)

router = APIRouter(prefix="/plataforma", tags=["4.3 Exhibición"])
logger = logging.getLogger(__name__)


@router.get("/catalogo")
def catalog(db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        models = all_rows(cursor, "SELECT id,sku,nombre,descripcion FROM iot_modelo WHERE activo AND publico ORDER BY id")
        units = all_rows(cursor, """
            SELECT u.vehiculo,v.nombre,u.modelo,(r.vehiculo IS NULL) disponible
            FROM iot_unidad u JOIN vehiculos v ON v.id_vehiculo=u.vehiculo
            JOIN iot_modelo m ON m.id=u.modelo LEFT JOIN iot_reserva r ON r.vehiculo=u.vehiculo
            WHERE u.estado='exhibicion' AND v.activo AND m.activo AND m.publico ORDER BY u.vehiculo
        """)
        return {"modelos": models, "unidades": units}


def reserve(db, vehicle, address):
    rate_limit(db, [(f"invitado:{address}", 25)])
    with db.transaction() as connection, connection.cursor() as cursor:
        row = unit(cursor, vehicle, lock=True)
        if row["estado"] != "exhibicion" or not (row["activo"] and row["publico"] and row["modelo_activo"]):
            raise missing()
        if one(cursor, "SELECT 1 FROM iot_reserva WHERE vehiculo=%s", (vehicle,)):
            raise conflict("La unidad de exhibición ya está reservada.")
        token, actor = issue(cursor, seconds=120, vehicle=vehicle)
        cursor.execute("INSERT INTO iot_reserva(vehiculo,sesion) VALUES(%s,%s)", (vehicle, actor.key))
        audit(cursor, "reserva_creada", vehicle=vehicle)
    return {"token": token, **actor.public()}


@router.post("/invitados/{vehicle}", status_code=201)
def guest(vehicle: Id, request: Request, response: Response, db: Database):
    response.headers["Cache-Control"] = "no-store"
    return reserve(db, vehicle, client_address(request))


@router.get("/reservas")
def reservations(actor: Admin, db: Database):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return all_rows(cursor, """
            SELECT r.vehiculo,v.nombre,s.vence,s.revocada FROM iot_reserva r
            JOIN iot_sesion s ON s.huella=r.sesion JOIN vehiculos v ON v.id_vehiculo=r.vehiculo
            ORDER BY r.vehiculo
        """)


def revoke(db, vehicle, *, admin=None, guest=None):
    with db.transaction() as connection, connection.cursor() as cursor:
        unit(cursor, vehicle, lock=True)
        row = one(cursor, "SELECT sesion FROM iot_reserva WHERE vehiculo=%s", (vehicle,))
        if not row or (guest and guest != row["sesion"]):
            raise missing()
        cursor.execute("UPDATE iot_sesion SET revocada=COALESCE(revocada,UTC_TIMESTAMP(6)) WHERE huella=%s", (row["sesion"],))
        audit(cursor, "reserva_revocada", user=admin, vehicle=vehicle)


@router.delete("/reservas/{vehicle}", status_code=204)
async def cancel_reservation(vehicle: Id, request: Request, actor: Admin, db: Database):
    state = request.app.state
    async with state.platform_lock:
        await run_in_threadpool(revoke, db, vehicle, admin=actor.user)
        await cleanup(state, db)


def expired(db):
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return all_rows(cursor, """
            SELECT r.vehiculo,r.sesion FROM iot_reserva r JOIN iot_sesion s ON r.sesion=s.huella
            WHERE s.vence<=UTC_TIMESTAMP(6) OR s.revocada IS NOT NULL
        """)


def release(db, vehicle, key, result):
    with db.transaction() as connection, connection.cursor() as cursor:
        unit(cursor, vehicle, lock=True)
        cursor.execute("DELETE FROM iot_reserva WHERE vehiculo=%s AND sesion=%s", (vehicle, key))
        if cursor.rowcount:
            audit(cursor, "reserva_liberada_stop", result, vehicle=vehicle)


async def cleanup(state, db):
    for row in await run_in_threadpool(expired, db):
        vehicle = row["vehiculo"]
        result = await state.websocket_manager.stop_device(vehicle)
        await run_in_threadpool(release, db, vehicle, row["sesion"], result)


async def maintenance(state, db):
    while True:
        await asyncio.sleep(1)
        try:
            async with state.platform_lock:
                await cleanup(state, db)
        except Exception:
            logger.warning("No se pudo procesar el vencimiento de reservas 4.3.")
