"""Columnas de sp_obtener_estado, incluido su LEFT JOIN opcional al comando."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.commands import CommandCode
from app.models.common import EntityId


class StateResponse(BaseModel):
    """El SELECT del SP no devuelve id_estado."""

    id_vehiculo: EntityId
    vehiculo: str = Field(max_length=80)
    id_comando: EntityId | None
    comando: str | None = Field(max_length=60)
    codigo: CommandCode | None
    conectado: bool
    fecha_actualizacion: datetime | None

    @field_validator("conectado", mode="before")
    @classmethod
    def convert_database_boolean(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError("La columna conectado debe contener un booleano o 0/1.")
