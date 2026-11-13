"""5.5-K-U: servidor HTTPS efimero SOLO para CI, sin actuadores.

No iniciar manualmente, no desplegar en EC2 ni ejecutar como servicio.
Se niega a arrancar fuera de GitHub Actions y escucha SOLO en 127.0.0.1.
No importa K-G, WSS, main.py, RDS ni controlador fisico.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import uvicorn

from app.public_control.ks_contract_test_app import create_ks_contract_test_app


def main() -> int:
    if (os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("KU_CI_LAB") != "isolated-loopback-only"
            or os.getenv("APP_ENV", "") != "development"):
        print("[K-U] CI aislado obligatorio; inicio denegado.")
        return 1

    db, crt, key = (Path(os.environ[name]).resolve()
                    for name in ("KU_PRIVATE_DB", "KU_SERVER_CRT", "KU_SERVER_KEY"))
    admin = os.getenv("KU_ADMIN_TEST_KEY", "")
    if not (len(admin) >= 32 and db.parent.is_dir() and
            all(p.is_file() for p in (crt, key)) and
            db.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()) and
            crt.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()) and
            key.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve())):
        print("[K-U] Faltan archivos temporales, base aislada o credencial ficticia.")
        return 1

    app = create_ks_contract_test_app(
        db, admin, kt_idempotency_required=True
    )
    # No abrir 0.0.0.0, VPN, AWS, router, WSS ni motores.
    print("[K-U] HTTPS 127.0.0.1:9443; admision VIRTUAL sin actuadores.", flush=True)
    uvicorn.run(
        app, host="127.0.0.1", port=9443, log_level="warning",
        ssl_certfile=str(crt), ssl_keyfile=str(key),
        access_log=False, proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
