"""Columnas exactas de sp_obtener_historial sin clasificar sus orígenes."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StrictInt

from app.models.commands import CommandCode
from app.models.common import EntityId


HistoryId = Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]


class HistoryResponse(BaseModel):
    """El SELECT no devuelve id_comando; origen conserva el VARCHAR del SQL."""

    id_historial: HistoryId
    id_vehiculo: EntityId
    comando: str | None = Field(max_length=60)
    codigo: CommandCode | None
    fecha_hora: datetime | None
    origen: str = Field(max_length=30)
