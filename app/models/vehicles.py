"""Contratos de vehículos acordes con la tabla y los SP proporcionados."""

from datetime import datetime

from pydantic import BaseModel, Field, StrictBool, field_validator

from app.models.common import EntityId, RequestModel


class VehicleCreate(RequestModel):
    """El alta usa el activo y la fecha predeterminados de MySQL."""

    nombre: str = Field(min_length=1, max_length=80)
    modelo: str | None = Field(default=None, max_length=80)
    descripcion: str | None = Field(default=None, max_length=255)
    microcontrolador: str | None = Field(default=None, max_length=50)

    @field_validator("nombre")
    @classmethod
    def validate_nombre(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El nombre no puede estar vacío ni contener sólo espacios.")
        return value


class VehicleUpdate(VehicleCreate):
    """Reemplazo completo: omitir un campo opcional lo asigna a NULL."""

    activo: StrictBool


class VehicleResponse(BaseModel):
    """Columnas completas del vehículo, incluidos los registros inactivos."""

    id_vehiculo: EntityId
    nombre: str = Field(max_length=80)
    modelo: str | None = Field(max_length=80)
    descripcion: str | None = Field(max_length=255)
    microcontrolador: str | None = Field(max_length=50)
    fecha_registro: datetime | None
    activo: bool

    @field_validator("activo", mode="before")
    @classmethod
    def convert_database_boolean(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError("La columna activo debe contener un booleano o 0/1.")
