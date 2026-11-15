"""Genera HMAC y TLS del laboratorio 55-H (sin motores) para un hotspot 2.4 GHz.

La contraseña del hotspot CELULAR no está en el firmware: se provisiona
por WiFiManager al encender el ESP8266. Solo se solicita clave del AP del ESP.
No reutilizar estas claves para control físico ni AWS.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "Excavadora_IoT_55H_Hotspot_Seguro"
PRIVATE = SKETCH / "private"


def prepare(host: str, ap_password: str, *, ci_fixture: bool = False) -> Path:
    ip = ipaddress.ip_address(host)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError("Usa la IP privada de la laptop en el hotspot")
    if (not ap_password.isascii() or not 8 <= len(ap_password) <= 63
            or '"' in ap_password or "\\" in ap_password):
        raise ValueError("La clave del AP de configuracion requiere 8-63 ASCII")
    if not (SKETCH / "Excavadora_IoT_55H_Hotspot_Seguro.ino").is_file():
        raise FileNotFoundError("Falta el sketch del candidato virtual")

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IoT 55-H Hotspot LAB CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .sign(ca_key, hashes.SHA256()))
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IoT 55-H LAN LAB")])
    server = (x509.CertificateBuilder().subject_name(server_name).issuer_name(ca_name)
        .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        # Doble SAN exclusivamente en LAB 55-H: iPAddress para clientes RFC
        # y dNSName como cadena IP para compatibilidad BearSSL ESP8266 3.1.2.
        # RFC 9525 no permite usar una IP como dNSName; NO usar en produccion.
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip), x509.DNSName(str(ip))]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    device_key = secrets.token_bytes(32)
    files = {
        "ca.pem": ca_pem,
        "server.pem": server.public_bytes(serialization.Encoding.PEM),
        "server-key.pem": server_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()),
        "device-key.bin": device_key,
        "settings.json": json.dumps({
            "ip": str(ip), "port": 8443, "vehicle_id": 1,
            "mode": "lab55h", "physical_enabled": False,
        }, indent=2).encode("utf-8"),
    }
    PRIVATE.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        dest = PRIVATE / name
        dest.write_bytes(value)
        if os.name != "nt":
            dest.chmod(0o600)

    conf = SKETCH / "config_55h_local.h"
    content = (
        "// SOLO EN PC PRIVADA; NO PUBLICAR. CANDIDATO SIN MOTORES.\n"
        "#define LAB55H_CONFIG_VALID 1\n"
        f"static const char LAB55H_AP_PASSWORD[] = {json.dumps(ap_password)};\n"
        f"static const char LAB55H_HOST[] = {json.dumps(str(ip))};\n"
        "static const uint16_t LAB55H_PORT = 8443;\n"
        'static const char LAB55H_WS_PATH[] = "/ws/dispositivos-lab/1/contrato";\n'
        "static const uint8_t LAB55H_DEVICE_KEY[32] = { "
        + ", ".join(map(str, device_key)) + " };\n"
        'static const char LAB55H_CA_CERT[] = R"LOCALCA(\n'
        + ca_pem.decode("ascii") + ')LOCALCA";\n'
    )
    conf.write_text(content, encoding="ascii")
    if os.name != "nt":
        conf.chmod(0o600)
    if ci_fixture:
        print("[CI] Valores ficticios, exclusivamente compilacion de seguridad.")
    else:
        print("[LAB 55-H] Certificados y HMAC creados SOLO en esta laptop.")
        print("[LAB 55-H] Credenciales hotspot: se configuran despues por WiFiManager.")
    print("[LAB 55-H] Sketch:", SKETCH)
    return conf


def main():
    parser = argparse.ArgumentParser(description="55-H Hotspot: prototipo sin motores")
    parser.add_argument("--host", help="IPv4 LAN de laptop conectada al hotspot")
    parser.add_argument("--ci-fixture", action="store_true", help="Valores de CI, JAMAS para hardware")
    args = parser.parse_args()
    host = args.host or input("IP privada de laptop en el hotspot: ").strip()
    ap_key = ("CI-SOLO-DIAGNOSTICO-123" if args.ci_fixture else
              getpass.getpass("Clave NUEVA del AP del ESP (no clave hotspot): "))
    prepare(host, ap_key, ci_fixture=args.ci_fixture)


if __name__ == "__main__":
    main()
