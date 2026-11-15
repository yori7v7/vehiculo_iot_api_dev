"""Safety contracts: neither substitute for GPIO measurement nor Arduino compile."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
INO = ROOT / "firmware/Excavadora_IoT_55H_Hotspot_Seguro/Excavadora_IoT_55H_Hotspot_Seguro.ino"


def source():
    return INO.read_text(encoding="utf-8")


def test_only_zero_may_reach_shift_register():
    s = source()
    calls = re.findall(r"\bshiftOut\s*\(([^;]+)\);", s)
    assert len(calls) == 1
    assert calls[0].replace(" ", "").replace("\n", "").endswith("uint8_t(0)")
    assert '#if ETAPA54_DIAGNOSTICO_SEGURO != 1' in s
    assert '#error "55-H no permite habilitar el actuador."' in s
    assert "grua.ejecutarCodigoAWS" not in s
    assert "grua.procesarComandoManual" not in s


def test_eight_directions_are_theoretical_only():
    s = source()
    mapping = dict(re.findall(r"case\s+(\d+)\s*:\s*return\s+B([01]{8})", s))
    assert {int(k): int(v, 2) for k,v in mapping.items()} == {
        1: 1, 2: 2, 4: 4, 5: 5, 6: 6, 8: 8, 9: 9, 10: 10,
    }
    assert "case 0: return 0;" in s
    assert "grua.registrarDireccionVirtual(code);" in s


def test_signed_wss_and_fail_closed():
    s = source()
    for token in (
        "LAB55H_DEVICE_KEY", "vehiculo-iot|device-order-v1|",
        "vehiculo-iot|device-order-ack-v1|",
        "ws.beginSslWithCA", "LAB55H_CA_CERT",
        "constantEqual(signature, expected, 32)",
        "sequence == lastSeq + 1", "caducarPendienteVirtual();",
        "grua.paradaSeguridad()", "if (started) {", "started = false;",
    ):
        assert token in s
    assert "setInsecure(" not in s


def test_hotspot_2ghz_wifi_manager_not_hardcoded():
    s = source()
    for forbidden in ("LAB55H_WIFI_PASSWORD", "LAB55H_WIFI_SSID", "WiFi.begin(",
                      "W = Avanzar", "grua.avanzar()"):
        assert forbidden not in s
    for required in (
        "portal.autoConnect(nombreAp.c_str(), LAB55H_AP_PASSWORD)",
        "portal.process();", "setConfigPortalBlocking(false)",
        "digitalRead(RESET_WIFI_PIN)", "millis() - inicioPulso >= 5000UL",
        "LAB55H_WS_PATH",
    ):
        assert required in s


def test_local_generator_creates_private_identity(tmp_path, monkeypatch):
    from scripts import preparar_55h_hotspot_seguro as provision

    sketch = tmp_path / "sketch"
    sketch.mkdir()
    (sketch / INO.name).write_text(source(), encoding="utf-8")
    monkeypatch.setattr(provision, "SKETCH", sketch)
    monkeypatch.setattr(provision, "PRIVATE", sketch / "private")
    with pytest.raises(ValueError):
        provision.prepare("127.0.0.1", "CI-PASSWORD-123")
    with pytest.raises(ValueError):
        provision.prepare("192.168.4.2", "corta")
    conf = provision.prepare("192.168.4.2", "CI-PASSWORD-123", ci_fixture=True)
    t = conf.read_text()
    assert "LAB55H_AP_PASSWORD" in t
    assert "LAB55H_DEVICE_KEY[32]" in t
    assert "LAB55H_CA_CERT" in t
    assert "LAB55H_WS_PATH" in t
    assert "LAB55H_WIFI_PASSWORD" not in t
    assert (sketch / "private/device-key.bin").stat().st_size == 32
    assert not (ROOT / "config_55h_local.h").exists()
