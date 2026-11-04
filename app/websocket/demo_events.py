"""Eventos de DEMO: controles con hora UTC y pasos con el estado confirmado."""

from datetime import datetime
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, Field

from app.models.commands import CommandCode
from app.models.common import EntityId


class DemoEvent(BaseModel):
    # Cada evento DEMO tiene identidad independiente, incluso en ejecuciones repetidas.
    id_evento: str = Field(default_factory=lambda: uuid4().hex)
    tipo_evento: Literal[
        "demo_inicio", "demo_movimiento", "demo_fin", "demo_cancelada", "demo_error"
    ]
    id_vehiculo: EntityId
    id_demo: EntityId
    nombre_demo: str | None
    comando: str | None = None
    codigo: CommandCode | None = None
    timestamp: datetime | None
    id_demo_movimiento: EntityId | None = None
    id_comando: EntityId | None = None
    orden: int | None = None
    duracion_ms: int | None = None
    pausa_ms: int | None = None
    conectado: bool | None = None
    mensaje: str | None = None
