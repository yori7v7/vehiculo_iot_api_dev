"""Corrige la identidad TLS del LAB 55-H tras error BearSSL 56.

NO toca WiFiManager, contraseña del AP, HMAC de dispositivo ni settings.json.
Emite NUEVA CA de laboratorio y certificado servidor con SAN iPAddress + dNSName
de la IP (la entrada DNS numérica es excepción de compatibilidad BearSSL,
NO conforme con RFC 9525 y NO apta para producción).

El ESP debe volver a compilarse/subirse para incorporar la nueva CA.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shutil
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts.preparar_55h_hotspot_seguro import SKETCH, PRIVATE

HEADER_CA = re.compile(
    r'(?P<prefix>static const char LAB55H_CA_CERT\[\]\s*=\s*R"LOCALCA\(\n)'
    r'(?P<ca>.*?)'
    r'(?P<suffix>\)LOCALCA";)', re.DOTALL
)
KEY_ARRAY = re.compile(
    r'static const uint8_t LAB55H_DEVICE_KEY\[32\]\s*=\s*\{([^}]+)\};'
)
HEADER_HOST = re.compile(r'static const char LAB55H_HOST\[\]\s*=\s*"([^"]+)";')
FILES_TO_BACKUP = ("ca.pem", "server.pem", "server-key.pem",
                   "device-key.bin", "settings.json")


def repair(sketch_dir: Path = SKETCH, private_dir: Path = PRIVATE) -> tuple[Path, Path]:
    sketch_dir, private_dir = Path(sketch_dir).resolve(), Path(private_dir).resolve()
    header_path = sketch_dir / "config_55h_local.h"
    header = header_path.read_text(encoding="ascii")
    if (not (sketch_dir / "Excavadora_IoT_55H_Hotspot_Seguro.ino").is_file()
            or "#define LAB55H_CONFIG_VALID 1" not in header):
        raise ValueError("NO-GO: sketch/configuracion LAB 55-H invalida")

    import json
    settings = json.loads((private_dir / "settings.json").read_text(encoding="utf-8"))
    ip = ipaddress.ip_address(settings["ip"])
    if (ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local
            or settings.get("physical_enabled") is not False
            or settings.get("mode") != "lab55h"
            or settings.get("port") != 8443
            or settings.get("vehicle_id") != 1):
        raise ValueError("NO-GO: el LAB debe permanecer virtual y en su IP original")

    if len(KEY_ARRAY.findall(header)) != 1 or len(HEADER_CA.findall(header)) != 1:
        raise ValueError("NO-GO: config_55h_local.h no tiene el formato esperado")
    current_key = bytes(int(x.strip()) for x in KEY_ARRAY.search(header).group(1).split(","))
    if len(current_key) != 32 or current_key != (private_dir / "device-key.bin").read_bytes():
        raise ValueError("NO-GO: HMAC local no coincide con firmware previo")
    host = HEADER_HOST.search(header)
    if host is None or host.group(1) != str(ip):
        raise ValueError("NO-GO: IP de certificado y firmware diferente")
    ca_match = HEADER_CA.search(header)
    previous_ca = (private_dir / "ca.pem").read_text(encoding="ascii")
    if ca_match.group("ca") != previous_ca:
        raise ValueError("NO-GO: la CA en firmware difiere del archivo privado")
    old_ca = x509.load_pem_x509_certificate(previous_ca.encode("ascii"))
    old_server = x509.load_pem_x509_certificate((private_dir / "server.pem").read_bytes())
    if old_server.issuer != old_ca.subject:
        raise ValueError("NO-GO: identidad TLS preexistente inconsistente")
    server_san = old_server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ip not in server_san.get_values_for_type(x509.IPAddress):
        raise ValueError("NO-GO: falta la IP original en el certificado")
    if str(ip) in server_san.get_values_for_type(x509.DNSName):
        raise ValueError("Ya existe SAN BearSSL; no rotar credenciales nuevamente")

    # Respaldo privado local ANTES de modificar cualquier identidad.
    backup = private_dir / "backup-before-bearssl-ip"
    if backup.exists():
        raise FileExistsError("NO-GO: ya existe respaldo previo; no sobrescribir")
    backup.mkdir(mode=0o700)
    for name in FILES_TO_BACKUP:
        shutil.copy2(private_dir / name, backup / name)
    shutil.copy2(header_path, backup / header_path.name)

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
    srv_key = ec.generate_private_key(ec.SECP256R1())
    srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IoT 55-H LAN LAB")])
    srv = (x509.CertificateBuilder().subject_name(srv_name).issuer_name(ca_name)
           .public_key(srv_key.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=7))
           .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
           .add_extension(x509.SubjectAlternativeName([
               x509.IPAddress(ip), x509.DNSName(str(ip)),
           ]), critical=False)
           .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
           .sign(ca_key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    new_header = (header[:ca_match.start("ca")] + ca_pem.decode("ascii")
                  + header[ca_match.end("ca"):])
    replacements = {
        private_dir / "ca.pem": ca_pem,
        private_dir / "server.pem": srv.public_bytes(serialization.Encoding.PEM),
        private_dir / "server-key.pem": srv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()),
        header_path: new_header.encode("ascii"),
    }
    written = []
    try:
        for path, value in replacements.items():
            temp = path.with_name(path.name + ".55h-new")
            try:
                temp.write_bytes(value)
                if os.name != "nt":
                    temp.chmod(0o600)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            written.append(path)
    except Exception:
        # Restituir archivos desde el respaldo si falla alguna sustitución.
        for path in written:
            original = backup / path.name
            shutil.copy2(original, path)
        raise

    assert (private_dir / "device-key.bin").read_bytes() == current_key
    assert (private_dir / "settings.json").read_bytes() == (backup / "settings.json").read_bytes()
    return backup, header_path


def main():
    backup, _ = repair()
    print("[55-H] TLS CORREGIDO PARA BEARSSL, SIEMPRE SOLO DIAGNOSTICO")
    print("[55-H] Clave HMAC, contraseña AP y hotspot guardado: INTACTOS")
    print("[55-H] Respaldo local privado:", backup)
    print("[55-H] ACCION OBLIGATORIA: recompilar y subir firmware por COM4.")
    print("[55-H] ACCION OBLIGATORIA: reiniciar servidor WSS; NO usar CA anterior.")
    print("[55-H] Compatibilidad dNSName numerico SOLAMENTE en LAB, NO produccion.")


if __name__ == "__main__":
    main()
