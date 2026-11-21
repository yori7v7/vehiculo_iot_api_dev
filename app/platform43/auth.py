"""Registro controlado, autenticación, cambio de contraseña y revocación."""
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .guests import cleanup

from .models import ChangePassword, Login
from .security import (Actor, Database, PASSWORDS, DUMMY_HASH, audit, client_address,
                       conflict, identity, issue, login_email, one, rate_limit, verified)

router = APIRouter(prefix="/plataforma", tags=["4.3 Identidad"])


@router.post("/sesion", summary="Iniciar sesión durante 30 minutos")
def login(data: Login, request: Request, response: Response, db: Database):
    email = login_email(data.email)
    rate_limit(db, [(f"ip:{client_address(request)}", 30), (f"cuenta:{email}", 8)])
    password = data.password.get_secret_value()
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        user = one(cursor, "SELECT id,clave,activo FROM iot_usuario WHERE email=%s", (email,))
    valid = verified(password, user["clave"] if user else DUMMY_HASH)
    result = None
    with db.transaction() as connection, connection.cursor() as cursor:
        if user and valid:
            current = one(cursor, "SELECT clave,activo FROM iot_usuario WHERE id=%s FOR UPDATE", (user["id"],))
            if current["activo"] and current["clave"] == user["clave"]:
                if PASSWORDS.check_needs_rehash(user["clave"]):
                    cursor.execute("UPDATE iot_usuario SET clave=%s WHERE id=%s",
                                   (PASSWORDS.hash(password), user["id"]))
                result = issue(cursor, seconds=1800, user=user["id"])
        audit(cursor, "login", "ok" if result else "rechazado", user=user["id"] if result else None)
    if not result:
        raise HTTPException(401, "Credenciales no válidas.")
    token, actor = result
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, **actor.public()}


@router.get("/perfil")
def profile(actor: Actor):
    return actor.public()


def revoke_session(actor, db):
    with db.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE iot_sesion SET revocada=UTC_TIMESTAMP(6) WHERE huella=%s", (actor.key,))
        audit(cursor, "logout", user=actor.user, vehicle=actor.vehicle)


@router.delete("/sesion", status_code=204)
async def logout(actor: Actor, db: Database, request: Request):
    state = request.app.state
    async with state.platform_lock:
        await run_in_threadpool(revoke_session, actor, db)
        if actor.vehicle:
            await cleanup(state, db)


@router.put("/perfil/password", status_code=204)
def password(data: ChangePassword, actor: Actor, db: Database):
    if actor.user is None:
        raise HTTPException(403, "Se requiere una cuenta.")
    rate_limit(db, [(f"password:{actor.user}", 8)])
    with db.transaction(read_only=True) as connection, connection.cursor() as cursor:
        old = one(cursor, "SELECT clave FROM iot_usuario WHERE id=%s", (actor.user,))["clave"]
    current = data.actual.get_secret_value()
    new = data.nueva.get_secret_value()
    if not verified(current, old):
        with db.transaction() as connection, connection.cursor() as cursor:
            audit(cursor, "password", "rechazado", user=actor.user)
        raise HTTPException(403, "Contraseña actual incorrecta.")
    if current == new:
        raise HTTPException(400, "La nueva contraseña debe ser distinta.")
    encoded = PASSWORDS.hash(new)
    with db.transaction() as connection, connection.cursor() as cursor:
        user = one(cursor, "SELECT clave FROM iot_usuario WHERE id=%s FOR UPDATE", (actor.user,))
        identity(cursor, actor.key)
        if user["clave"] != old:
            raise conflict("La contraseña cambió durante la operación.")
        cursor.execute("UPDATE iot_usuario SET clave=%s WHERE id=%s", (encoded, actor.user))
        cursor.execute("UPDATE iot_sesion SET revocada=UTC_TIMESTAMP(6) WHERE usuario=%s AND revocada IS NULL", (actor.user,))
        audit(cursor, "password", user=actor.user)
