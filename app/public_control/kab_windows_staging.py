"""K-AB — candidato de lanzador Windows para admisión 100% virtual.

NO instala tareas, Caddy ni firewall. NO usa app.main, ESP, RDS o WSS.
El estado privado se almacena fuera de ProgramData/VehiculoIoT (legacy).
El servicio solo escucha 127.0.0.1:9444 tras un GO explícito en un
manifiesto ACL-protegido y ejecutándose como su identidad configurada.

Uso (solo ventana supervisada, nunca ejecutar por el mero checkout):
  python -m app.public_control.kab_windows_staging --mode preflight
  python -m app.public_control.kab_windows_staging --mode serve
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

_ROOT_NAME = "VehiculoIoT-Admission-Staging"
_REPO = Path(__file__).resolve().parents[2]
_SECRET_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z", re.ASCII)
_ALLOWED_KEYS = frozenset({
    "schema_version", "mode", "service_sid", "bind_host", "bind_port",
    "database_name", "enabled",
})
_FORBIDDEN_SYSTEM_SIDS = {"S-1-5-18", "S-1-5-19", "S-1-5-20"}


class StagingRefused(ValueError):
    """Never include secrets in the message."""


def _real_private(path: Path, *, directory: bool = False) -> Path:
    from app.public_control.local_files import check_private

    # A Windows junction/reparse point must not redirect state to an
    # attacker-controlled directory, even if Path.resolve() follows it.
    if path.is_symlink() or (
        getattr(path.lstat(), "st_file_attributes", 0)
        & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise StagingRefused("Ruta de estado insegura")
    check_private(path, directory=directory)
    return path.resolve(strict=True)


def _state_root(configured: str | None) -> tuple[Path, bool]:
    if os.name != "nt":
        raise StagingRefused("K-AB requiere Windows")
    program_data = os.environ.get("ProgramData")
    if not program_data:
        raise StagingRefused("ProgramData no disponible")
    default = Path(program_data).resolve(strict=True) / _ROOT_NAME
    if configured is None:
        return default, False

    # The test override can NEVER be enabled in a regular EC2 deployment.
    # A plain environment flag alone is insufficient: private marker and
    # Windows CI prefix are rechecked below before opening sockets.
    if (os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("KAB_WINDOWS_CI_ONLY") != "isolated-loopback"
            or not os.environ.get("RUNNER_TEMP")):
        raise StagingRefused("Estado alternativo no permitido")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    override = Path(configured).resolve(strict=True)
    if (not override.is_relative_to(runner)
            or override == runner or override.name != "kab-private"):
        raise StagingRefused("Estado alternativo fuera del runner")
    return override, True


def load_staging(state: str | None, *, serve: bool):
    """Validate all permissions and file identities before reading proofs."""
    # Resolver primero el guard Windows; en Linux _current_windows_sid
    # intencionalmente no existe y la petición se rechaza con NO-GO limpio.
    root, ci = _state_root(state)
    from app.public_control.local_files import _current_windows_sid
    _real_private(root, directory=True)
    if root.is_relative_to(_REPO):
        raise StagingRefused("Estado no puede ubicarse en repositorio")
    if ci:
        marker = _real_private(root / "KAB_CI_ONLY.marker")
        if marker.read_text(encoding="utf-8-sig") != "KAB-CI-ISOLATED\n":
            raise StagingRefused("Marcador de CI incorrecto")
    manifest = _real_private(root / "staging.json")
    if manifest.stat().st_size > 2048:
        raise StagingRefused("Manifiesto demasiado grande")
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if type(data) is not dict or data.keys() != _ALLOWED_KEYS:
        raise StagingRefused("Esquema no autorizado")
    sid = _current_windows_sid()
    if (data["schema_version"] != 1 or type(data["schema_version"]) is not int
            or data["mode"] != "virtual_staging"
            or data["service_sid"] != sid
            or data["bind_host"] != "127.0.0.1"
            or type(data["bind_port"]) is not int or data["bind_port"] != 9444
            or data["database_name"] != "tickets.sqlite3"
            or type(data["enabled"]) is not bool):
        raise StagingRefused("Configuración no coincide con identidad o modo")
    if not ci and sid in _FORBIDDEN_SYSTEM_SIDS:
        raise StagingRefused("Se requiere identidad dedicada, no cuentas compartidas")
    if serve and data["enabled"] is not True:
        raise StagingRefused("Activación explícita todavía no autorizada")

    secret_dir = _real_private(root / "secrets", directory=True)
    admin_file = _real_private(secret_dir / "admin.proof")
    proxy_file = _real_private(secret_dir / "proxy.proof")
    if admin_file.stat().st_size > 256 or proxy_file.stat().st_size > 256:
        raise StagingRefused("Longitud de secreto fuera de contrato")
    admin = admin_file.read_text(encoding="ascii").rstrip("\r\n")
    proxy = proxy_file.read_text(encoding="ascii").rstrip("\r\n")
    if (not _SECRET_PATTERN.fullmatch(admin)
            or not _SECRET_PATTERN.fullmatch(proxy) or admin == proxy):
        raise StagingRefused("Pruebas privadas inválidas")
    database = root / "tickets.sqlite3"
    if database.exists():
        _real_private(database)
    return database, admin, proxy, ci


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="K-AB virtual staging Windows")
    parser.add_argument("--mode", choices=("preflight", "serve"), required=True)
    parser.add_argument("--state", help="Solo CI: ruta efímera dentro de RUNNER_TEMP")
    args = parser.parse_args(argv)
    try:
        db, admin, proxy, _ci = load_staging(
            args.state, serve=(args.mode == "serve")
        )
        if args.mode == "preflight":
            print("[K-AB] Preflight privado correcto; NINGÚN servicio instalado.")
            return 0

        # Call the already tested virtual-only app, never legacy or hardware.
        os.environ["APP_ENV"] = "staging"
        os.environ["ADMISSION_VIRTUAL_ONLY"] = "enabled"
        from app.public_control.kv_virtual_staging import create_kv_virtual_app
        app = create_kv_virtual_app(db, admin, proxy)
        import uvicorn
        print("[K-AB] VIRTUAL ONLY 127.0.0.1:9444; sin motor.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=9444, workers=1,
                    reload=False, proxy_headers=False,
                    access_log=False, server_header=False,
                    log_level="warning")
        # A service unexpectedly exiting is not a successful deployment.
        return 3
    except Exception:
        # Exceptions may contain filesystem paths or secret values. Never log.
        print("[K-AB] NO-GO: identidad, estado o sidecar indisponibles.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
