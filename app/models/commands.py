"""Contratos HTTP de comandos basados en la tabla comandos del SQL."""

from typing import Annotated

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from app.models.common import EntityId, INT_MAX, INT_MIN, RequestModel


CommandCode = Annotated[StrictInt, Field(ge=INT_MIN, le=INT_MAX)]


class CommandCreate(RequestModel):
    """Datos admitidos por sp_crear_comando; el vehículo viene de la ruta."""

    nombre: str = Field(
        min_length=1, max_length=60, description="Nombre obligatorio, hasta 60 caracteres."
    )
    codigo: CommandCode = Field(
        description="Código entero INT firmado; admite cero y números negativos."
    )
    descripcion: str | None = Field(
        default=None, max_length=255, description="Descripción opcional; admite null."
    )

    @field_validator("nombre")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        """Rechazar nombres vacíos sin alterar el valor enviado a MySQL."""

        if not value.strip():
            raise ValueError("El nombre no puede estar vacío.")
        return value


class CommandUpdate(CommandCreate):
    """Reemplazo de los campos editables; una descripción omitida se borra."""

    activo: StrictBool = Field(description="Estado activo obligatorio: true o false.")


class CommandResponse(BaseModel):
    """Representación completa de una fila devuelta por el SP de lectura."""

    id_comando: EntityId
    id_vehiculo: EntityId
    nombre: str = Field(max_length=60)
    codigo: CommandCode
    descripcion: str | None = Field(max_length=255)
    activo: bool

    @field_validator("activo", mode="before")
    @classmethod
    def convert_database_boolean(cls, value: object) -> bool:
        """Aceptar los booleanos y el TINYINT 0/1 de PyMySQL explícitamente."""

        if isinstance(value, bool):
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError("La columna activo debe contener un booleano o 0/1.")
