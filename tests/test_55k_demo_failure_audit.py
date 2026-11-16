"""Auditoria de fallas K-R/K-X: exclusivamente virtual."""
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

from test_55k_demo_coordinator import (
    demo_app,
    G_START,
    G_CANCEL,
    G_STATUS,
    guest_headers,
    wait_status,
    finish_chunk,
)

from test_kv_kx_virtual_bridge_lab import (
    AUTH,
    PATH,
    browser,
    authenticate,
    ack_two_phases,
    guest_request,
    approve,
    wait_ready,
)


def test_supervision_expires_during_signed_order(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)
        headers = guest_headers(secret)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            started = client.post(G_START, headers=headers)
            assert started.status_code == 202

            first = ws.receive_json()

            # La supervision K-R vence durante el tramo.
            clock = app.state.kv_ledger._clock
            clock.advance(16)

            assert finish_chunk(ws, wire, first).code == 1

            # STOP firmado de la operacion ya iniciada.
            assert ack_two_phases(ws, wire).code == 0

            result = wait_status(
                client, G_STATUS, headers, "cancelada"
            )

            assert result["canDrive"] is False
            assert not app.state.kv_demo_coordinator.active

            # No debe poder iniciar otra DEMO sin supervision.
            denied = client.post(G_START, headers=headers)
            assert denied.status_code == 403


def test_websocket_disconnect_releases_virtual_demo(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)
        headers = guest_headers(secret)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            started = client.post(G_START, headers=headers)
            assert started.status_code == 202

            # Recibir la orden y desconectar sin enviar ACK.
            first = ws.receive_json()
            assert first["tipo"] == "orden_dispositivo_v1"

        # Sin WSS, la DEMO debe finalizar como error virtual.
        result = wait_status(
            client, G_STATUS, headers, "error_virtual"
        )

        assert result["control_fisico"] is False
        assert result["stop_fisico_confirmado"] is False
        assert not app.state.kv_demo_coordinator.active

        # No reanudar automaticamente tras perder conexion.
        restart = client.post(G_START, headers=headers)
        assert restart.status_code == 403


def test_other_controller_cannot_cancel_active_demo(demo_app):
    app = demo_app

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)
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

            # Otro invitado no es propietario de la DEMO.
            other = secrets.token_urlsafe(32)
            denied = client.post(
                G_CANCEL,
                headers=guest_headers(other),
            )
            assert denied.status_code == 403

            # El administrador no invade el turno cancelando
            # como propietario; conserva la revocacion K-R.
            admin_cancel = client.post(
                "/__lab__/vehiculos/1/demo-programada/admin/cancelar",
                headers=AUTH,
            )
            assert admin_cancel.status_code == 403

            active = app.state.kv_demo_coordinator._active
            assert active is not None
            assert not active.cancel.is_set()

            # El propietario SI puede cancelar.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    client.post, G_CANCEL, headers=headers
                )

                for _ in range(200):
                    if active.cancel.is_set():
                        break
                    time.sleep(0.005)

                assert active.cancel.is_set()

                assert finish_chunk(ws, wire, first).code == 1
                assert ack_two_phases(ws, wire).code == 0

                response = future.result(timeout=7)

            assert response.status_code == 200, response.text
            assert response.json()["estado"] == "cancelada"
            assert response.json()["tramos"] == 1
            assert not app.state.kv_demo_coordinator.active