"""55-K: prioridad de STOP sobre DEMO, solo simulador."""
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_55k_demo_coordinator import (
    demo_app, G_START, G_CANCEL,
    guest_headers, finish_chunk,
)
from test_55k_kx_dynamic_roles import ADMIN_URL
from test_kv_kx_virtual_bridge_lab import (
    AUTH, PATH, browser, authenticate, ack_two_phases,
    guest_request, approve, wait_ready,
)

GUEST_URL = "/__lab__/vehiculos/1/accion-virtual"


@pytest.mark.parametrize("actor", ("guest", "admin"))
def test_stop_during_demo(actor, demo_app):
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

            url = ADMIN_URL if actor == "admin" else GUEST_URL
            headers = AUTH if actor == "admin" else guest

            run = app.state.kv_demo_coordinator._active
            assert run is not None

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post,
                    url,
                    headers=headers,
                    json={"codigo": 0, "duracion_ms": 0},
                )

                for _ in range(200):
                    if run.cancel.is_set() and (
                        not app.state.kx_diag_hub.ready
                    ):
                        break
                    time.sleep(0.005)

                assert run.cancel.is_set()
                assert not app.state.kx_diag_hub.ready

                # Final del tramo que ya estaba en vuelo.
                assert finish_chunk(ws, wire, first).code == 1

                # STOP del tramo en vuelo.
                assert ack_two_phases(ws, wire).code == 0

                # STOP adicional solicitado por DETENER.
                assert ack_two_phases(ws, wire).code == 0

                response = future.result(timeout=7)

            assert response.status_code == 200, response.text

            result = response.json()
            assert result["demo_cancelada"] is True
            assert result["codigo"] == 0
            assert result["neutral_virtual_reportado"] is True
            assert result["stop_fisico_confirmado"] is False
            assert result["canDrive"] is False

            assert run.status == "cancelada"
            # El STOP revoco el tramo durante su validacion.
            # Se recibieron ACK, pero K-X no confirmo el tramo
            # como completado despues del interlock.
            assert run.chunks == 0
            assert not app.state.kv_demo_coordinator.active
            assert not app.state.kx_diag_hub.ready


def test_unrelated_guest_cannot_stop_demo(demo_app):
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
            run = app.state.kv_demo_coordinator._active
            assert run is not None

            other = guest_headers(
                secrets.token_urlsafe(32)
            )

            denied = client.post(
                GUEST_URL,
                headers=other,
                json={"codigo": 0, "duracion_ms": 0},
            )

            assert denied.status_code == 403
            assert not run.cancel.is_set()
            assert app.state.kx_diag_hub.ready

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post, G_CANCEL, headers=guest
                )

                for _ in range(200):
                    if run.cancel.is_set():
                        break
                    time.sleep(0.005)

                assert run.cancel.is_set()
                assert finish_chunk(ws, wire, first).code == 1
                assert ack_two_phases(ws, wire).code == 0

                response = future.result(timeout=7)

            assert response.status_code == 200, response.text
            assert response.json()["estado"] == "cancelada"
