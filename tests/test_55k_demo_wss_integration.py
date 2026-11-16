"""55-K: integración DEMO/WSS en TestClient, sin endpoints productivos."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException, Request

from app.public_control.control_evidence_55k import (
    can_dispatch_virtual_55k,
)
from app.public_control.control_permissions_55k import ADMIN, GUEST
from app.public_control.demo_programada_55k import (
    PasoDemo55K, ejecutar_demo_virtual,
)
from app.public_control.kv_virtual_staging import _guard
from app.public_control.kv_kx_virtual_bridge_lab import (
    create_kv_kx_virtual_lab_app,
)

from test_kv_kx_virtual_bridge_lab import (
    ADMIN as ADMIN_PROOF, PROXY, DEVICE, HEAD, AUTH,
    INBOX, PATH, Clock, browser, authenticate,
    ack_two_phases, wait_ready, guest_request, approve,
)


PLAN_SERVIDOR = (PasoDemo55K(1, 1000, 0),)


@pytest.fixture
def demo_lab(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv(
        "KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only"
    )

    app = create_kv_kx_virtual_lab_app(
        tmp_path / "demo_wss.sqlite3",
        ADMIN_PROOF, PROXY, DEVICE,
        clock=Clock(),
    )

    async def run(request: Request, role: str, mode: str):
        # Solo rutas de prueba. El rol no proviene del cuerpo JSON.
        if role == ADMIN:
            ledger, _ = _guard(request, 1, admin=True)
            credential = request.headers["x-api-key"]
        else:
            ledger, _ = _guard(request, 1, admin=False)
            credential = request.headers["x-browser-session"]

        hub = request.app.state.kx_diag_hub
        cancel = asyncio.Event()
        dispatched = 0

        def authorized():
            return can_dispatch_virtual_55k(
                ledger,
                server_role=role,
                credential=credential,
                action="demo_programada",
                authenticated_device=hub.ready,
            )

        if not authorized():
            raise HTTPException(403, "Sin turno vigente")

        async def send(code: int, duration: int):
            nonlocal dispatched

            # K-X vuelve a comprobar el turno antes y despues
            # de cada envio firmado.
            if role == ADMIN:
                await hub.execute_admin_virtual(
                    ledger, credential, code, duration
                )
            else:
                await hub.execute_virtual(
                    ledger, credential, code, duration
                )

            dispatched += 1

            # Fallos controlados exclusivamente por la prueba.
            if dispatched == 1 and mode == "cancel":
                cancel.set()

            if dispatched == 1 and mode == "revoke":
                ledger.revoke(ADMIN_PROOF)

        status = await ejecutar_demo_virtual(
            PLAN_SERVIDOR,
            1,
            enviar=send,
            autorizado=authorized,
            cancelar=cancel,
        )

        return {
            "estado": status,
            "tramos": dispatched,
            "simulado": True,
            "control_fisico": False,
            "canDrive": False,
        }

    @app.post("/__lab__/demo55k/admin")
    async def admin_demo(request: Request):
        return await run(request, ADMIN, "normal")

    @app.post("/__lab__/demo55k/guest")
    async def guest_demo(request: Request):
        return await run(request, GUEST, "normal")

    @app.post("/__lab__/demo55k/cancel")
    async def cancel_demo(request: Request):
        return await run(request, GUEST, "cancel")

    @app.post("/__lab__/demo55k/revoke")
    async def revoke_demo(request: Request):
        return await run(request, GUEST, "revoke")

    return app


def submit(client, path, headers):
    return client.post(path, headers=headers)


def acknowledge_chunks(ws, wire, count):
    for _ in range(count):
        move = ack_two_phases(ws, wire)
        stop = ack_two_phases(ws, wire)

        assert move.code == 1
        assert move.duration_ms == 500
        assert stop.code == 0


@pytest.mark.parametrize(
    "role, path",
    [
        ("admin", "/__lab__/demo55k/admin"),
        ("guest", "/__lab__/demo55k/guest"),
    ],
)
def test_both_roles_execute_signed_demo(demo_lab, role, path):
    app = demo_lab

    with browser(app) as client:
        headers = AUTH

        if role == "guest":
            secret, request_id = guest_request(client)
            approve(client, request_id)
            headers = {
                **HEAD, "X-Browser-Session": secret
            }
        else:
            assert client.post(
                INBOX + "/supervision", headers=AUTH
            ).status_code == 200

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    submit, client, path, headers
                )
                acknowledge_chunks(ws, wire, 2)
                response = future.result(timeout=7)

            assert response.status_code == 200, response.text
            result = response.json()

            assert result["estado"] == "finalizada"
            assert result["tramos"] == 2
            assert result["control_fisico"] is False
            assert result["canDrive"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/__lab__/demo55k/cancel",
        "/__lab__/demo55k/revoke",
    ],
)
def test_cancel_or_revoke_stops_future_chunks(demo_lab, path):
    app = demo_lab

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)

        headers = {
            **HEAD, "X-Browser-Session": secret
        }

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    submit, client, path, headers
                )
                acknowledge_chunks(ws, wire, 1)
                response = future.result(timeout=7)

            assert response.status_code == 200, response.text
            result = response.json()

            assert result["estado"] == "cancelada"
            assert result["tramos"] == 1
            assert result["control_fisico"] is False


def test_admin_cannot_override_guest_demo_turn(demo_lab):
    app = demo_lab

    with browser(app) as client:
        _, request_id = guest_request(client)
        approve(client, request_id)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            response = client.post(
                "/__lab__/demo55k/admin",
                headers=AUTH,
            )

            assert response.status_code == 403


def test_demo_requires_authorized_turn(demo_lab):
    with browser(demo_lab) as client:
        response = client.post(
            "/__lab__/demo55k/admin",
            headers=AUTH,
        )
        assert response.status_code == 403