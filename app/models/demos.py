"""Contratos de DEMO y pasos según las tablas y los SP del script MySQL."""

from typing import Annotated

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from app.models.commands import CommandCode
from app.models.common import EntityId, INT_MAX, RequestModel


UINT_MAX = 2**32 - 1
PositiveInt = Annotated[StrictInt, Field(gt=0, le=INT_MAX)]
Milliseconds = Annotated[StrictInt, Field(ge=0, le=INT_MAX)]
StoredMilliseconds = Annotated[StrictInt, Field(ge=0, le=UINT_MAX)]


class DemoCreate(RequestModel):
    """La creación usa el valor activo predeterminado de MySQL."""

    nombre: str = Field(min_length=1, max_length=80)
    descripcion: str | None = Field(default=None, max_length=255)

    @field_validator("nombre")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El nombre no puede estar vacío.")
        return value


class DemoUpdate(DemoCreate):
    """PUT reemplaza campos; omitir descripción equivale a NULL."""

    activo: StrictBool


class DemoResponse(BaseModel):
    """Columnas exactas de sp_obtener_demos."""

    id_demo: EntityId
    id_vehiculo: EntityId
    nombre: str = Field(max_length=80)
    descripcion: str | None = Field(max_length=255)
    activo: bool

    @field_validator("activo", mode="before")
    @classmethod
    def convert_database_boolean(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError("La columna activo debe contener un booleano o 0/1.")


class DemoMovementCreate(RequestModel):
    """Las firmas SP usan INT firmado incluso para los tiempos UNSIGNED."""

    id_comando: PositiveInt = Field(description="Comando activo del mismo vehículo.")
    orden: PositiveInt = Field(description="Orden positivo y único dentro de la DEMO.")
    duracion_ms: Milliseconds = Field(description="Duración en milisegundos, de 0 a 2147483647.")
    pausa_ms: Milliseconds = Field(default=0, description="Pausa en milisegundos; predeterminada 0.")


class DemoMovementUpdate(DemoMovementCreate):
    """PUT exige todos los campos editables, incluida la pausa."""

    pausa_ms: Milliseconds = Field(description="Pausa obligatoria en milisegundos.")


class DemoMovementResponse(BaseModel):
    """SELECT exacto de movimientos: el SP no incluye id_demo en su resultado."""

    id_demo_movimiento: EntityId
    orden: CommandCode
    id_comando: EntityId
    comando: str = Field(max_length=60)
    codigo: CommandCode
    duracion_ms: StoredMilliseconds
    pausa_ms: StoredMilliseconds
