"""Preparar COPIA bloqueada del firmware 55-H para K-X.

Nunca cambia el sketch original, ni toca AWS/ESP, ni publica secretos.
La copia no compila hasta que se verifiquen TLS, host y clave en una etapa
posterior. Diseñado para ejecución local, fuera de cualquier repositorio.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import shutil
import sys

SOURCE_SHA256 = "6ab9a1a05f5b8e103458b7f01972b9e63f4bee369087cddc27e978003e56ade7"
OLD_ROUTE = '"/ws/dispositivos-lab/1/contrato"'
NEW_ROUTE = '"/ws/kx-diagnostico/1"'
NEW_SKETCH = "Excavadora_IoT_55H_AWS_KX_Diagnostico"
ORIGINAL_SKETCH = "Excavadora_IoT_55H_WSS_Directo"
HEADER_NAME = "config_55h_local.h"

COMPILE_INTERLOCK = (
    '#ifndef KX_AWS_TLS_CONFIG_OK\n'
    '#error "KX AWS: host, CA TLS y clave del dispositivo NO validados. NO COMPILAR."\n'
    '#endif\n'
)


def _outside_git(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("La copia privada nunca debe quedar dentro de un repositorio Git.")


def prepare(source: Path, destination: Path) -> tuple[str, str]:
    source = source.resolve()
    destination = destination.resolve()
    _outside_git(destination)
    if destination.exists():
        raise FileExistsError("Destino existente: no se modifica ni sobrescribe.")
    if source.name != ORIGINAL_SKETCH + ".ino":
        raise ValueError("Archivo .ino original inesperado.")
    if destination.name != NEW_SKETCH:
        raise ValueError("Carpeta de destino inesperada para Arduino IDE.")
    source_header = source.parent / HEADER_NAME
    if not source.is_file() or not source_header.is_file():
        raise FileNotFoundError("Falta el sketch original o su cabecera privada.")
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("El SHA256 no coincide con el firmware 55-H validado; ABORTAR.")
    content = raw.decode("utf-8")
    conditions = {
        "Bloqueo seguro": re.search(
            r"(?m)^\s*#define\s+ETAPA54_DIAGNOSTICO_SEGURO\s+1\s*$", content),
        "Error si se desactiva diagnostico": "ETAPA54_DIAGNOSTICO_SEGURO != 1" in content,
        "TLS con CA": "beginSslWithCA" in content and "LAB55H_CA_CERT" in content,
        "Sin setInsecure": "setInsecure(" not in content,
        "Cabecera privada": '#include "config_55h_local.h"' in content,
        "Ruta WSS original unica": content.count(OLD_ROUTE) == 1,
        "Sin interlock previo": "KX_AWS_TLS_CONFIG_OK" not in content,
    }
    if not all(conditions.values()):
        raise ValueError(
            "Contrato de origen inesperado: "
            + ", ".join(k for k, v in conditions.items() if not v)
        )
    header = source_header.read_bytes()
    if b"KX_AWS_TLS_CONFIG_OK" in header:
        raise ValueError("La cabecera privada ya define la habilitacion K-X. ABORTAR.")
    transformed = content.replace(OLD_ROUTE, NEW_ROUTE, 1)
    # Arduino IDE puede guardar el sketch en CRLF; conservar sus saltos.
    newline = "\r\n" if "\r\n" in content else "\n"
    directive = '#include "config_55h_local.h"' + newline
    transformed = transformed.replace(
        directive, directive + COMPILE_INTERLOCK.replace("\n", newline), 1,
    )
    if COMPILE_INTERLOCK.replace("\n", newline) not in transformed:
        raise ValueError("No se pudo insertar el bloqueo de compilacion.")
    if transformed.count(NEW_ROUTE) != 1 or OLD_ROUTE in transformed:
        raise ValueError("La ruta WSS candidata no es unica.")
    # El host/CA/clave del antiguo laboratorio NO se reutilizan
    # automaticamente para AWS. La cabecera se copia PRIVADA y se revisara.
    destination.mkdir(parents=True, exist_ok=False)
    try:
        sketch = destination / (NEW_SKETCH + ".ino")
        sketch.write_bytes(transformed.encode("utf-8"))
        (destination / HEADER_NAME).write_bytes(header)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return digest.upper(), sha256(sketch.read_bytes()).hexdigest().upper()


def main() -> int:
    root = (Path.home() / "Downloads" / "Etapa_5_5_H_WSS_Directo_Local"
            / "Etapa_5_5_H_WSS_Directo_Local" / "firmware")
    source = root / ORIGINAL_SKETCH / (ORIGINAL_SKETCH + ".ino")
    destination = root / NEW_SKETCH
    print("=== CANDIDATO 55-H PARA K-X / SIN MOTORES ===")
    try:
        original, candidate = prepare(source, destination)
    except (OSError, UnicodeError, ValueError) as exc:
        print("ABORTADO:", str(exc))
        return 1
    print("ORIGINAL SHA256:", original)
    print("CANDIDATO SHA256:", candidate)
    print("COPIA CREADA:", destination)
    print("DIAGNOSTICO SEGURO: 1")
    print("DESTINO WSS CANDIDATO: /ws/kx-diagnostico/1")
    print("HOST/CA/CLAVE AWS: SIN CONFIGURAR")
    print("COMPILACION: BLOQUEADA HASTA VALIDAR TLS Y CLAVE")
    print("SECRETO PRIVADO: COPIADO LOCALMENTE, NUNCA SUBIR A GITHUB")
    print("ORIGINAL: INTACTO; EC2 Y ESP: SIN CAMBIOS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
