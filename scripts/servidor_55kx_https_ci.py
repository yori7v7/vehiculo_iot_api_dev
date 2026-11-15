"""K-X HTTPS: servidor temporal de integración de página COMPLETA en GitHub Actions.

NO ejecutar manualmente ni instalar en EC2. Sólo runner CI efímero,
sin RDS, dispositivos ni actuadores, con certificado HTTPS temporal.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> int:
    root = Path(os.environ.get("RUNNER_TEMP", "/inexistente")).resolve()
    cert = Path(os.environ.get("KX_SERVER_CRT", "/inexistente")).resolve()
    key = Path(os.environ.get("KX_SERVER_KEY", "/inexistente")).resolve()
    db = Path(os.environ.get("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", "/inexistente")).resolve()
    admin = os.environ.get("API_KEY", "")
    if (sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("KX_CI_LAB") != "two-loopbacks-https"
            or os.environ.get("APP_ENV") != "production"
            or os.environ.get("PUBLIC_VIRTUAL_ADMISSION_ENABLED") != "true"
            or os.environ.get("CONTROL_PUBLICO_ENABLED", "").lower() != "false"
            or os.environ.get("CONTROL_PUBLICO_SIMULATION", "").lower() != "false"
            or os.environ.get("DEVICE_LAB_ENABLED", "").lower() != "false"
            or len(admin) < 32
            or not all(p.is_relative_to(root) for p in (cert, key, db))
            or not cert.is_file() or not key.is_file() or not db.parent.is_dir()
            or db.exists()):
        print("[K-X] NO-GO: solo runner CI HTTPS efimero, estado nuevo y aislado.")
        return 2
    from app.main import app
    if app.state.kx_enabled is not True or app.state.exclusive_device_control_enabled is not True:
        print("[K-X] NO-GO: el bloqueo virtual no esta activo.")
        return 2
    import uvicorn
    print("[K-X] FastAPI + SQLite VIRTUAL en 127.0.0.2:443; sin actuadores.", flush=True)
    uvicorn.run(
        app, host="127.0.0.2", port=443, workers=1,
        ssl_certfile=str(cert), ssl_keyfile=str(key),
        proxy_headers=False, access_log=False, server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
