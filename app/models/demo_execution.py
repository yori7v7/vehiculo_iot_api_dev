"""Plan independiente e inmutable y respuestas de control de una DEMO."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.common import EntityId
from app.models.demos import DemoMovementResponse, DemoResponse


class _DemoSnapshot(DemoResponse):
    model_config = ConfigDict(frozen=True)


class _MovementSnapshot(DemoMovementResponse):
    model_config = ConfigDict(frozen=True)


class DemoExecutionPlan(BaseModel):
    """Copiar y congelar también los modelos anidados, preservando el orden SQL."""

    model_config = ConfigDict(frozen=True)

    demo: DemoResponse
    movimientos: tuple[DemoMovementResponse, ...]

    @field_validator("demo")
    @classmethod
    def freeze_demo(cls, value: DemoResponse) -> DemoResponse:
        return _DemoSnapshot.model_validate(value.model_dump())

    @field_validator("movimientos")
    @classmethod
    def freeze_movements(cls, values: tuple[DemoMovementResponse, ...]) -> tuple[DemoMovementResponse, ...]:
        return tuple(
            _MovementSnapshot.model_validate(value.model_dump())
            for value in values
        )


class DemoExecutionResponse(BaseModel):
    id_vehiculo: EntityId
    id_demo: EntityId
    estado: Literal["iniciada", "cancelada"]
