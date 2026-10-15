"""Validación de resultados de SP sin filtrar filas a mensajes de excepción."""

from pydantic import BaseModel, ValidationError

from app.database.procedures import ProcedureResult, Row
from app.errors.database import DatabaseResultError
from app.models.common import INT_MAX


def parse_model[Model: BaseModel](model: type[Model], row: Row) -> Model:
    """Validar la fila dentro de la transacción, antes de permitir un commit."""

    try:
        return model.model_validate(row)
    except ValidationError:
        raise DatabaseResultError() from None


def created_id(result: ProcedureResult, column: str) -> int:
    """Leer el ID de LAST_INSERT_ID que devuelve el SP, sin usar IDs supuestos."""

    row = result.fetch_one()
    value = row.get(column) if row is not None else None
    if type(value) is not int or not 0 < value <= INT_MAX:
        raise DatabaseResultError()
    return value
