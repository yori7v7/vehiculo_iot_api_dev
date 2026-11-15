"""Contratos de seguridad del saneamiento BearSSL 56 (sin redes ni motores)."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from scripts import preparar_55h_hotspot_seguro as generator
from scripts.reparar_tls_bearssl_55h import repair, HEADER_CA


def setup_sketch(tmp_path, monkeypatch, ip="172.22.82.209"):
    sketch = tmp_path / "sketch"
    sketch.mkdir()
    (sketch / "Excavadora_IoT_55H_Hotspot_Seguro.ino").write_text(
        "// Test fixture only; no GPIO, no secrets", encoding="ascii"
    )
    monkeypatch.setattr(generator, "SKETCH", sketch)
    monkeypatch.setattr(generator, "PRIVATE", sketch / "private")
    generator.prepare(ip, "CI-LAB-HOTSPOT-123", ci_fixture=True)
    return sketch


def test_new_generator_has_both_sans(tmp_path, monkeypatch):
    sketch = setup_sketch(tmp_path, monkeypatch)
    crt = x509.load_pem_x509_certificate((sketch / "private/server.pem").read_bytes())
    san = crt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("172.22.82.209") in san.get_values_for_type(x509.IPAddress)
    assert "172.22.82.209" in san.get_values_for_type(x509.DNSName)


def test_repair_migrates_old_identity_preserves_secrets(tmp_path, monkeypatch):
    sketch = setup_sketch(tmp_path, monkeypatch)
    private = sketch / "private"
    header_path = sketch / "config_55h_local.h"

    # Simula identidad ORIGINAL (certificado SAN solo iPAddress), sin recompilar.
    # Crear nueva CA/servidor solo IP empleando builder de cryptography.
    now_certificate = x509.load_pem_x509_certificate((private / "server.pem").read_bytes())
    san = now_certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "172.22.82.209" in san.get_values_for_type(x509.DNSName)
    from datetime import datetime, timezone, timedelta
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    ca_priv = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Old LAB CA")])
    now = datetime.now(timezone.utc)
    old_ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
              .public_key(ca_priv.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=7))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .sign(ca_priv, hashes.SHA256()))
    old_srv = (x509.CertificateBuilder().subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, "Old LAB server")]))
               .issuer_name(ca_name).public_key(ec.generate_private_key(ec.SECP256R1()).public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=7))
               .add_extension(x509.SubjectAlternativeName([
                   x509.IPAddress(ipaddress.ip_address("172.22.82.209")),
               ]), critical=False)
               .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
               .sign(ca_priv, hashes.SHA256()))
    prev_ca_pem = old_ca.public_bytes(serialization.Encoding.PEM)
    (private / "ca.pem").write_bytes(prev_ca_pem)
    (private / "server.pem").write_bytes(old_srv.public_bytes(serialization.Encoding.PEM))
    orig_header = header_path.read_text(encoding="ascii")
    match = HEADER_CA.search(orig_header)
    assert match
    header_path.write_text(
        orig_header[:match.start("ca")] +
        prev_ca_pem.decode("ascii") +
        orig_header[match.end("ca"):], encoding="ascii"
    )
    hmac_before = (private / "device-key.bin").read_bytes()
    settings_before = (private / "settings.json").read_bytes()
    header_before = header_path.read_text(encoding="ascii")
    backup, updated = repair(sketch, private)
    assert updated == header_path
    assert backup.exists()
    assert (backup / "config_55h_local.h").read_text(encoding="ascii") == header_before
    assert (private / "device-key.bin").read_bytes() == hmac_before
    assert (private / "settings.json").read_bytes() == settings_before
    after = header_path.read_text(encoding="ascii")
    assert "CI-SOLO-DIAGNOSTICO-123" in after  # CI fixture AP only
    assert after.split("LAB55H_DEVICE_KEY[32] = ")[1].split(";")[0] == (
        header_before.split("LAB55H_DEVICE_KEY[32] = ")[1].split(";")[0])
    crt = x509.load_pem_x509_certificate((private / "server.pem").read_bytes())
    san = crt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "172.22.82.209" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("172.22.82.209") in san.get_values_for_type(x509.IPAddress)
    assert (private / "ca.pem").read_bytes() != prev_ca_pem
    with pytest.raises(ValueError, match="Ya existe SAN BearSSL"):
        repair(sketch, private)


def test_refuse_identity_with_mismatched_key(tmp_path, monkeypatch):
    sketch = setup_sketch(tmp_path, monkeypatch)
    private = sketch / "private"
    (private / "device-key.bin").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="HMAC"):
        repair(sketch, private)
    assert not (private / "backup-before-bearssl-ip").exists()
