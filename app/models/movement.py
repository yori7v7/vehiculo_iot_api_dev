"""Contratos del movimiento individual registrado por la API."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt

from app.models.commands import CommandCode
from app.models.common import EntityId, INT_MAX, RequestModel


class MovementRequest(RequestModel):
    """Seleccionar un comando existente; los demás valores los controla el servicio."""

    id_comando: Annotated[StrictInt, Field(gt=0, le=INT_MAX)] = Field(
        description="Identificador positivo de un comando activo del vehículo."
    )


class MovementResponse(BaseModel):
    """Estado real leído dentro de la operación que se confirmó correctamente."""

    resultado: Literal["ok"]
    id_vehiculo: EntityId
    id_comando: EntityId
    comando: str = Field(max_length=60)
    codigo: CommandCode
    fecha_actualizacion: datetime | None
    conectado: bool
    origen: Literal["API"]
