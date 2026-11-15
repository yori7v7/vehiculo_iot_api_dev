"""Carga de identidad PRIVADA para el WSS K-X de diagnostico.

Solo bytes HMAC, nunca textos de configuracion, cabeceras HTTP ni registros.
Validacion fail-closed en el arranque. Este archivo NO entrega permiso fisico.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from app.config.settings import PROJECT_ROOT


class KXDeviceIdentityError(ValueError):
    """La identidad de dispositivo K-X no se puede considerar confiable."""


def load_private_key(path: Path) -> tuple[bytes, str]:
    """Devuelve clave binaria y huella de auditoria; nunca expone la clave en logs."""
    if not isinstance(path, Path):
        raise KXDeviceIdentityError("Ruta privada de K-X invalida")
    if not path.is_absolute() or path.is_symlink():
        raise KXDeviceIdentityError("Se exige archivo regular absoluto, sin enlaces")
    try:
        real = path.resolve(strict=True)
        if real.is_relative_to(PROJECT_ROOT.resolve()):
            raise KXDeviceIdentityError("Archivo privado dentro del repositorio")
        if not real.is_file() or real.is_symlink():
            raise KXDeviceIdentityError("No es un archivo privado regular")
        # Este limite evita leer archivos inesperados o material accidental.
        if real.stat().st_size != 32:
            raise KXDeviceIdentityError("La clave K-X debe medir exactamente 32 bytes")
        secret = real.read_bytes()
    except (OSError, RuntimeError) as exc:
        raise KXDeviceIdentityError("No se pudo verificar la clave privada K-X") from None
    if len(secret) != 32:
        raise KXDeviceIdentityError("La clave K-X esta truncada")
    return secret, sha256(secret).hexdigest().upper()
