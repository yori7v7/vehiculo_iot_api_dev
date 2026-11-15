"""K-W: puerta virtual detrás de Caddy REAL solo en GitHub Actions.

NO instalar como tarea Windows ni desplegar EC2. El puerto 9444 escucha en
127.0.0.1 exclusivamente y el comando se niega fuera del CI efímero.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import uvicorn

from app.public_control.kv_virtual_staging import create_kv_virtual_app


def main() -> int:
    if not all((
        os.environ.get("GITHUB_ACTIONS") == "true",
        os.environ.get("KW_TEST_LAB") == "isolated-loopback-only",
        os.environ.get("APP_ENV") == "staging",
        os.environ.get("ADMISSION_VIRTUAL_ONLY") == "enabled",
    )):
        print("[K-W] Solo GitHub Actions aislado; arranque denegado.")
        return 1

    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    db = Path(os.environ["KW_PRIVATE_DB"]).resolve()
    admin = os.environ.get("KW_ADMIN_TEST_KEY", "")
    proxy = os.environ.get("KW_PROXY_TEST_KEY", "")
    if (not db.is_relative_to(runner_temp) or not db.parent.is_dir()
            or len(admin) < 32 or len(proxy) < 32 or admin == proxy):
        print("[K-W] Base o credenciales efimeras invalidas.")
        return 1

    app = create_kv_virtual_app(db, admin, proxy)
    # SOLO CI: inspeccion de la estructura de cabeceras, nunca valores
    # secretos ni IP personal. Se elimina al salir del runner.
    from fastapi import Request

    @app.middleware("http")
    async def safe_ci_diagnostic(request: Request, call_next):
        response = await call_next(request)
        if response.status_code in (401, 403) and "/control-publico/solicitudes" in request.url.path:
            forbidden = (
                "forwarded", "x-forwarded-for", "x-forwarded-host",
                "x-forwarded-proto", "x-real-ip", "cookie", "authorization",
                "proxy-authorization",
            )
            print("[KW_DIAG] status", response.status_code,
                  "peer_loopback", request.client.host in ("127.0.0.1", "::1"),
                  "host_correct", request.headers.getlist("host") == ["100-30-4-62.nip.io"],
                  "origin_correct", request.headers.getlist("origin") == ["https://yori7v7.github.io"],
                  "scheme_proof", request.headers.getlist("x-admission-scheme") == ["https"],
                  "proxy_token_present", len(request.headers.getlist("x-admission-proxy-token")) == 1,
                  "client_ip_present", len(request.headers.getlist("x-admission-client-ip")) == 1,
                  "forbidden_present", [n for n in forbidden if request.headers.getlist(n)],
                  flush=True)
        return response

    print("[K-W] SOLO virtual: 127.0.0.1:9444; sin hardware.", flush=True)
    uvicorn.run(
        app, host="127.0.0.1", port=9444, workers=1,
        proxy_headers=False, access_log=False, server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
