import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def leer(ruta):
    return (ROOT / ruta).read_text(encoding="utf-8")


class TestCadena55K(unittest.TestCase):

    def test_permiso_servidor_antes_de_firmar(self):
        kv = leer("app/public_control/kv_kx_virtual_bridge_lab.py")
        kx = leer("app/public_control/kx_signed_wss.py")

        autoridad = kv.split("class VirtualOnlyAuthority:", 1)[1]
        autoridad = autoridad.split(
            "def create_kv_kx_virtual_lab_app", 1
        )[0]

        self.assertLess(
            autoridad.index("ledger.verify_virtual_action(browser_secret)"),
            autoridad.index("await self.hub.execute_virtual(")
        )

        despacho = kx.split("async def execute_virtual(", 1)[1]
        despacho = despacho.split("async def stop_virtual(", 1)[0]

        self.assertLess(
            despacho.index("ledger.verify_virtual_action(browser_secret)"),
            despacho.index("await self._send(code")
        )

    def test_hmac_antes_del_puente(self):
        ino = leer(
            "firmware/Excavadora_IoT_55H_Hotspot_Seguro/"
            "Excavadora_IoT_55H_Hotspot_Seguro.ino"
        )

        orden = ino.split("void order(JsonDocument& doc) {", 1)[1]
        orden = orden.split("void event(", 1)[0]

        self.assertLess(
            orden.index("constantEqual(signature, expected, 32)"),
            orden.index("if (!valid) {")
        )
        self.assertLess(
            orden.index("if (!valid) {"),
            orden.index("grua.registrarPuente55K(")
        )
        self.assertLess(
            orden.index("grua.registrarPuente55K("),
            orden.index("grua.registrarDireccionVirtual(code);")
        )

    def test_stop_y_salida_inhibida(self):
        ino = leer(
            "firmware/Excavadora_IoT_55H_Hotspot_Seguro/"
            "Excavadora_IoT_55H_Hotspot_Seguro.ino"
        )

        orden = ino.split("void order(JsonDocument& doc) {", 1)[1]
        orden = orden.split("void event(", 1)[0]
        stop = orden.split("if (code == 0) {", 1)[1]
        stop = stop.split("} else {", 1)[0]

        self.assertLess(
            stop.index("grua.paradaSeguridad();"),
            stop.index("ack(raw, 1);")
        )

        llamadas = re.findall(r"\bshiftOut\s*\(([^;]+)\);", ino)
        self.assertEqual(len(llamadas), 1)
        self.assertTrue(
            re.sub(r"\s+", "", llamadas[0]).endswith("uint8_t(0)")
        )
        self.assertIn(
            "#define ETAPA54_DIAGNOSTICO_SEGURO 1", ino
        )


if __name__ == "__main__":
    unittest.main()