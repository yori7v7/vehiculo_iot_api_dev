"""Generar identidad HMAC K-X LOCAL, sin AWS, ESP, Git ni exponer secretos.

Una clave de 32 bytes se crea una sola vez con CSPRNG en LocalAppData del
usuario. El mismo archivo binario sera entregado de forma privada al backend
y usado para crear el header AWS del ESP en un paso posterior.

NO desbloquea la compilacion ni altera el firmware. No es apto para upload.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import re
import secrets
import ssl
import sys

ROOT_CA_SHA256 = "96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6"
CANDIDATE_SHA256 = "6b5012192806d2611e5a92d728099cadf92d005ac3e1ee6f01b6f268ba99f0d4"
KEY_NAME = "kx-device-1-key.bin"
MANIFEST_NAME = "kx-device-1-manifest.json"
HOST = "100-30-4-62.nip.io"
PORT = 443
WSS_PATH = "/ws/kx-diagnostico/1"


def _refuse_git_tree(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("Destino dentro de Git: prohibido almacenar claves ahi")


def _verify_file(path: Path, expected_sha256: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("Archivo de entrada ausente o vinculo no permitido")
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise ValueError("La huella SHA256 de un archivo de entrada no coincide")
    return data


def provision(key_dir: Path, ca_file: Path, sketch: Path, header: Path) -> tuple[bool, str]:
    key_dir = key_dir.resolve()
    _refuse_git_tree(key_dir)
    ca_file, sketch, header = (p.resolve() for p in (ca_file, sketch, header))
    raw = _verify_file(sketch, CANDIDATE_SHA256)
    if not header.is_file() or header.is_symlink():
        raise ValueError("Falta la cabecera privada original del candidato")
    code = raw.decode("utf-8")
    if (not re.search(r"(?m)^\s*#define\s+ETAPA54_DIAGNOSTICO_SEGURO\s+1\s*$", code)
            or "ETAPA54_DIAGNOSTICO_SEGURO != 1" not in code
            or "KX_AWS_TLS_CONFIG_OK" not in code
            or WSS_PATH not in code
            or "setInsecure(" in code):
        raise ValueError("El sketch no conserva los interlocks de seguridad K-X")
    if b"KX_AWS_TLS_CONFIG_OK" in header.read_bytes():
        raise ValueError("La cabecera ya habilita compilacion: revisar manualmente")

    pem = ca_file.read_text(encoding="ascii")
    try:
        ca_der = ssl.PEM_cert_to_DER_cert(pem)
    except (ValueError, ssl.SSLError):
        raise ValueError("No es un PEM publico valido") from None
    if sha256(ca_der).hexdigest() != ROOT_CA_SHA256:
        raise ValueError("CA raiz distinta de ISRG Root X1 validada")

    # Todas las precondiciones se verifican ANTES de crear cualquier secreto.
    key_dir.mkdir(parents=True, exist_ok=True)
    _refuse_git_tree(key_dir)
    path = key_dir / KEY_NAME
    if path.is_symlink():
        raise ValueError("No se acepta enlace simbolico como clave privada")
    created = False
    if not path.exists():
        try:
            with path.open("xb") as file:
                file.write(secrets.token_bytes(32))
                file.flush()
                os.fsync(file.fileno())
            created = True
        except FileExistsError:
            pass
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("La clave existente es invalida; NO reemplazar")
    fingerprint = sha256(key).hexdigest().upper()

    manifest = key_dir / MANIFEST_NAME
    if manifest.is_symlink():
        raise ValueError("Manifest no puede ser un enlace simbolico")
    if not manifest.exists():
        metadata = {
            "version": 1,
            "device_id": 1,
            "host": HOST,
            "port": PORT,
            "path": WSS_PATH,
            "key_fingerprint_sha256": fingerprint,
            "ca_root": "ISRG Root X1",
            "firmware_diagnostic": True,
            "esp_configured": False,
            "aws_configured": False,
            "compile_unlocked": False,
        }
        with manifest.open("x", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2, sort_keys=True)
            file.write("\n")
    else:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (type(metadata) is not dict or metadata.get("version") != 1
                or metadata.get("key_fingerprint_sha256") != fingerprint
                or metadata.get("host") != HOST or metadata.get("port") != PORT
                or metadata.get("path") != WSS_PATH):
            raise ValueError("Manifest existente no corresponde a la clave; NO cambiar")
    return created, fingerprint


def main() -> int:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        print("ABORTADO: LOCALAPPDATA no existe (ejecutar desde laptop Windows)")
        return 1
    base = (Path.home() / "Downloads" / "Etapa_5_5_H_WSS_Directo_Local"
            / "Etapa_5_5_H_WSS_Directo_Local" / "firmware"
            / "Excavadora_IoT_55H_AWS_KX_Diagnostico")
    try:
        created, fingerprint = provision(
            Path(local_app_data) / "VehiculoIoT" / "KXDevice",
            base / "ISRG_Root_X1_public.pem",
            base / "Excavadora_IoT_55H_AWS_KX_Diagnostico.ino",
            base / "config_55h_local.h",
        )
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print("ABORTADO:", type(exc).__name__, str(exc))
        return 1
    print("=== IDENTIDAD PRIVADA K-X AWS ===")
    print("CLAVE HMAC DE 32 BYTES:", "CREADA" if created else "REUTILIZADA, SIN ROTACION")
    print("HUELLA SHA256:", fingerprint)
    print("UBICACION:", "%LOCALAPPDATA%\\VehiculoIoT\\KXDevice")
    print("VALIDEZ DE CA PUBLICA ISRG Root X1: OK")
    print("FIRMWARE: DIAGNOSTICO=1; COMPILACION BLOQUEADA")
    print("ARCHIVO PRIVADO: NO IMPRIMIR, NO SUBIR A GITHUB, NO ENVIAR AL CHAT")
    print("EC2, RDS, ESP Y CADDY: SIN CAMBIOS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
