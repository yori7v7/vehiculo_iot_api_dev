from contextlib import contextmanager
from unittest.mock import MagicMock

import pymysql
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.errors.database import DatabaseUnavailableError
from app.legacy_boundary import LegacySchemaBoundary


@pytest.mark.parametrize("condition", ["legacy", "commercial", "unavailable", "denied"])
def test_legacy_boundary_guards_reads_writes_and_websocket(condition):
    connection = MagicMock()
    query = connection.cursor.return_value.__enter__.return_value.execute
    if condition == "legacy":
        query.side_effect = pymysql.err.ProgrammingError(1146, "missing table")
    if condition == "denied":
        query.side_effect = DatabaseUnavailableError()

    class Database:
        @contextmanager
        def transaction(self, *, read_only):
            assert read_only
            if condition == "unavailable":
                raise DatabaseUnavailableError()
            yield connection

    app = FastAPI()
    app.add_middleware(LegacySchemaBoundary, database=Database())

    @app.api_route("/vehiculos/{vehicle}/movimientos", methods=["GET", "POST"])
    def legacy(vehicle: int):
        return {"id": vehicle}

    @app.websocket("/ws/vehiculos/{vehicle}")
    async def socket(websocket: WebSocket, vehicle: int):
        await websocket.accept()
        await websocket.send_json({"id": vehicle})
        await websocket.close()

    with TestClient(app) as client:
        for method in ("GET", "POST"):
            result = client.request(method, "/vehiculos/1/movimientos", headers={"X-API-Key": "legacy-fixture"})
            assert result.status_code == (200 if condition == "legacy" else 503)
        if condition == "legacy":
            with client.websocket_connect("/ws/vehiculos/1") as ws:
                assert ws.receive_json() == {"id": 1}
        else:
            with pytest.raises(WebSocketDisconnect) as rejected:
                with client.websocket_connect("/ws/vehiculos/1"):
                    pytest.fail("El esquema no permite acceso legado.")
            assert rejected.value.code == 1008
