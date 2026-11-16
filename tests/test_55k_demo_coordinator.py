"""55-K: rutas reales del coordinador DEMO virtual."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.device_channel.command_wire import (
    DeviceAck, PHASE_RECEIVED, PHASE_NEUTRAL,
)
from app.public_control.demo_programada_55k import PasoDemo55K
from app.public_control.kv_kx_virtual_bridge_lab import (
    create_kv_kx_virtual_lab_app,
)

from test_kv_kx_virtual_bridge_lab import (
    ADMIN, PROXY, DEVICE, HEAD, AUTH, INBOX, PATH,
    Clock, browser, authenticate, ack_two_phases,
    wait_ready, guest_request, approve,
)
from test_55k_kx_dynamic_roles import ADMIN_URL

PREFIX = "/__lab__/vehiculos/1/demo-programada"
A_START = PREFIX + "/admin/iniciar"
G_START = PREFIX + "/iniciar"
A_STATUS = PREFIX + "/admin/estado"
G_STATUS = PREFIX + "/estado"
G_CANCEL = PREFIX + "/cancelar"


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv(
        "KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only"
    )

    return create_kv_kx_virtual_lab_app(
        tmp_path / "coordinator.sqlite3",
        ADMIN, PROXY, DEVICE,
        clock=Clock(),
        demo_plan=(PasoDemo55K(1, 1000, 0),),
        demo_cycles=1,
    )


def guest_headers(secret):
    return {**HEAD, "X-Browser-Session": secret}


def wait_status(client, url, headers, expected):
    for _ in range(200):
        response = client.get(url, headers=headers)

        if (
            response.status_code == 200
            and response.json()["estado"] == expected
        ):
            return response.json()

        time.sleep(0.01)

    pytest.fail("DEMO no alcanzo estado esperado")


def finish_chunk(ws, wire, frame):
    order = wire.verify_order(
        frame, now_ms=int(time.time() * 1000)
    )

    for phase, neutral in (
        (PHASE_RECEIVED, False),
        (PHASE_NEUTRAL, True),
    ):
        ack = DeviceAck(
            1, order.session_id, order.operation_id,
            order.generation, order.epoch,
            order.sequence,
            int(time.time() * 1000),
            phase, neutral,
        )
        ws.send_json(wire.sign_ack(ack))

    return order


@pytest.mark.parametrize("role", ("admin", "guest"))
def test_demo_from_real_coordinator(demo_app, role):
    app = demo_app

    with browser(app) as client:
        if role == "admin":
            assert client.post(
                INBOX + "/supervision", headers=AUTH
            ).status_code == 200
            headers = AUTH
            start_url = A_START
            status_url = A_STATUS
        else:
            secret, rid = guest_request(client)
            approve(client, rid)
            headers = guest_headers(secret)
            start_url = G_START
            status_url = G_STATUS

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            started = client.post(
                start_url, headers=headers
            )
            assert started.status_code == 202, started.text
            assert started.json()["estado"] == "iniciada"

            manual_url = (
                ADMIN_URL
                if role == "admin"
                else "/__lab__/vehiculos/1/accion-virtual"
            )

            manual = client.post(
                manual_url,
                headers=headers,
                json={"codigo": 9, "duracion_ms": 250},
            )
            assert manual.status_code == 409, manual.text

            for _ in range(2):
                move = ack_two_phases(ws, wire)
                stop = ack_two_phases(ws, wire)
                assert (move.code, move.duration_ms) == (1, 500)
                assert stop.code == 0

            result = wait_status(
                client, status_url, headers, "finalizada"
            )
            assert result["tramos"] == 2
            assert result["canDrive"] is False


def test_guest_cancel_during_signed_command(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, rid = guest_request(client)
        approve(client, rid)
        headers = guest_headers(secret)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            assert client.post(
                G_START, headers=headers
            ).status_code == 202

            first = ws.receive_json()

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post, G_CANCEL, headers=headers
                )

                for _ in range(200):
                    run = app.state.kv_demo_coordinator._active
                    if run is not None and run.cancel.is_set():
                        break
                    time.sleep(0.005)

                assert run.cancel.is_set()

                assert finish_chunk(ws, wire, first).code == 1
                assert ack_two_phases(ws, wire).code == 0

                cancelled = future.result(timeout=7)

            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["estado"] == "cancelada"
            assert cancelled.json()["tramos"] == 1


def test_admin_revoke_preempts_demo(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, rid = guest_request(client)
        approve(client, rid)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            assert client.post(
                G_START, headers=guest_headers(secret)
            ).status_code == 202

            first = ws.receive_json()

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post,
                    INBOX + "/revocar",
                    headers=AUTH,
                )

                for _ in range(200):
                    if not app.state.kx_diag_hub.ready:
                        break
                    time.sleep(0.005)

                assert not app.state.kx_diag_hub.ready

                assert finish_chunk(ws, wire, first).code == 1
                assert ack_two_phases(ws, wire).code == 0

                # STOP de la revocacion administrativa.
                assert ack_two_phases(ws, wire).code == 0

                revoked = future.result(timeout=7)

            assert revoked.status_code == 200
            for _ in range(200):
                if not app.state.kv_demo_coordinator.active:
                    break
                time.sleep(0.005)
            assert not app.state.kv_demo_coordinator.active
            assert revoked.json()["stop_fisico_confirmado"] is False


def test_no_plan_and_no_browser_defined_steps(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv(
        "KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only"
    )

    app = create_kv_kx_virtual_lab_app(
        tmp_path / "closed.sqlite3",
        ADMIN, PROXY, DEVICE, clock=Clock(),
    )

    with browser(app) as client:
        assert client.post(
            INBOX + "/supervision", headers=AUTH
        ).status_code == 200

        # Sin WSS autenticado: se deniega el control.
        assert client.post(
            A_START, headers=AUTH
        ).status_code == 403

        # Con WSS autenticado, pero sin plan de servidor:
        # el servicio debe responder 503.
        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            response = client.post(A_START, headers=AUTH)
            assert response.status_code == 503

        forged = client.post(
            A_START,
            headers=AUTH,
            json={
                "rol": "administrador",
                "pasos": [{"codigo": 64, "duracion_ms": 300}],
            },
        )
        assert forged.status_code == 400
