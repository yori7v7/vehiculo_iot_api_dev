"""Ejecución genérica de SP sobre una conexión propiedad del servicio llamante."""

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Any

import pymysql
from pymysql.connections import Connection
from pymysql.constants import CR, ER

from app.errors.database import (
    DatabaseConflictError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)


type Row = dict[str, Any]


@dataclass(frozen=True)
class ProcedureResult:
    """Conjuntos tabulares, incluidos SELECT vacíos, en el orden recibido."""

    result_sets: tuple[tuple[Row, ...], ...]

    def fetch_one(self) -> Row | None:
        """Primera fila del primer conjunto, o None si no hay filas."""

        if self.result_sets and self.result_sets[0]:
            return self.result_sets[0][0]
        return None

    def fetch_all(self) -> list[Row]:
        """Filas del primer conjunto, o una lista vacía."""

        return list(self.result_sets[0]) if self.result_sets else []


class StoredProcedureExecutor:
    """Consumir todos los resultados sin commit, rollback ni cierre de conexión.

    El nombre debe ser una constante interna de repositorio o servicio, nunca
    un valor procedente de una petición HTTP. Los valores se pasan a callproc.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def execute(
        self, procedure: str, parameters: Sequence[object] = ()
    ) -> ProcedureResult:
        """Ejecutar un SP con cero o más parámetros IN y drenar sus resultados."""

        if not re.fullmatch(r"sp_[A-Za-z0-9_]+", procedure, flags=re.ASCII):
            raise ValueError("El nombre del Stored Procedure no es válido.")
        if isinstance(parameters, (str, bytes, bytearray)):
            raise TypeError("Los parámetros deben ser una secuencia de valores.")

        result_sets: list[tuple[Row, ...]] = []
        try:
            with self._connection.cursor() as cursor:
                cursor.callproc(procedure, tuple(parameters))
                while True:
                    if cursor.description is not None:
                        result_sets.append(tuple(cursor.fetchall()))
                    # CALL agrega un resultado final sin columnas. También se
                    # consume; un error tardío debe propagarse antes del commit.
                    if not cursor.nextset():
                        break
        except (pymysql.MySQLError, OSError) as error:
            error_code = error.args[0] if error.args and type(error.args[0]) is int else None
            if error_code in (ER.DUP_ENTRY, ER.ROW_IS_REFERENCED_2, ER.NO_REFERENCED_ROW_2):
                raise DatabaseConflictError() from None
            if isinstance(error, (pymysql.InterfaceError, OSError)) or error_code in (
                CR.CR_SERVER_GONE_ERROR,
                CR.CR_SERVER_LOST,
            ):
                raise DatabaseUnavailableError() from None
            raise StoredProcedureExecutionError() from None

        return ProcedureResult(result_sets=tuple(result_sets))
