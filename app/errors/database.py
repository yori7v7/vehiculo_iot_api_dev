"""Excepciones controlables sin mensajes ni credenciales del driver MySQL."""


class DatabaseError(Exception):
    """Error base de infraestructura con un mensaje seguro."""

    message = "Ocurrió un error al acceder a la base de datos."

    def __init__(self) -> None:
        super().__init__(self.message)


class DatabaseConfigurationError(DatabaseError):
    """Faltan variables necesarias para abrir una conexión."""

    message = "La configuración de la base de datos está incompleta o no es válida."


class DatabaseUnavailableError(DatabaseError):
    """No fue posible abrir la conexión MySQL."""

    message = "No fue posible establecer la conexión con la base de datos."


class DatabaseTransactionError(DatabaseError):
    """Falló el inicio o la finalización de una transacción."""

    message = "No fue posible completar la transacción con la base de datos."


class StoredProcedureExecutionError(DatabaseError):
    """Falló la ejecución o la lectura de algún conjunto de resultados."""

    message = "No fue posible ejecutar el Stored Procedure."


class DatabaseConflictError(DatabaseError):
    """La operación viola unicidad o una restricción de claves foráneas."""

    message = "La operación entra en conflicto con datos únicos o referencias existentes."


class DatabaseResultError(DatabaseError):
    """El SP no devolvió la estructura necesaria para completar la operación."""

    message = "La base de datos devolvió una respuesta inesperada."
