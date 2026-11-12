"""Modelos HTTP del control público temporal simulado."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, UUID4

from app.models.common import INT_MAX, EntityId
from app.public_control.domain import MOVEMENT_CODES, TOKEN_PATTERN


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def require_true(value: object) -> bool:
    if value is not True:
        raise ValueError("Confirma la supervisión de forma explícita.")
    return True


class EnableWindow(ControlInput):
    id_solicitud: UUID4
    duracion_seg: Annotated[int, Field(strict=True, ge=1200, le=1200)]
    supervision_confirmada: Annotated[Literal[True], BeforeValidator(require_true)]


class AcquireTurn(ControlInput):
    """La solicitud de turno no contiene credenciales ni parámetros."""


class StopRequest(ControlInput):
    id_solicitud: UUID4


MovementAction = StrEnum("MovementAction", {action: action for action in MOVEMENT_CODES})


class MoveRequest(ControlInput):
    id_solicitud: UUID4
    secuencia: Annotated[int, Field(strict=True, ge=1, le=INT_MAX)]
    epoca_operacion: Annotated[int, Field(strict=True, ge=1, le=INT_MAX)]
    duracion_ms: Annotated[int, Field(strict=True, ge=100, le=500)]
    accion: MovementAction


class PublicStatus(BaseModel):
    id_vehiculo: EntityId
    habilitado: bool
    estado: Literal["cerrado", "disponible", "ocupado", "deteniendo", "bloqueado"]
    vence_ventana_en: AwareDatetime | None
    hora_servidor: AwareDatetime
    revision: int = Field(ge=0)
    simulado: bool


class StopResult(BaseModel):
    id_operacion: UUID
    id_vehiculo: EntityId
    epoca_operacion: int
    estado: Literal["pendiente", "verificada", "incierta", "fallida"]
    solicitada_en: AwareDatetime
    verificada_en: AwareDatetime | None
    simulado: Literal[True]


class AdminStatus(PublicStatus):
    inicio_ventana_en: AwareDatetime | None
    id_turno_auditoria: UUID | None
    turno_vence_en: AwareDatetime | None
    parada: StopResult | None
    motivo_bloqueo: str | None


class ControlOperation(BaseModel):
    id_operacion: UUID
    id_vehiculo: EntityId
    epoca_operacion: int
    estado: Literal["aceptada", "despachada", "rechazada", "incierta", "finalizada"]
    creada_en: AwareDatetime
    simulado: Literal[True]


class CurrentTurn(BaseModel):
    id_vehiculo: EntityId
    estado: Literal["activo", "deteniendo"]
    vence_en: AwareDatetime
    vence_inactividad_en: AwareDatetime
    hora_servidor: AwareDatetime
    epoca_operacion: int
    siguiente_secuencia: int
    ultima_operacion: ControlOperation | None
    simulado: Literal[True]


class GrantedTurn(CurrentTurn):
    token: Annotated[str, Field(pattern=rf"^{TOKEN_PATTERN.pattern}$", repr=False)]


class AuditEntry(BaseModel):
    id_auditoria: int
    id_vehiculo: EntityId
    hora: AwareDatetime
    evento: str
    id_turno: UUID | None
    id_operacion: UUID | None
    motivo: str | None


class ControlErrorResponse(BaseModel):
    codigo: str
    detalle: str
    reintentar_en_seg: int | None = None
