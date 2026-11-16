"""55-K: pruebas dinamicas de roles con TestClient y WSS virtual."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.public_control.kv_kx_virtual_bridge_lab import (
    LOCAL_ADMIN_ACTION,
    create_kv_kx_virtual_lab_app,
)

from test_kv_kx_virtual_bridge_lab import (
    ADMIN, PROXY, DEVICE, HEAD, AUTH, BASE, INBOX, PATH,
    Clock, browser, authenticate, ack_two_phases,
    wait_ready, guest_request, approve, action,
)


ADMIN_URL = LOCAL_ADMIN_ACTION.replace("{id_vehiculo}", "1")


@pytest.fixture
def role_lab(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    monkeypatch.setenv(
        "KX_KV_VIRTUAL_BRIDGE_LAB", "isolated_ci_only"
    )

    clock = Clock()
    app = create_kv_kx_virtual_lab_app(
        tmp_path / "roles.sqlite3",
        ADMIN, PROXY, DEVICE, clock=clock,
    )
    return app, clock


def admin_action(client, code=9, duration=250, headers=None):
    return client.post(
        ADMIN_URL,
        headers=AUTH if headers is None else headers,
        json={"codigo": code, "duracion_ms": duration},
    )


def test_admin_controls_with_real_signed_wss(role_lab):
    app, _ = role_lab

    with browser(app) as client:
        supervised = client.post(
            INBOX + "/supervision", headers=AUTH
        )
        assert supervised.status_code == 200

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            for code, duration in ((9, 250), (0, 0)):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(
                        admin_action, client, code, duration
                    )

                    order = ack_two_phases(ws, wire)
                    assert order.code == code
                    assert order.duration_ms == duration

                    if code != 0:
                        stop = ack_two_phases(ws, wire)
                        assert stop.code == 0

                    response = pending.result(timeout=7)

                assert response.status_code == 200, response.text
                result = response.json()
                assert result["aceptada"] is True
                assert result["simulado"] is True
                assert result["motor"] is False
                assert result["canDrive"] is False


def test_guest_excludes_admin_and_still_controls(role_lab):
    app, _ = role_lab

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            # El administrador no invade el turno del invitado.
            denied = admin_action(client)
            assert denied.status_code == 403, denied.text

            # El invitado conserva su movimiento firmado.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(
                    action, client, secret, 9, 250
                )

                movement = ack_two_phases(ws, wire)
                stop = ack_two_phases(ws, wire)
                response = pending.result(timeout=7)

            assert movement.code == 9
            assert stop.code == 0
            assert response.status_code == 200, response.text
            assert response.json()["control_fisico"] is False


def test_admin_requires_current_supervision(role_lab):
    app, clock = role_lab

    with browser(app) as client:
        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            assert admin_action(client).status_code == 403

            assert client.post(
                INBOX + "/supervision",
                headers=AUTH,
            ).status_code == 200

            clock.advance(16)
            assert admin_action(client).status_code == 403


def test_invalid_identity_and_unwired_actions_denied(role_lab):
    app, _ = role_lab

    with browser(app) as client:
        assert admin_action(
            client,
            headers={**HEAD, "X-API-Key": "INVALID"},
        ).status_code == 403

        assert admin_action(
            client,
            headers=HEAD,
        ).status_code == 401

        # La DEMO original requiere tratamiento independiente.
        assert admin_action(client, 64, 300).status_code == 422

        # Duraciones fuera de contrato permanecen rechazadas.
        for code in (16, 32, 128):
            assert admin_action(client, code, 99).status_code == 422
            assert admin_action(client, code, 301).status_code == 422

        # El rol no se puede declarar desde el cuerpo JSON.
        response = client.post(
            ADMIN_URL,
            headers=AUTH,
            json={
                "codigo": 9,
                "duracion_ms": 250,
                "rol": "administrador",
            },
        )
        assert response.status_code == 422



def test_admin_signed_auxiliaries_without_guest(role_lab):
    app, _ = role_lab

    with browser(app) as client:
        assert client.post(
            INBOX + "/supervision", headers=AUTH
        ).status_code == 200

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws, allow_auxiliary=True)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            for code in (16, 32, 128):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(
                        admin_action, client, code, 300
                    )

                    auxiliary = ack_two_phases(ws, wire)
                    stop = ack_two_phases(ws, wire)
                    response = pending.result(timeout=7)

                assert auxiliary.code == code
                assert auxiliary.duration_ms == 300
                assert stop.code == 0
                assert response.status_code == 200, response.text
                assert response.json()["motor"] is False
                assert response.json()["canDrive"] is False


def test_guest_signed_auxiliaries_and_exclusive_turn(role_lab):
    app, _ = role_lab

    with browser(app) as client:
        secret, request_id = guest_request(client)
        approve(client, request_id)

        with client.websocket_connect(
            "wss://100-30-4-62.nip.io" + PATH
        ) as ws:
            wire = authenticate(ws, allow_auxiliary=True)
            assert ack_two_phases(ws, wire).code == 0
            wait_ready(app)

            for code in (16, 32, 128):
                # El admin no puede invadir el turno del invitado.
                denied = admin_action(client, code, 300)
                assert denied.status_code == 403, denied.text

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(
                        action, client, secret, code, 300
                    )

                    auxiliary = ack_two_phases(ws, wire)
                    stop = ack_two_phases(ws, wire)
                    response = pending.result(timeout=7)

                assert auxiliary.code == code
                assert auxiliary.duration_ms == 300
                assert stop.code == 0
                assert response.status_code == 200, response.text
                assert response.json()["control_fisico"] is False


def test_auxiliary_default_stays_closed(role_lab):
    app, _ = role_lab

    from app.public_control.kx_signed_wss import KXDiagnosticWSSHub
    from app.public_control.kv_kx_virtual_bridge_lab import VirtualAction
    from pydantic import ValidationError

    closed = KXDiagnosticWSSHub(DEVICE)
    assert closed._allow_auxiliary is False

    # Solo la instancia de CI habilita el protocolo auxiliar.
    assert app.state.kx_diag_hub._allow_auxiliary is True

    for code in (16, 32, 128):
        VirtualAction(codigo=code, duracion_ms=300)
        with pytest.raises(ValidationError):
            VirtualAction(codigo=code, duracion_ms=301)

    with pytest.raises(ValidationError):
        VirtualAction(codigo=64, duracion_ms=300)
