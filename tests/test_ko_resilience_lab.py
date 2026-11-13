"""5.5-K-O: resiliencia de admision en el backend, sin red, WSS ni motores.

Esta bateria verifica el modelo de turnos y los cierres de autoridad. NO
prueba STOP mecanico ni autoriza la publicacion de las rutas de laboratorio.
"""
from __future__ import annotations

import asyncio
import ast
from pathlib import Path

import pytest

from app.public_control.single_link_admission_lab import (
    AdmissionDenied, SingleLinkAdmissionLab,
)

ADMIN = "token-administrativo-KO-ficticio-" + "x" * 36


class FakeClock:
    def __init__(self):
        self.time = 100.0

    def __call__(self):
        return self.time

    def advance(self, seconds):
        self.time += seconds


def rig():
    clock = FakeClock()
    return SingleLinkAdmissionLab(ADMIN, clock=clock), clock


def ready(gate, ticket, *, mode="timed", seconds=120):
    gate.supervisor_heartbeat(ADMIN)
    gate.neutral_confirmed_by_transport_for_lab(
        ADMIN, signed_neutral_ack=True
    )
    gate.approve(
        ADMIN, ticket["request_id"], mode=mode,
        turn_seconds=seconds if mode == "timed" else None,
    )


def test_ko_stale_ticket_cannot_be_approved_after_expiration():
    gate, clock = rig()
    ticket = gate.arrive()
    clock.advance(120)
    gate.supervisor_heartbeat(ADMIN)
    gate.neutral_confirmed_by_transport_for_lab(ADMIN, signed_neutral_ack=True)
    with pytest.raises(AdmissionDenied):
        gate.approve(ADMIN, ticket["request_id"], mode="timed", turn_seconds=120)
    assert gate.visitor_status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    assert gate.snapshot()["guest_active"] is False


def test_ko_supervisor_heartbeat_timeout_invalidates_guest_and_requires_neutral():
    gate, clock = rig()
    ticket = gate.arrive()
    ready(gate, ticket, mode="supervised")
    assert gate.visitor_status(ticket["browser_secret"])["estado"] == "autorizado"
    clock.advance(15)
    assert gate.visitor_status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    assert gate.snapshot()["guest_active"] is False
    assert gate.snapshot()["stop_required"] is True
    another = gate.arrive()
    gate.supervisor_heartbeat(ADMIN)
    with pytest.raises(AdmissionDenied):
        gate.approve(ADMIN, another["request_id"], mode="supervised")
    gate.neutral_confirmed_by_transport_for_lab(ADMIN, signed_neutral_ack=True)
    gate.approve(ADMIN, another["request_id"], mode="supervised")
    assert gate.visitor_status(another["browser_secret"])["estado"] == "autorizado"


def test_ko_timed_turn_expires_even_while_supervisor_renews():
    gate, clock = rig()
    ticket = gate.arrive()
    ready(gate, ticket, mode="timed", seconds=30)
    assert gate.snapshot()["guest_active"] is True
    for _ in range(3):
        clock.advance(10)
        gate.supervisor_heartbeat(ADMIN)
    assert gate.visitor_status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    assert gate.snapshot()["guest_active"] is False
    assert gate.snapshot()["stop_required"] is True


def test_ko_device_disconnect_revokes_all_tickets_and_blocks_old_secrets():
    gate, clock = rig()
    ticket = gate.arrive()
    ready(gate, ticket)
    before = gate.snapshot()["generation"]
    gate.device_lost()
    assert gate.snapshot()["guest_active"] is False
    assert gate.snapshot()["generation"] > before
    assert gate.visitor_status(ticket["browser_secret"])["estado"] == "revocado_o_caducado"
    assert gate.snapshot()["stop_required"] is True
    gate.supervisor_heartbeat(ADMIN)
    next_ticket = gate.arrive()
    with pytest.raises(AdmissionDenied):
        gate.approve(ADMIN, next_ticket["request_id"], mode="timed", turn_seconds=120)


def test_ko_rollback_of_monotonic_clock_revokes_guest():
    gate, clock = rig()
    ticket = gate.arrive()
    ready(gate, ticket)
    clock.time -= 2
    with pytest.raises(AdmissionDenied):
        gate.snapshot()
    clock.time += 3
    assert gate.snapshot()["guest_active"] is False
    assert gate.snapshot()["stop_required"] is True


@pytest.mark.asyncio
async def test_ko_concurrent_approve_revoke_cannot_leave_guest_active():
    """Simular la transaccion del controlador K-C con SU MISMO lock."""
    for _ in range(8):
        gate, clock = rig()
        ticket = gate.arrive()
        gate.supervisor_heartbeat(ADMIN)
        lock = asyncio.Lock()

        async def approve():
            async with lock:
                await asyncio.sleep(0)
                gate.neutral_confirmed_by_transport_for_lab(
                    ADMIN, signed_neutral_ack=True
                )
                gate.approve(
                    ADMIN, ticket["request_id"], mode="timed", turn_seconds=120
                )

        async def revoke():
            async with lock:
                await asyncio.sleep(0)
                gate.revoke(ADMIN)

        results = await asyncio.gather(approve(), revoke(), return_exceptions=True)
        assert all(isinstance(x, (type(None), AdmissionDenied)) for x in results)
        assert gate.snapshot()["guest_active"] is False
        assert gate.snapshot()["simulated_only"] is True


def test_ko_local_script_syntax_get_only_and_no_unsafe_tls():
    source = (Path(__file__).resolve().parents[1] / "scripts"
              / "prueba_55ko_reconexion_local.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="prueba_55ko_reconexion_local.py")
    # La prueba remota K-O puede LEER el estado, nunca escribir permisos ni movimientos.
    methods = [node.args[0].value for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "call"
               and node.args and isinstance(node.args[0], ast.Constant)]
    assert methods == ["GET"]
    assert "/movimientos" not in source and "/accion" not in source
    assert "CERT_NONE" not in source and "check_hostname = False" not in source
