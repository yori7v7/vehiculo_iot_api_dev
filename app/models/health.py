"""Modelo de respuesta de la comprobación básica de FastAPI."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Salud del proceso HTTP; no representa disponibilidad de RDS o hardware."""

    status: Literal["ok"] = Field(description="El proceso HTTP responde.")
    service: str = Field(description="Nombre configurado de la API.")
    environment: Literal["development"] = Field(description="Entorno local.")
