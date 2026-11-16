"""55-K: reinicio virtual sin reanudacion de DEMO ni de turnos."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.public_control.demo_programada_55k import PasoDemo55K
from app.public_control.kv_kx_virtual_bridge_lab import (
    create_kv_kx_virtual_lab_app,
)

from test_55k_demo_coordinator import (
    A_START, A_STATUS, G_START, G_STATUS,
    guest_headers, wait_status, finish_chunk,
)
from test_kv_kx_virtual_bridge_lab import (
    ADMIN, PROXY, DEVICE, AUTH, INBOX, PATH,
    Clock, browser, authenticate, ack_two_phases,
    wait_ready, guest_request, approve,
)


@pytest.fixture
def restart_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv(
        "KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only"
    )

    # Las dos instancias comparten el mismo archivo durable.
    db = tmp_path / "restart_shared.sqlite3"
    clock = Clock()

    def factory():
        return create_kv_kx_virtual_lab_app(
            db, ADMIN, PROXY, DEVICE,
            clock=clock,
            demo_plan=(PasoDemo55K(1, 1000, 0),),
            demo_cycles=1,
        )

    return factory


def test_old_guest_ticket_does_not_revive(restart_factory):
    factory = restart_factory

    # Primera instancia: invitado con turno aprobado.
    with browser(factory()) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)

    # Segunda instancia: mismo SQLite, nueva epoca K-Q/K-R.
    app = factory()

    with browser(app) as client:
        demo = app.state.kv_demo_coordinator

        assert not demo.active
        assert app.state.kx_diag_hub.ready is False

        status = client.get(
            G_STATUS, headers=guest_headers(secret)
        )
        assert status.status_code == 200
        assert status.json()["estado"] == "sin_demo"

        # Renovar supervision NO revive el permiso anterior.
        assert client.post(
            INBOX + "/supervision", headers=AUTH
        ).status_code == 200

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            first = ack_two_phases(ws, wire)

            assert first.code == 0
            wait_ready(app)

            # Solo se emitio el STOP inicial, ninguna DEMO.
            assert app.state.kx_diag_hub._seq == 1
            assert not demo.active

            denied = client.post(
                G_START, headers=guest_headers(secret)
            )
            assert denied.status_code == 403

            assert app.state.kx_diag_hub._seq == 1


def test_finished_demo_not_restored(restart_factory):
    factory = restart_factory
    app1 = factory()

    with browser(app1) as client:
        assert client.post(
            INBOX + "/supervision", headers=AUTH
        ).status_code == 200

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)

            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app1)

            started = client.post(A_START, headers=AUTH)
            assert started.status_code == 202

            for _ in range(2):
                move = ack_two_phases(ws, wire)
                stop = ack_two_phases(ws, wire)

                assert move.code == 1
                assert move.duration_ms == 500
                assert stop.code == 0

            finished = wait_status(
                client, A_STATUS, AUTH, "finalizada"
            )
            assert finished["tramos"] == 2

    # Al recrear ASGI, ni el estado final ni la tarea
    # anterior pueden aparecer como una DEMO activa.
    app2 = factory()

    with browser(app2) as client:
        demo = app2.state.kv_demo_coordinator

        assert not demo.active
        assert demo._last is None
        assert app2.state.kx_diag_hub.ready is False

        status = client.get(A_STATUS, headers=AUTH)
        assert status.status_code == 200
        assert status.json()["estado"] == "sin_demo"

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)

            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app2)

            # El nuevo canal no reenvia las ordenes anteriores.
            assert app2.state.kx_diag_hub._seq == 1
            assert not demo.active


def test_close_waits_for_inflight_virtual_stop(restart_factory):
    app = restart_factory()

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)

            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            started = client.post(
                G_START, headers=guest_headers(secret)
            )
            assert started.status_code == 202

            first = ws.receive_json()
            demo = app.state.kv_demo_coordinator
            active = demo._active

            assert active is not None

            # Pedimos cierre del coordinador mientras el
            # simulador aun no confirma la primera orden.
            with ThreadPoolExecutor(max_workers=1) as pool:
                closing = pool.submit(
                    client.portal.call, demo.close
                )

                for _ in range(200):
                    if active.cancel.is_set():
                        break
                    time.sleep(0.005)

                assert active.cancel.is_set()

                move = finish_chunk(ws, wire, first)
                assert move.code == 1

                # Se recoge el STOP virtual firmado antes
                # de terminar el cierre cooperativo.
                assert ack_two_phases(ws, wire).code == 0

                closing.result(timeout=7)

            assert not demo.active
            assert demo.authority.demo_busy is False
            assert active.done.is_set()
            assert active.status == "cancelada"
            assert active.chunks == 1