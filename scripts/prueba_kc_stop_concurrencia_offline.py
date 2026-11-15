"""Evidencia negativa del STOP bajo concurrencia: SIN red, ESP, AWS ni motores.

El STOP lógico no tiene prioridad sobre una operación que ya obtuvo
controller.lock. Es una prueba para detectar la brecha, NO para autorizar
movimientos físicos. KC real local, despacho sustituido completamente.
"""
from __future__ import annotations

import asyncio
from fastapi import HTTPException
import servidor_55kc as kc
from app.public_control.single_link_admission_lab import (
    SingleLinkAdmissionLab as CanonicalAdmissionGate,
)

ADMIN = "ADMIN-DE-PRUEBA-SOLO-EN-MEMORIA-1234567890123456"
KEY = "K" * 43
SECRET = "S" * 43


class DelayedMemoryKC(kc.KCController):
    def __init__(self):
        super().__init__(ADMIN)
        self.ws = object()
        self.queue = asyncio.Queue()
        self.fence = object()
        self.fault = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.commands: list[str] = []

    async def dispatch(self, code: int, duration: int = 0):
        # Intercepta TODOS los códigos: no llamar jamás a super().dispatch().
        assert type(code) is int and code in (0, 9)
        if code == 9:
            self.commands.append("MOVIMIENTO_ENTRO")
            self.started.set()
            await self.release.wait()
            self.commands.append("MOVIMIENTO_SALIO")
        else:
            self.commands.append("STOP_VIRTUAL")
        self.last_neutral_virtual = True


async def run():
    assert kc.SingleLinkAdmissionLab is CanonicalAdmissionGate
    assert kc.KCController.dispatch is kc.old.LabController.dispatch

    controller = DelayedMemoryKC()
    t = controller.gate.arrive_idempotent(
        idempotency_key=KEY, browser_secret=SECRET,
        client_identity="prueba-local-sin-red"
    )
    await controller.supervisor_pulse()
    await controller.approve_ticket(
        t["request_id"], mode="timed", seconds=60
    )
    assert controller.commands == ["STOP_VIRTUAL"]
    assert controller.gate.visitor_status(SECRET)["estado"] == "autorizado"

    move = asyncio.create_task(controller.move_authorized(
        "guest", 9, 250, browser_secret=SECRET
    ))
    try:
        await asyncio.wait_for(controller.started.wait(), timeout=2.0)
        revoke = asyncio.create_task(controller.revoke_all())
        await asyncio.sleep(0)
        assert controller.gate.visitor_status(SECRET)["estado"] == "revocado_o_caducado"
        assert not revoke.done(), "El STOP revocador debería esperar el lock actual"
        assert controller.commands == ["STOP_VIRTUAL", "MOVIMIENTO_ENTRO"]
        print("1/3 Permiso revocado antes de esperar el lock: OK")
        print("2/3 BRECHA DETECTADA: STOP virtual en espera de un despacho en vuelo")

        controller.release.set()
        result, stopped = await asyncio.wait_for(
            asyncio.gather(move, revoke, return_exceptions=True), timeout=2.0
        )
        # La orden pudo atravesar el despacho antes de la revocacion.
        # NO se permite reportarla como exitosa tras invalidar el ticket.
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert stopped["parada_fisica_verificada"] is False
        assert controller.commands == [
            "STOP_VIRTUAL", "MOVIMIENTO_ENTRO", "MOVIMIENTO_SALIO",
            "STOP_VIRTUAL", "STOP_VIRTUAL"
        ]
        assert controller.gate.visitor_status(SECRET)["estado"] == "revocado_o_caducado"
        print("3/3 Movimiento ya revocado NO regresa exito; STOP virtual posterior: OK")
        print("RESULTADO: SIN FALSO EXITO; STOP NO PREEMPTIVO; NO-GO CONTROL FISICO")
    finally:
        controller.release.set()


if __name__ == "__main__":
    asyncio.run(run())
