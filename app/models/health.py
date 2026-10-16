"""Modelo de respuesta de la comprobación básica de FastAPI."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Salud del proceso HTTP; no representa disponibilidad de RDS o hardware."""

    status: Literal["ok"] = Field(description="El proceso HTTP responde.")
    service: str = Field(description="Nombre configurado de la API.")
    environment: Literal["development", "production"] = Field(description="Entorno configurado del proceso.")


class DatabaseHealthResponse(BaseModel):
    """Conexión y procedimiento de lectura disponibles, sin datos sensibles."""

    status: Literal["ok"] = "ok"
    database: Literal["available"] = "available"


class DatabaseHealthErrorResponse(BaseModel):
    """Detalle público del diagnóstico, sin errores internos de MySQL."""

    detail: str
