"""Pruebas offline de cabecera AWS privada: no ESP, no AWS ni secretos reales."""
from __future__ import annotations

from hashlib import sha256
import json

import pytest

from scripts import preparar_config_kx_firmware_privada as stage


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    identity = tmp_path / "identity"
    candidate.mkdir()
    identity.mkdir()
    source = (
        '#include "config_55h_local.h"\n'
        '#ifndef KX_AWS_TLS_CONFIG_OK\n#error "No compilar"\n#endif\n'
        '#define ETAPA54_DIAGNOSTICO_SEGURO 1\n'
        '#if ETAPA54_DIAGNOSTICO_SEGURO != 1\n#error "Motores"\n#endif\n'
        'ws.beginSslWithCA(LAB55H_HOST, LAB55H_PORT,'
        ' "/ws/kx-diagnostico/1", LAB55H_CA_CERT);\n'
    ).encode()
    (candidate / stage.SKETCH_NAME).write_bytes(source)
    monkeypatch.setattr(stage, "FIRMWARE_SHA256", sha256(source).hexdigest())
    old = (
        '#pragma once\n'
        '#define LAB55H_CONFIG_VALID 1\n'
        'const char* LAB55H_WIFI_SSID = "SSID_DE_EJEMPLO";\n'
        'const char* LAB55H_WIFI_PASSWORD = "PASS_DE_EJEMPLO";\n'
        'const char* LAB55H_HOST = "192.168.1.82";\n'
        'const uint16_t LAB55H_PORT = 8443;\n'
        'const uint8_t LAB55H_DEVICE_KEY[32] = { 0x17, 0x1A };\n'
        'const char LAB55H_CA_CERT[] PROGMEM = R"EOF(\nOLD LAN CA\n)EOF";\n'
    ).encode()
    (candidate / stage.HEADER_NAME).write_bytes(old)
    (candidate / "ISRG_Root_X1_public.pem").write_text("FAKE PUBLIC CA")
    monkeypatch.setattr(stage, "_read_root_ca", lambda _path: "PUBLIC CA FOR TEST\n")
    secret = bytes(range(32))
    (identity / "kx-device-1-key.bin").write_bytes(secret)
    manifest = {
        "key_fingerprint_sha256": sha256(secret).hexdigest().upper(),
        "host": stage.WSS_HOST,
        "port": stage.WSS_PORT,
        "path": stage.WSS_PATH,
        "compile_unlocked": False,
        "aws_configured": False,
    }
    (identity / "kx-device-1-manifest.json").write_text(json.dumps(manifest))
    return candidate, identity, source, old, secret


def test_prepare_is_idempotent_without_modifying_existing_files(inputs):
    candidate, identity, source, old, secret = inputs
    created, fingerprint = stage.prepare(candidate, identity)
    assert created is True
    assert fingerprint == sha256(secret).hexdigest().upper()
    generated = (candidate / stage.PREPARED_NAME).read_text()
    assert 'LAB55H_HOST = "100-30-4-62.nip.io";' in generated
    assert "LAB55H_PORT = 443;" in generated
    assert "R\"KXROOT(" in generated
    assert "PUBLIC CA FOR TEST" in generated
    assert "SSID_DE_EJEMPLO" in generated
    assert "PASS_DE_EJEMPLO" in generated
    assert "0x00, 0x01, 0x02" in generated
    assert "KX_AWS_TLS_CONFIG_OK" not in generated
    assert (candidate / stage.SKETCH_NAME).read_bytes() == source
    assert (candidate / stage.HEADER_NAME).read_bytes() == old

    created_again, fingerprint_again = stage.prepare(candidate, identity)
    assert created_again is False
    assert fingerprint_again == fingerprint


def test_refuses_changed_identity_without_overwriting_existing_output(inputs):
    candidate, identity, _source, _old, secret = inputs
    stage.prepare(candidate, identity)
    output = candidate / stage.PREPARED_NAME
    before = output.read_bytes()
    (identity / "kx-device-1-key.bin").write_bytes(bytes(reversed(secret)))
    with pytest.raises(ValueError, match="manifest"):
        stage.prepare(candidate, identity)
    assert output.read_bytes() == before


def test_refuses_unknown_header_syntax_without_writing(inputs):
    candidate, identity, _source, old, _secret = inputs
    (candidate / stage.HEADER_NAME).write_bytes(
        old.replace(b'LAB55H_DEVICE_KEY[32] = { 0x17, 0x1A };',
                    b'LAB55H_DEVICE_KEY = getSecret();')
    )
    with pytest.raises(ValueError, match="LAB55H_DEVICE_KEY"):
        stage.prepare(candidate, identity)
    assert not (candidate / stage.PREPARED_NAME).exists()


def test_refuses_git_tree(inputs):
    candidate, identity, _source, _old, _secret = inputs
    (candidate.parent / ".git").mkdir()
    with pytest.raises(ValueError, match="Git"):
        stage.prepare(candidate, identity)
    assert not (candidate / stage.PREPARED_NAME).exists()


def test_refuses_existing_different_private_file(inputs):
    candidate, identity, _source, _old, _secret = inputs
    (candidate / stage.PREPARED_NAME).write_text("NOT OUR FILE")
    with pytest.raises(FileExistsError, match="NO sobrescribir"):
        stage.prepare(candidate, identity)
    assert (candidate / stage.PREPARED_NAME).read_text() == "NOT OUR FILE"
