"""Impide montar el contrato público legado sobre un esquema comercial 4.3."""

import pymysql
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.errors.database import DatabaseError


def is_legacy_schema(database):
    with database.transaction(read_only=True) as connection, connection.cursor() as cursor:
        try:
            cursor.execute("SELECT 1 FROM iot_unidad LIMIT 0")
        except pymysql.err.ProgrammingError as error:
            if error.args[0] == 1146:  # La tabla no existe en el esquema seleccionado.
                return True
            raise
        return False


class LegacySchemaBoundary:
    def __init__(self, app, database):
        self.app = app
        self.database = database

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root = scope.get("root_path", "").rstrip("/")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        legacy_http = scope["type"] == "http" and (path == "/vehiculos" or path.startswith("/vehiculos/"))
        legacy_socket = scope["type"] == "websocket" and path.startswith("/ws/vehiculos/")
        if legacy_http or legacy_socket:
            try:
                allowed = await run_in_threadpool(is_legacy_schema, self.database)
            except DatabaseError:
                allowed = False
            if not allowed:
                if legacy_socket:
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    response = JSONResponse({"detail": "El contrato legado no está disponible en este esquema."}, 503)
                    await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
