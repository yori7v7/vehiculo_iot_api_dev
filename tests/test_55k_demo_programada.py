"""Pruebas de DEMO 55-K: sin AWS, GPIO o red externa."""
import asyncio
import unittest

from app.public_control.demo_programada_55k import (
    PasoDemo55K,
    validar_plan,
    dividir_duracion,
    ejecutar_demo_virtual,
)


class TestPlan55K(unittest.TestCase):

    def test_plan_original_de_un_segundo(self):
        validar_plan((PasoDemo55K(1, 1000, 1000),), 3)

    def test_division_respeta_duracion(self):
        for duracion in (100, 250, 500, 501, 550, 1000, 1050, 12000):
            tramos = dividir_duracion(duracion)
            self.assertEqual(sum(tramos), duracion)
            self.assertTrue(all(100 <= n <= 500 for n in tramos))

    def test_codigos_prohibidos(self):
        for codigo in (0, 3, 16, 32, 64, 128, True):
            with self.assertRaises(ValueError):
                validar_plan((PasoDemo55K(codigo, 100, 0),), 1)

    def test_tiempos_invalidos(self):
        for duracion in (0, 99, 12001, True):
            with self.assertRaises(ValueError):
                validar_plan((PasoDemo55K(1, duracion, 0),), 1)

        for pausa in (-1, 12001, True):
            with self.assertRaises(ValueError):
                validar_plan((PasoDemo55K(1, 100, pausa),), 1)

    def test_limites_y_plan_vacio(self):
        for pasos, ciclos in (
            ((), 1),
            ((PasoDemo55K(1, 500, 0),), 0),
            ((PasoDemo55K(1, 500, 0),), 4),
            ((PasoDemo55K(1, 12000, 12000),), 3),
        ):
            with self.assertRaises(ValueError):
                validar_plan(pasos, ciclos)


class TestEjecucion55K(unittest.IsolatedAsyncioTestCase):

    async def test_tres_ciclos(self):
        comandos = []

        async def enviar(codigo, duracion):
            comandos.append((codigo, duracion))

        resultado = await ejecutar_demo_virtual(
            (
                PasoDemo55K(1, 1000, 0),
                PasoDemo55K(8, 500, 0),
            ),
            3,
            enviar=enviar,
            autorizado=lambda: True,
            cancelar=asyncio.Event(),
        )

        self.assertEqual(resultado, "finalizada")
        self.assertEqual(
            comandos,
            [(1, 500), (1, 500), (8, 500)] * 3,
        )

    async def test_cancelacion_entre_tramos(self):
        cancelar = asyncio.Event()
        comandos = []

        async def enviar(codigo, duracion):
            comandos.append((codigo, duracion))
            cancelar.set()

        resultado = await ejecutar_demo_virtual(
            (PasoDemo55K(2, 1000, 0),),
            3,
            enviar=enviar,
            autorizado=lambda: True,
            cancelar=cancelar,
        )

        self.assertEqual(resultado, "cancelada")
        self.assertEqual(comandos, [(2, 500)])

    async def test_revocacion_corta_secuencia(self):
        comandos = []
        vigente = True

        async def enviar(codigo, duracion):
            nonlocal vigente
            comandos.append((codigo, duracion))
            vigente = False

        resultado = await ejecutar_demo_virtual(
            (PasoDemo55K(9, 1000, 0),),
            1,
            enviar=enviar,
            autorizado=lambda: vigente,
            cancelar=asyncio.Event(),
        )

        self.assertEqual(resultado, "cancelada")
        self.assertEqual(comandos, [(9, 500)])

    async def test_cancelacion_durante_pausa(self):
        cancelar = asyncio.Event()
        comandos = []

        async def enviar(codigo, duracion):
            comandos.append((codigo, duracion))

        async def detener():
            await asyncio.sleep(0.01)
            cancelar.set()

        tarea = asyncio.create_task(detener())

        resultado = await ejecutar_demo_virtual(
            (
                PasoDemo55K(4, 100, 2000),
                PasoDemo55K(8, 100, 0),
            ),
            1,
            enviar=enviar,
            autorizado=lambda: True,
            cancelar=cancelar,
        )

        await tarea

        self.assertEqual(resultado, "cancelada")
        self.assertEqual(comandos, [(4, 100)])

    async def test_sin_permiso_no_despacha(self):
        async def enviar(codigo, duracion):
            self.fail("No debe enviar movimientos")

        resultado = await ejecutar_demo_virtual(
            (PasoDemo55K(1, 500, 0),),
            1,
            enviar=enviar,
            autorizado=lambda: False,
            cancelar=asyncio.Event(),
        )

        self.assertEqual(resultado, "cancelada")


if __name__ == "__main__":
    unittest.main()