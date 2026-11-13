"""K-Y — sidecar Windows REAL, pero solo ejecutable en runner Windows CI.

No instalar en EC2, Task Scheduler ni convertir en servicio. Solo prueba
arranque independiente de K-V en loopback y apagado sin alterar 8000/legacy.
No importa app.main, WSS, GPIO, RDS ni despacha comandos fisicos.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from app.public_control.kv_virtual_staging import create_kv_virtual_app


def _configuration(path: Path) -> tuple[Path, str, str]:
    """Comprobar origen runner y contrato cerrado ANTES de abrir sockets."""
    if (os.name != "nt"
            or os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("KY_WINDOWS_CI_ONLY") != "isolated-sidecar"
            or os.getenv("APP_ENV") != "staging"
            or os.getenv("ADMISSION_VIRTUAL_ONLY") != "enabled"):
        raise ValueError("K-Y: fuera del laboratorio Windows CI")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    cfg = path.resolve(strict=True)
    if cfg == runner or not cfg.is_relative_to(runner) or path.is_symlink():
        raise ValueError("K-Y: archivo fuera del directorio temporal")
    if cfg.stat().st_size > 4096:
        raise ValueError("K-Y: configuración demasiado grande")
    raw = json.loads(cfg.read_text(encoding="utf-8-sig"))
    if type(raw) is not dict or set(raw) != {
            "schema_version", "mode", "bind_host", "bind_port",
            "database_path", "admin_proof", "proxy_proof"}:
        raise ValueError("K-Y: esquema desconocido")
    if (type(raw["schema_version"]) is not int or raw["schema_version"] != 1
            or raw["mode"] != "virtual_ci"
            or raw["bind_host"] != "127.0.0.1"
            or type(raw["bind_port"]) is not int or raw["bind_port"] != 9444):
        raise ValueError("K-Y: destino de red no permitido")
    db = Path(raw["database_path"]).resolve()
    if (db == cfg or not db.is_relative_to(runner)
            or not db.parent.is_dir() or db.is_symlink()):
        raise ValueError("K-Y: base fuera de zona privada")
    admin = raw["admin_proof"]
    proxy = raw["proxy_proof"]
    if (type(admin) is not str or type(proxy) is not str
            or len(admin) < 32 or len(proxy) < 32
            or len(admin) > 256 or len(proxy) > 256 or admin == proxy):
        raise ValueError("K-Y: prueba privada no válida")
    return db, admin, proxy


def main() -> int:
    parser = argparse.ArgumentParser(description="K-Y virtual Windows CI only")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        database, admin, proxy = _configuration(Path(args.config))
        app = create_kv_virtual_app(database, admin, proxy)
        # No se imprimen secretos, rutas de credenciales ni respuestas cliente.
        import uvicorn
        print("[K-Y] sidecar VIRTUAL 127.0.0.1:9444, sin motores.", flush=True)
        uvicorn.run(
            app,
            host="127.0.0.1", port=9444, workers=1,
            reload=False, proxy_headers=False,
            access_log=False, server_header=False, log_level="warning",
        )
        return 0
    except (ValueError, KeyError, OSError, json.JSONDecodeError):
        print("[K-Y] NO-GO: precondición de laboratorio incumplida.", file=sys.stderr)
        return 2
    except Exception:
        # No incluir excepciones: algunas bibliotecas interpolan secretos.
        print("[K-Y] NO-GO: sidecar falló cerrado.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
