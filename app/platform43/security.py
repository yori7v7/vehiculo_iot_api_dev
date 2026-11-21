"""Identidad de la plataforma y permisos acotados al recurso."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database.connection import MySQLDatabase
from app.dependencies import get_database

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash(token_urlsafe(32))
bearer = HTTPBearer(auto_error=False, description="Sesión opaca de 4.3, mantenida en memoria por el navegador.")
Database = Annotated[MySQLDatabase, Depends(get_database)]
GUEST_CODES = frozenset({0, 1, 2, 4, 5, 6, 8, 9, 10})
COMMAND_CODES = GUEST_CODES | {16, 32, 64, 128}


@dataclass(frozen=True)
class Identity:
    key: bytes
    user: int | None
    role: str
    name: str
    vehicle: int | None
    expires: datetime

    def public(self):
        return {"id": self.user, "rol": self.role, "nombre": self.name,
                "vehiculo": self.vehicle, "vence": self.expires.isoformat() + "Z"}


def digest(value: str) -> bytes:
    return sha256(value.encode()).digest()


def login_email(value: str) -> str:
    return value.strip().casefold()


def verified(value: str, stored: str) -> bool:
    try:
        return PASSWORDS.verify(stored, value)
    except (InvalidHashError, VerificationError):
        return False


def one(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchone()


def all_rows(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchall()


def audit(cursor, action, result="ok", *, user=None, vehicle=None):
    cursor.execute(
        "INSERT INTO iot_auditoria(actor,vehiculo,accion,resultado) VALUES(%s,%s,%s,%s)",
        (user, vehicle, action, result),
    )


def denied():
    return HTTPException(401, "Sesión ausente, revocada o caducada.", headers={"WWW-Authenticate": "Bearer"})


def missing():
    return HTTPException(404, "Recurso no disponible.")


def conflict(message):
    return HTTPException(409, message)


def identity(cursor, key: bytes) -> Identity:
    row = one(cursor, """
        SELECT s.usuario,s.vehiculo,s.vence,u.rol,u.nombre
        FROM iot_sesion s LEFT JOIN iot_usuario u ON u.id=s.usuario
        WHERE s.huella=%s AND s.revocada IS NULL AND s.vence>UTC_TIMESTAMP(6)
        AND (s.usuario IS NULL OR u.activo)
    """, (key,))
    if not row:
        raise denied()
    return Identity(key, row["usuario"], row["rol"] or "invitado",
                    row["nombre"] or "Invitado", row["vehiculo"], row["vence"])


def authenticated(database: Database, credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]):
    if credentials is None or len(credentials.credentials) != 43 or not credentials.credentials.isascii():
        raise denied()
    with database.transaction(read_only=True) as connection, connection.cursor() as cursor:
        return identity(cursor, digest(credentials.credentials))


Actor = Annotated[Identity, Depends(authenticated)]


def admin(actor: Actor):
    if actor.role != "administrador":
        raise HTTPException(403, "Se requiere el rol administrador.")
    return actor


Admin = Annotated[Identity, Depends(admin)]


def unit(cursor, vehicle, *, lock=False):
    row = one(cursor, """
        SELECT u.*,v.activo,v.nombre,m.activo AS modelo_activo,m.publico FROM iot_unidad u
        JOIN vehiculos v ON v.id_vehiculo=u.vehiculo JOIN iot_modelo m ON m.id=u.modelo
        WHERE u.vehiculo=%s
    """ + (" FOR UPDATE" if lock else ""), (vehicle,))
    if not row:
        raise missing()
    return row


def authorized_unit(cursor, key, vehicle, *, lock=False):
    row = unit(cursor, vehicle, lock=lock)
    actor = identity(cursor, key)
    if row["estado"] == "vendida" and actor.role == "usuario" and actor.user == row["propietario"]:
        return actor, row
    if (actor.role == "invitado" and actor.vehicle == vehicle and row["estado"] == "exhibicion"
            and row["publico"] and one(cursor,
            "SELECT 1 FROM iot_reserva WHERE vehiculo=%s AND sesion=%s", (vehicle, key))):
        return actor, row
    raise missing()


def issue(cursor, *, seconds, user=None, vehicle=None):
    token = token_urlsafe(32)
    key = digest(token)
    cursor.execute("""
        INSERT INTO iot_sesion(huella,usuario,vehiculo,vence)
        VALUES(%s,%s,%s,TIMESTAMPADD(SECOND,%s,UTC_TIMESTAMP(6)))
    """, (key, user, vehicle, seconds))
    return token, identity(cursor, key)


def rate_limit(database, buckets):
    blocked = False
    with database.transaction() as connection, connection.cursor() as cursor:
        for name, limit in sorted(buckets):
            key = digest(name)
            cursor.execute("""
                INSERT INTO iot_intento(ambito,inicio,intentos) VALUES(%s,UTC_TIMESTAMP(6),1)
                ON DUPLICATE KEY UPDATE intentos=IF(inicio<UTC_TIMESTAMP(6)-INTERVAL 10 MINUTE,1,LEAST(intentos+1,10000)),
                inicio=IF(inicio<UTC_TIMESTAMP(6)-INTERVAL 10 MINUTE,UTC_TIMESTAMP(6),inicio)
            """, (key,))
            blocked |= one(cursor, "SELECT intentos FROM iot_intento WHERE ambito=%s", (key,))["intentos"] > limit
    if blocked:
        raise HTTPException(429, "Demasiadas solicitudes.", headers={"Retry-After": "600"})


def client_address(request: Request) -> str:
    return request.client.host if request.client else "desconocida"
