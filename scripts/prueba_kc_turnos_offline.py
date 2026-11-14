"""Prueba local y aislada del KCController real con despacho REEMPLAZADO por memoria.

No abrir sockets, no leer carpeta private, no iniciar FastAPI ni WSS,
no usar AWS, no ESP, no GPIO. Los resultados son lógicos, NO físicos.
Ejecutar con PYTHONPATH que incluya repo experimental y carpeta local de KC.
"""
from __future__ import annotations

import asyncio

from fastapi import HTTPException
import servidor_55kc as kc
from app.public_control.single_link_admission_lab import (
    SingleLinkAdmissionLab as CanonicalAdmissionGate,
)

ADMIN = "ADMIN-FICTICIO-DE-PRUEBA-KC-EXCLUSIVAMENTE-VIRTUAL"
RETRY_KEY = "A" * 43
BROWSER_SECRET = "B" * 43
CLIENT_ID = "local-sin-red"


class MemoryOnlyKC(kc.KCController):
    """Simula canal conectado y SOLO intercepta dispatch: jamás llama al padre."""

    def __init__(self):
        super().__init__(ADMIN)
        # Satisfacen connected del LabController sin conectar red/sesiones.
        self.ws = object()
        self.queue = asyncio.Queue()
        self.fence = object()
        self.fault = False
        self.sent: list[tuple[int, int]] = []

    async def dispatch(self, code: int, duration: int = 0):
        # Intercepción terminal deliberada: NUNCA super().dispatch().
        assert type(code) is int and code in (0, 9)
        self.sent.append((code, duration))
        self.last_neutral_virtual = True


async def must_deny(awaitable, *, status: int):
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status, (
            f"Se esperaba HTTP {status}, recibido {error.status_code}")
    else:
        raise AssertionError(f"Una operación sin autorización fue aceptada (HTTP {status}).")


async def run():
    assert kc.SingleLinkAdmissionLab is CanonicalAdmissionGate, (
        "NO-GO: KC no comparte el gate con el backend experimental")
    assert kc.KCController.dispatch is kc.old.LabController.dispatch, (
        "NO-GO: KC tiene un despacho inesperado")
    ctl = MemoryOnlyKC()

    ticket = ctl.gate.arrive_idempotent(
        idempotency_key=RETRY_KEY, browser_secret=BROWSER_SECRET,
        client_identity=CLIENT_ID)
    replay = ctl.gate.arrive_idempotent(
        idempotency_key=RETRY_KEY, browser_secret=BROWSER_SECRET,
        client_identity=CLIENT_ID)
    assert ticket["request_id"] == replay["request_id"]
    assert replay["idempotent_replay"] is True
    assert ctl.gate.snapshot()["pendientes"] == 1
    assert ctl.sent == []
    print("1/6 Solicitud y reintento con el mismo ticket: OK")

    await must_deny(ctl.move_authorized("guest", 9, 250, BROWSER_SECRET), status=409)
    assert ctl.sent == []
    print("2/6 Sin aprobación no hay movimiento virtual: OK")

    await ctl.supervisor_pulse()
    approved = await ctl.approve_ticket(
        ticket["request_id"], mode="timed", seconds=60)
    assert approved["aprobada"] is True
    assert ctl.gate.visitor_status(BROWSER_SECRET)["estado"] == "autorizado"
    assert ctl.sent == [(0, 0)]
    print("3/6 Aprobación individual y STOP previo virtual: OK")

    await must_deny(ctl.move_authorized("guest", 9, 250, "C" * 43), status=403)
    await must_deny(ctl.move_authorized("admin", 9, 250), status=409)
    assert ctl.sent == [(0, 0)]
    print("4/6 Invitado ajeno y administrador sin turno bloqueados: OK")

    result = await ctl.move_authorized(
        "guest", 9, 250, browser_secret=BROWSER_SECRET)
    assert result["aceptada"] is True and result["motor"] is False
    assert ctl.sent == [(0, 0), (9, 250), (0, 0)]
    print("5/6 Orden virtual autorizada y STOP posterior: OK")

    revoked = await ctl.revoke_all()
    assert revoked["parada_fisica_verificada"] is False
    assert ctl.gate.visitor_status(BROWSER_SECRET)["estado"] == "revocado_o_caducado"
    assert ctl.sent == [(0, 0), (9, 250), (0, 0), (0, 0)]
    await must_deny(ctl.move_authorized(
        "guest", 9, 250, browser_secret=BROWSER_SECRET), status=409)
    assert len(ctl.sent) == 4
    print("6/6 Revocación, STOP virtual y bloqueo posterior: OK")
    print("KC_TURNOS_OFFLINE_OK | SIN RED | SIN WSS | SIN MOTORES")


if __name__ == "__main__":
    asyncio.run(run())
