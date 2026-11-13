"""K-G: arrancar FastAPI principal y K-C WSS en la misma instancia, LAN aislada."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LAB = Path.home() / "Downloads" / "Etapa_5_5_H_WSS_Directo_Local" / "Etapa_5_5_H_WSS_Directo_Local"
sys.path.insert(0, str(ROOT))
if not (LAB / "servidor_55kc.py").is_file() or not (LAB / "servidor_55j.py").is_file():
    raise SystemExit("[55-K-G] Falta K-C en la carpeta 55-H validada.")
sys.path.append(str(LAB))

from app.public_control.kg_bootstrap import create_kg_app
import servidor_55kc as kc


def main() -> None:
    firmware = LAB / "firmware" / "plantilla_55h.ino"
    if (not firmware.is_file() or not re.search(
        r"(?m)^\\s*#define\\s+ETAPA54_DIAGNOSTICO_SEGURO\\s+1\\s*$",
        firmware.read_text(encoding="utf-8-sig", errors="replace"),
    )):
        raise SystemExit("[55-K-G] ABORTADO: plantilla firmware sin inhibicion GPIO.")
    config, _ = kc.old.load_config()
    print("[55-K-G] FASTAPI + WSS K-C en UN ASGI, diagnostico virtual", flush=True)
    print(f"[55-K-G] LAN: {config['ip']}:8443. HTTP operador SOLO desde esta PC.", flush=True)
    print("[55-K-G] REST legacy bloqueado; AWS/RDS apagados; bateria desconectada.", flush=True)
    print("[55-K-G] No abrir 8443 en router ni Internet.", flush=True)
    app = create_kg_app(kc)
    import uvicorn
    uvicorn.run(
        app, host=config["ip"], port=8443, workers=1,
        ssl_certfile=str(kc.old.PRIVATE / "server.pem"),
        ssl_keyfile=str(kc.old.PRIVATE / "server-key.pem"),
        ws_ping_interval=5.0, ws_ping_timeout=5.0,
        proxy_headers=False, access_log=False, log_level="warning",
    )


if __name__ == "__main__":
    main()
