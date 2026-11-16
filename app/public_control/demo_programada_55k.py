"""Planificador virtual 55-K. No conecta GPIO, AWS ni RDS.

Los pasos deben proceder de un plan confiable del servidor,
nunca directamente de un listado enviado por el navegador.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

DIRECCIONES = frozenset((1, 2, 4, 5, 6, 8, 9, 10))


@dataclass(frozen=True)
class PasoDemo55K:
    codigo: int
    duracion_ms: int
    pausa_ms: int


def validar_plan(
    pasos: tuple[PasoDemo55K, ...],
    ciclos: int,
) -> None:
    if type(pasos) is not tuple or not 1 <= len(pasos) <= 16:
        raise ValueError("Plan de DEMO invalido")

    if type(ciclos) is not int or not 1 <= ciclos <= 3:
        raise ValueError("Numero de ciclos invalido")

    total = 0

    for paso in pasos:
        if not isinstance(paso, PasoDemo55K):
            raise ValueError("Paso de DEMO invalido")

        if (
            type(paso.codigo) is not int
            or paso.codigo not in DIRECCIONES
            or type(paso.duracion_ms) is not int
            or not 100 <= paso.duracion_ms <= 12000
            or type(paso.pausa_ms) is not int
            or not 0 <= paso.pausa_ms <= 12000
        ):
            raise ValueError("Paso fuera del contrato seguro")

        total += paso.duracion_ms + paso.pausa_ms

    if total * ciclos > 60000:
        raise ValueError("DEMO supera 60 segundos")


def dividir_duracion(duracion_ms: int) -> tuple[int, ...]:
    if type(duracion_ms) is not int or not 100 <= duracion_ms <= 12000:
        raise ValueError("Duracion invalida")

    cantidad = (duracion_ms + 499) // 500
    base, sobrante = divmod(duracion_ms, cantidad)

    tramos = (
        (base + 1,) * sobrante
        + (base,) * (cantidad - sobrante)
    )

    if any(not 100 <= tramo <= 500 for tramo in tramos):
        raise ValueError("No se puede dividir la duracion")

    return tramos


async def ejecutar_demo_virtual(
    pasos: tuple[PasoDemo55K, ...],
    ciclos: int,
    *,
    enviar: Callable[[int, int], Awaitable[object]],
    autorizado: Callable[[], bool],
    cancelar: asyncio.Event,
) -> str:
    """Ejecuta tramos virtuales y cancela cooperativamente.

    'enviar' DEBE implementar validacion K-R, WSS firmado,
    STOP y ACK bajo la autoridad compartida de K-X.

    No certifica una parada fisica.
    """
    validar_plan(pasos, ciclos)

    if not isinstance(cancelar, asyncio.Event):
        raise TypeError("Cancelacion invalida")

    for _ in range(ciclos):
        for paso in pasos:
            for tramo in dividir_duracion(paso.duracion_ms):

                if cancelar.is_set() or not autorizado():
                    return "cancelada"

                await enviar(paso.codigo, tramo)

                if cancelar.is_set() or not autorizado():
                    return "cancelada"

            if paso.pausa_ms:
                if cancelar.is_set() or not autorizado():
                    return "cancelada"

                try:
                    await asyncio.wait_for(
                        cancelar.wait(),
                        timeout=paso.pausa_ms / 1000,
                    )
                    return "cancelada"
                except TimeoutError:
                    pass

    if cancelar.is_set() or not autorizado():
        return "cancelada"

    return "finalizada"