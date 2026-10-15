"""Composición de dependencias; crear la fábrica no abre sockets MySQL."""

from typing import Annotated

from fastapi import Depends

from app.config.settings import Settings, get_settings
from app.database.connection import MySQLDatabase


def get_database(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MySQLDatabase:
    """Entregar una fábrica por solicitud, sin conexiones globales."""

    return MySQLDatabase(settings)
