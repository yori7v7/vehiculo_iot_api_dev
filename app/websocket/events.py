"""Eventos WebSocket construidos con los valores persistidos de la operación."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field

from app.models.commands import CommandCode
from app.models.common import EntityId
from app.models.movement import MovementResponse
from app.models.state import StateResponse


class InitialStateEvent(BaseModel):
    """Instantánea inicial; un vehículo sin estado conserva los valores null."""

    tipo_evento: Literal["estado_actual"] = "estado_actual"
    id_vehiculo: EntityId
    comando: str | None = Field(max_length=60)
    codigo: CommandCode | None
    timestamp: datetime | None
    estado: StateResponse | None

    @classmethod
    def from_state(cls, id_vehiculo: int, state: StateResponse | None) -> Self:
        if state is not None and state.id_vehiculo != id_vehiculo:
            raise ValueError("El estado no pertenece al vehículo solicitado.")
        return cls(
            id_vehiculo=id_vehiculo,
            comando=state.comando if state is not None else None,
            codigo=state.codigo if state is not None else None,
            timestamp=state.fecha_actualizacion if state is not None else None,
            estado=state,
        )


class MovementEvent(BaseModel):
    """Movimiento confirmado; timestamp procede de la relectura del estado SQL."""

    tipo_evento: Literal["movimiento"] = "movimiento"
    id_vehiculo: EntityId
    id_comando: EntityId
    comando: str = Field(max_length=60)
    codigo: CommandCode
    timestamp: datetime | None
    conectado: bool
    origen: Literal["API"] = "API"

    @classmethod
    def from_movement(cls, response: MovementResponse) -> Self:
        return cls(
            id_vehiculo=response.id_vehiculo,
            id_comando=response.id_comando,
            comando=response.comando,
            codigo=response.codigo,
            timestamp=response.fecha_actualizacion,
            conectado=response.conectado,
            origen=response.origen,
        )
