"""55-K: MONITOREO virtual sin credenciales ni falsas garantias."""
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

from test_55k_demo_coordinator import (
    demo_app, G_START, G_STATUS, guest_headers,
    wait_status, finish_chunk,
)
from test_55k_kx_dynamic_roles import ADMIN_URL
from test_kv_kx_virtual_bridge_lab import (
    AUTH, HEAD, PATH, browser, authenticate,
    ack_two_phases, guest_request, approve, wait_ready,
)

MONITOR = "/__lab__/vehiculos/1/monitoreo-demo"

FIELDS = {
    "estado", "demo_activa", "tramos_intentados",
    "tramos_confirmados", "tramos_sin_confirmar",
    "ordenes_wss_emitidas", "wss_disponible",
    "simulado", "control_fisico", "canDrive",
    "stop_fisico_confirmado",
}


def read_monitor(client):
    response = client.get(MONITOR, headers=HEAD)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == FIELDS
    assert data["simulado"] is True
    assert data["control_fisico"] is False
    assert data["canDrive"] is False
    assert data["stop_fisico_confirmado"] is False
    assert data["ordenes_wss_emitidas"] is None
    return data


def test_monitor_without_login_or_private_credentials(demo_app):
    with browser(demo_app) as client:
        data = read_monitor(client)

        assert data["estado"] == "sin_demo"
        assert data["demo_activa"] is False
        assert data["tramos_intentados"] == 0
        assert data["tramos_confirmados"] == 0
        assert data["tramos_sin_confirmar"] == 0
        assert data["wss_disponible"] is False

        assert client.get(
            MONITOR, headers=AUTH
        ).status_code == 403

        assert client.get(
            MONITOR,
            headers={
                **HEAD,
                "X-Browser-Session": secrets.token_urlsafe(32),
            },
        ).status_code == 403

        assert client.get(
            MONITOR, headers=HEAD, params={"debug": "1"}
        ).status_code == 403


def test_monitor_distinguishes_attempt_and_confirmation(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)
        guest = guest_headers(secret)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            assert client.post(
                G_START, headers=guest
            ).status_code == 202

            first = ws.receive_json()

            running = read_monitor(client)

            assert running["estado"] == "ejecutando"
            assert running["demo_activa"] is True
            assert running["tramos_intentados"] == 1
            assert running["tramos_confirmados"] == 0
            assert running["tramos_sin_confirmar"] == 1

            run = app.state.kv_demo_coordinator._active
            assert run is not None

            # DETENER prioritario durante el tramo pendiente.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post,
                    ADMIN_URL,
                    headers=AUTH,
                    json={"codigo": 0, "duracion_ms": 0},
                )

                for _ in range(200):
                    if run.cancel.is_set() and (
                        not app.state.kx_diag_hub.ready
                    ):
                        break
                    time.sleep(0.005)

                assert run.cancel.is_set()

                cancelling = read_monitor(client)

                assert cancelling["estado"] == "cancelando"
                assert cancelling["demo_activa"] is True
                assert cancelling["tramos_intentados"] == 1
                assert cancelling["tramos_confirmados"] == 0

                assert finish_chunk(ws, wire, first).code == 1
                assert ack_two_phases(ws, wire).code == 0
                assert ack_two_phases(ws, wire).code == 0

                stopped = future.result(timeout=7)

            assert stopped.status_code == 200

            final = read_monitor(client)

            assert final["estado"] == "cancelada"
            assert final["demo_activa"] is False
            assert final["tramos_intentados"] == 1
            assert final["tramos_confirmados"] == 0
            assert final["tramos_sin_confirmar"] == 1
            assert final["wss_disponible"] is False


def test_monitor_reports_completed_chunks(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)
        guest = guest_headers(secret)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            assert client.post(
                G_START, headers=guest
            ).status_code == 202

            for _ in range(2):
                assert ack_two_phases(ws, wire).code == 1
                assert ack_two_phases(ws, wire).code == 0

            wait_status(client, G_STATUS, guest, "finalizada")

            final = read_monitor(client)

            assert final["estado"] == "finalizada"
            assert final["demo_activa"] is False
            assert final["tramos_intentados"] == 2
            assert final["tramos_confirmados"] == 2
            assert final["tramos_sin_confirmar"] == 0
            assert final["wss_disponible"] is True
