"""Tipos de entrada comunes basados en los INT firmados del esquema MySQL."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


INT_MIN = -(2**31)
INT_MAX = 2**31 - 1
EntityId = Annotated[int, Field(gt=0, le=INT_MAX)]


class RequestModel(BaseModel):
    """Evitar campos de entrada no contemplados por la operación del SP."""

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    """Mensaje público de error sin SQL ni información de conexión."""

    detail: str
