"""Traducción centralizada de errores controlados a respuestas HTTP seguras."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors.database import (
    DatabaseConfigurationError,
    DatabaseConflictError,
    DatabaseError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
)
from app.errors.domain import ResourceNotFoundError


async def resource_not_found_handler(
    _request: Request, error: ResourceNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


async def database_error_handler(_request: Request, error: DatabaseError) -> JSONResponse:
    if isinstance(error, DatabaseConflictError):
        status_code = 409
    elif isinstance(
        error,
        (DatabaseConfigurationError, DatabaseUnavailableError, DatabaseTransactionError),
    ):
        status_code = 503
    else:
        status_code = 500
    return JSONResponse(status_code=status_code, content={"detail": str(error)})


def register_exception_handlers(application: FastAPI) -> None:
    """Registrar errores de dominio y persistencia sin exponer el driver."""

    application.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)
    application.add_exception_handler(DatabaseError, database_error_handler)
