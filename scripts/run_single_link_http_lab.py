"""Iniciar la admisión HTTP K-B solo en la PC de laboratorio, sin actuadores."""
from secrets import token_urlsafe

import uvicorn

from app.public_control.single_link_http_lab import create_portal_http_lab_app

if __name__ == "__main__":
    key = token_urlsafe(32)
    print("\n[K-B] LABORATORIO SOLO LOCAL, no es la API de producción.", flush=True)
    print("[K-B] 127.0.0.1:8767; sin AWS, WSS ni motores.", flush=True)
    print("[K-B] Token administrativo temporal (NO COMPARTIR):", flush=True)
    print(key, flush=True)
    uvicorn.run(
        create_portal_http_lab_app(key), host="127.0.0.1", port=8767,
        proxy_headers=False, server_header=False, access_log=False,
    )
