"""Reglas de entrada y proyecciones del control simulado."""

import re
from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from types import MappingProxyType
from uuid import UUID


MOVEMENT_CODES = MappingProxyType({
    "AVANZAR": 1,
    "RETROCEDER": 2,
    "IZQUIERDA": 4,
    "DERECHA": 8,
    "AVANZAR_IZQUIERDA": 5,
    "RETROCEDER_IZQUIERDA": 6,
    "AVANZAR_DERECHA": 9,
    "RETROCEDER_DERECHA": 10,
})
WINDOW_SECONDS = 1200
MAX_SEQUENCE = 2_147_483_647
STOP_CONFIRMATION_SECONDS = 2
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class PublicControlError(Exception):
    def __init__(self, status: int, code: str, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.retry_after = retry_after


def unavailable():
    return PublicControlError(503, "control_no_disponible", "El control simulado no está disponible.")


def unauthorized():
    return PublicControlError(401, "turno_no_autorizado", "Se requiere un turno válido para este vehículo.")


def request_identifier(value) -> str:
    try:
        request = UUID(str(value))
    except (TypeError, ValueError):
        raise PublicControlError(422, "solicitud_invalida", "El identificador debe ser un UUID v4.") from None
    if request.version != 4:
        raise PublicControlError(422, "solicitud_invalida", "El identificador debe ser un UUID v4.")
    return str(request)


class GuestTokenService:
    @staticmethod
    def issue() -> tuple[str, bytes]:
        token = token_urlsafe(32)
        return token, GuestTokenService.digest(token)

    @staticmethod
    def digest(token: str) -> bytes:
        if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
            raise unauthorized()
        return sha256(token.encode("ascii")).digest()


def utc(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, timezone.utc) if value is not None else None


def stop_response(row):
    if row is None:
        return None
    return {
        "id_operacion": row["operation_id"],
        "id_vehiculo": row["vehicle_id"],
        "epoca_operacion": row["epoch"],
        "estado": row["status"],
        "solicitada_en": utc(row["created_at"]),
        "verificada_en": utc(row["verified_at"]),
        "simulado": True,
    }


def operation_response(row):
    if row is None:
        return None
    return {
        "id_operacion": row["operation_id"],
        "id_vehiculo": row["vehicle_id"],
        "epoca_operacion": row["epoch"],
        "estado": row["status"],
        "creada_en": utc(row["created_at"]),
        "simulado": True,
    }
