"""Preparar cabecera PRIVADA K-X AWS sin modificar la cabecera utilizada por Arduino.

Conserva solo las credenciales WiFi LOCALES del candidato y sustituye
el host, puerto, CA y clave HMAC del laboratorio. El archivo de salida
NO es incluido por el sketch y NO desbloquea la compilación.
No imprimir, versionar o compartir esta cabecera.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import re
import ssl
import sys

FIRMWARE_SHA256 = "6b5012192806d2611e5a92d728099cadf92d005ac3e1ee6f01b6f268ba99f0d4"
ISRG_ROOT_X1_SHA256 = "96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6"
WSS_HOST = "100-30-4-62.nip.io"
WSS_PORT = 443
WSS_PATH = "/ws/kx-diagnostico/1"
PREPARED_NAME = "config_55h_kx_aws_preparado.h"
SKETCH_NAME = "Excavadora_IoT_55H_AWS_KX_Diagnostico.ino"
HEADER_NAME = "config_55h_local.h"


def _outside_git(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("No guardar archivos privados dentro de un repositorio Git")


def _replace_value(content: str, name: str, expr: str, substitute: str) -> str:
    # El prefijo debe estar en una sola línea, incluyendo el tipo C++.
    pattern = re.compile(
        r"(?m)^(?P<prefix>[^\r\n;]*\b" + re.escape(name)
        + r"\b[^\r\n;]*?=\s*)(?P<value>" + expr + r")(?P<suffix>\s*;)",
        re.DOTALL,
    )
    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        raise ValueError("Declaracion C++ ausente, repetida o incompatible: " + name)
    match = matches[0]
    return content[:match.start("value")] + substitute + content[match.end("value"):]


def _read_root_ca(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("Falta la CA publica ISRG Root X1")
    pem = path.read_text(encoding="ascii")
    certs = re.findall(
        r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", pem
    )
    if len(certs) != 1:
        raise ValueError("La CA publica debe contener exactamente un certificado")
    try:
        der = ssl.PEM_cert_to_DER_cert(certs[0])
    except (ValueError, ssl.SSLError):
        raise ValueError("PEM publico invalido") from None
    if sha256(der).hexdigest() != ISRG_ROOT_X1_SHA256:
        raise ValueError("Huella de ISRG Root X1 incorrecta")
    return certs[0] + "\n"


def prepare(
    candidate_dir: Path, identity_dir: Path,
) -> tuple[bool, str]:
    candidate_dir, identity_dir = candidate_dir.resolve(), identity_dir.resolve()
    _outside_git(candidate_dir)
    _outside_git(identity_dir)
    ino = candidate_dir / SKETCH_NAME
    original_header = candidate_dir / HEADER_NAME
    ca_path = candidate_dir / "ISRG_Root_X1_public.pem"
    secret_path = identity_dir / "kx-device-1-key.bin"
    manifest_path = identity_dir / "kx-device-1-manifest.json"
    output = candidate_dir / PREPARED_NAME

    if any(p.is_symlink() for p in (ino, original_header, ca_path, secret_path, manifest_path, output)):
        raise ValueError("No se permiten enlaces simbolicos en archivos privados")
    if not all(p.is_file() for p in (ino, original_header, ca_path, secret_path, manifest_path)):
        raise ValueError("Faltan archivos privados o certificados locales")
    firmware = ino.read_bytes()
    if sha256(firmware).hexdigest() != FIRMWARE_SHA256:
        raise ValueError("Firmware candidato diferente al comprobado anteriormente")
    sketch_code = firmware.decode("utf-8")
    if (not re.search(r"(?m)^\s*#define\s+ETAPA54_DIAGNOSTICO_SEGURO\s+1\s*$",
                      sketch_code)
            or "ETAPA54_DIAGNOSTICO_SEGURO != 1" not in sketch_code
            or '#include "config_55h_local.h"' not in sketch_code
            or "KX_AWS_TLS_CONFIG_OK" not in sketch_code
            or WSS_PATH not in sketch_code
            or "setInsecure(" in sketch_code):
        raise ValueError("Protecciones del candidato no verificadas")

    secret = secret_path.read_bytes()
    if len(secret) != 32:
        raise ValueError("La clave HMAC local no mide 32 bytes")
    fingerprint = sha256(secret).hexdigest().upper()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (type(manifest) is not dict
            or manifest.get("key_fingerprint_sha256") != fingerprint
            or manifest.get("host") != WSS_HOST
            or manifest.get("port") != WSS_PORT
            or manifest.get("path") != WSS_PATH
            or manifest.get("compile_unlocked") is not False
            or manifest.get("aws_configured") is not False):
        raise ValueError("Identidad local o manifest inconsistente")

    root_pem = _read_root_ca(ca_path)
    old_header = original_header.read_bytes()
    try:
        original = old_header.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("Cabecera local no es UTF-8 valida") from None

    if "KX_AWS_TLS_CONFIG_OK" in original:
        raise ValueError("La cabecera actual no debe desbloquear la compilacion")
    if "#define LAB55H_CONFIG_VALID" not in original:
        raise ValueError("No existe validacion de cabecera del 55-H")
    # Conservar exactamente los literales WiFi originales, sin imprimirlos.
    literal = r'"(?:\\.|[^"\\\r\n])*"'
    for name in ("LAB55H_WIFI_SSID", "LAB55H_WIFI_PASSWORD"):
        wi = re.compile(
            r"(?m)^[^\r\n;]*\b" + re.escape(name) + r"\s*=\s*" + literal + r"\s*;"
        )
        if len(wi.findall(original)) != 1:
            raise ValueError("Formato WiFi privado no reconocido: " + name)

    raw_pem = r'R"(?P<d>[A-Za-z0-9_]*)\([\s\S]*?\)(?P=d)"'
    configured = _replace_value(original, "LAB55H_HOST", literal, '"' + WSS_HOST + '"')
    configured = _replace_value(configured, "LAB55H_PORT", r"\d+", str(WSS_PORT))
    key_initializer = "{\n  " + ", ".join("0x%02X" % byte for byte in secret) + "\n}"
    configured = _replace_value(
        configured, "LAB55H_DEVICE_KEY", r"\{[^}]*\}", key_initializer,
    )
    ca_initializer = 'R"KXROOT(\n' + root_pem + ')KXROOT"'
    configured = _replace_value(
        configured, "LAB55H_CA_CERT", raw_pem, ca_initializer,
    )
    if "KX_AWS_TLS_CONFIG_OK" in configured:
        raise ValueError("La cabecera preparada no puede habilitar la compilacion")
    if configured == original:
        raise ValueError("Cabecera preparada inesperadamente identica a la original")

    # No cambiar estilos de linea ni cabeceras usadas por Arduino IDE.
    result = configured.encode("utf-8")
    if output.exists():
        if not output.is_file() or output.read_bytes() != result:
            raise FileExistsError("Cabecera preparada distinta ya existe: NO sobrescribir")
        return False, fingerprint
    with output.open("xb") as stream:
        stream.write(result)
        stream.flush()
        os.fsync(stream.fileno())
    return True, fingerprint


def main() -> int:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        print("ABORTADO: no se encontro LOCALAPPDATA de Windows")
        return 1
    candidate = (Path.home() / "Downloads"
                 / "Etapa_5_5_H_WSS_Directo_Local"
                 / "Etapa_5_5_H_WSS_Directo_Local"
                 / "firmware" / "Excavadora_IoT_55H_AWS_KX_Diagnostico")
    identity = Path(local) / "VehiculoIoT" / "KXDevice"
    try:
        created, fingerprint = prepare(candidate, identity)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print("ABORTADO:", type(exc).__name__, str(exc))
        return 1
    print("=== CABECERA PRIVADA K-X AWS ===")
    print("ESTADO:", "CREADA" if created else "YA EXISTIA SIN CAMBIOS")
    print("DESTINO:", PREPARED_NAME)
    print("HOST/PUERTO:", WSS_HOST, WSS_PORT)
    print("CA: ISRG Root X1 comprobada por SHA256")
    print("CLAVE HMAC: COINCIDE con manifest; HUELLA:", fingerprint)
    print("VALORES WIFI: CONSERVADOS, SIN MOSTRAR")
    print("HEADER UTILIZADO POR EL SKETCH: INTACTO")
    print("MOTORES: BLOQUEADOS; COMPILACION: BLOQUEADA")
    print("EC2/RDS/ESP: SIN CAMBIOS")
    print("NO SUBIR LA CABECERA PRIVADA A GITHUB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
