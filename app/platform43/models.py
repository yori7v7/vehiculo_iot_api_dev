"""Contratos de entrada de la actividad 4.3."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

Id = Annotated[int, Field(gt=0, le=2147483647)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]
ExistingPassword = Annotated[SecretStr, Field(min_length=1, max_length=128)]
Code = Literal[0, 1, 2, 4, 5, 6, 8, 9, 10, 16, 32, 64, 128]
HORN_MAX_MS = 300  # No superar el pulso individual del firmware de referencia.


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Login(Payload):
    email: Email
    password: ExistingPassword


class ChangePassword(Payload):
    actual: ExistingPassword
    nueva: Password


class Client(Payload):
    email: Email
    nombre: Name
    password: Password


class Access(Payload):
    activo: bool


class Capability(Payload):
    codigo: Code
    nombre: Annotated[Name, Field(max_length=60)]
    invitado: bool = False


class Model(Payload):
    sku: Annotated[Name, Field(max_length=64)]
    nombre: Name
    descripcion: str | None = Field(None, max_length=255)
    publico: bool = False
    activo: bool = True
    capacidades: list[Capability] = Field(min_length=1, max_length=13)


class Unit(Payload):
    serie: Name
    modelo: Id
    nombre: Name
    estado: Literal["inventario", "exhibicion", "baja"] = "inventario"


class NewUnit(Unit):
    id_vehiculo_existente: Id | None = None


class Transfer(Payload):
    propietario: Id | None
    version: Id


class Step(Payload):
    codigo: Code
    duracion_ms: Annotated[int, Field(strict=True, ge=30, le=12000)]
    pausa_ms: Annotated[int, Field(strict=True, ge=0, le=12000)] = 0


class Demo(Payload):
    nombre: Name
    descripcion: str | None = Field(None, max_length=255)
    activo: bool = True
    pasos: list[Step] = Field(min_length=1, max_length=24)

    @field_validator("pasos")
    @classmethod
    def safe_sequence(cls, steps):
        if any(step.codigo == 64 for step in steps):
            raise ValueError("DEMO_ORIGINAL es una función independiente del equipo.")
        if any(step.codigo == 128 and step.duracion_ms > HORN_MAX_MS for step in steps):
            raise ValueError(f"CLAXON admite hasta {HORN_MAX_MS} ms por paso.")
        if sum(step.duracion_ms + step.pausa_ms for step in steps) > 60000:
            raise ValueError("La secuencia admite hasta 60 segundos.")
        return steps
