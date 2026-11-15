"""55-K: contratos estaticos de seguridad, sin hardware."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SAFE = ROOT / (
    "firmware/Excavadora_IoT_55H_Hotspot_Seguro/"
    "Excavadora_IoT_55H_Hotspot_Seguro.ino"
)

LEGACY = ROOT / (
    "firmware/Excavadora_IoT_AWS/"
    "Excavadora_IoT_AWS.ino"
)


class TestContrato55K(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.safe = SAFE.read_text(encoding="utf-8")
        cls.legacy = LEGACY.read_text(encoding="utf-8")

    def test_01_registro_solo_cero(self):
        calls = re.findall(
            r"\bshiftOut\s*\(([^;]+)\);",
            self.safe
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(
            re.sub(r"\s+", "", calls[0]).endswith(
                "uint8_t(0)"
            )
        )
        self.assertIn(
            "#define ETAPA54_DIAGNOSTICO_SEGURO 1",
            self.safe
        )

    def test_02_ocho_direcciones_virtuales(self):
        pairs = re.findall(
            r"case\s+(\d+)\s*:\s*return\s+B([01]{8})",
            self.safe
        )
        mapping = {
            int(code): int(bits, 2)
            for code, bits in pairs
        }
        self.assertEqual(
            mapping,
            {1: 1, 2: 2, 4: 4, 5: 5,
             6: 6, 8: 8, 9: 9, 10: 10}
        )

    def test_03_validacion_antes_de_orden(self):
        section = self.safe.split(
            "void order(JsonDocument& doc) {", 1
        )[1].split("void event(", 1)[0]

        self.assertIn(
            "constantEqual(signature, expected, 32)",
            section
        )
        self.assertLess(
            section.index("if (!valid) {"),
            section.index(
                "grua.registrarDireccionVirtual(code);"
            )
        )

    def test_04_stop_antes_de_ack(self):
        section = self.safe.split(
            "void order(JsonDocument& doc) {", 1
        )[1].split("void event(", 1)[0]

        self.assertLess(
            section.index("grua.paradaSeguridad();"),
            section.index("ack(raw, 1);")
        )

    def test_05_referencia_fisica_conservada(self):
        for token in (
            "class GruaRC",
            "shiftOut(dataPin, clockPin, MSBFIRST, valor)",
            "delay(30)",
            "MAX_MOVIMIENTO_INDIVIDUAL_MS = 12000UL",
            "void ejecutarCodigoAWS",
        ):
            self.assertIn(token, self.legacy)

        for code in (5, 6, 9, 10):
            self.assertIn(
                "case {}:".format(code),
                self.legacy
            )


    def test_06_integracion_wss_sombra(self):
        s = self.safe
        self.assertIn('#include "Controlador55KInhibido.h"', s)
        self.assertIn("Controlador55KInhibido sombra55K;", s)

        order = s.split(
            "void order(JsonDocument& doc) {", 1
        )[1].split("void event(", 1)[0]

        self.assertLess(
            order.index("if (!valid) {"),
            order.index("grua.registrarSombra55K(code, duration)")
        )

        self.assertLess(
            order.index("grua.registrarSombra55K(code, duration)"),
            order.index("grua.registrarDireccionVirtual(code);")
        )

        self.assertIn(
            "grua.actualizarSombra55K();",
            s
        )

    def test_07_paradas_convergentes(self):
        s = self.safe
        stop = s.split(
            "void paradaSeguridadSilenciosa() {", 1
        )[1].split("void paradaSeguridad() {", 1)[0]

        self.assertIn("sombra55K.detener();", stop)
        self.assertIn("enviarCero();", stop)
        self.assertIn(
            "void paradaSeguridad() {\n"
            "    paradaSeguridadSilenciosa();",
            s
        )

        for token in (
            "grua.paradaSeguridad();",
            "grua.paradaSeguridadSilenciosa();",
            "if (code == 0)",
            "WStype_DISCONNECTED",
            "WiFi.status() != WL_CONNECTED",
        ):
            self.assertIn(token, s)


if __name__ == "__main__":
    unittest.main()
