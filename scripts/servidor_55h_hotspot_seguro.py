"""Servidor TLS/WSS 55-H para ESP8266 en hotspot, SOLO DIAGNOSTICO.

Reutiliza la identidad privada generada para el sketch del PR 55-H.
No contiene autoridad física ni puente al navegador, AWS o RDS.
No abrir el puerto 8443 en el router ni exponerlo a Internet.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from app.device_channel.authenticated_lab import DeviceLabHandshake, LabDeviceProtocolError
from app.device_channel.command_wire import AckFence, CommandWire, DeviceOrder, WireProtocolError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = PROJECT_ROOT / "firmware" / "Excavadora_IoT_55H_Hotspot_Seguro" / "private"
WSS_PATH = "/ws/dispositivos-lab/1/contrato"
MAX_FRAME_BYTES = 512
LOCAL_SUBNET_PREFIX = 24


def read_private_identity(private_dir: Path = PRIVATE_DIR) -> tuple[dict, bytes]:
    """Carga LA MISMA clave que quedó incorporada al firmware compilado.

    NO ejecuta preparadores, NO regenera claves y NO revela secretos.
    """
    private_dir = Path(private_dir).resolve()
    conf = json.loads((private_dir / "settings.json").read_text(encoding="utf-8"))
    device_key = (private_dir / "device-key.bin").read_bytes()
    ip = ipaddress.ip_address(conf.get("ip", ""))
    if (type(conf.get("port")) is not int or conf["port"] != 8443 or
            type(conf.get("vehicle_id")) is not int or conf["vehicle_id"] != 1 or
            conf.get("mode") != "lab55h" or
            conf.get("physical_enabled") is not False or
            ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or
            type(device_key) is not bytes or len(device_key) != 32):
        raise ValueError("NO-GO: identidad o configuración privada incompatible con LAB")
    for filename in ("server.pem", "server-key.pem", "ca.pem"):
        if not (private_dir / filename).is_file():
            raise ValueError("NO-GO: certificado TLS de laboratorio ausente")
    return conf, device_key


def verified_peer(ws: WebSocket, ip: str) -> bool:
    """Solo clientes desde la misma subred privada del hotspot y Host correcto."""
    if ws.client is None:
        return False
    try:
        address = ipaddress.ip_address(ws.client.host)
        host_header = ws.headers.get("host", "")
        hostname = urlsplit("https://" + host_header).hostname
        network = ipaddress.ip_network(f"{ip}/{LOCAL_SUBNET_PREFIX}", strict=False)
    except (ValueError, TypeError):
        return False
    if (address.version != 4 or address not in network or
            hostname != ip or
            ws.query_params or
            any(ws.headers.get(h) for h in (
                "origin", "forwarded", "x-forwarded-for", "x-real-ip",
                "proxy-authorization", "authorization", "via", "cookie",
            ))):
        return False
    return True


async def receive_strict(ws: WebSocket, seconds: float = 5.0) -> dict:
    raw = await asyncio.wait_for(ws.receive_text(), timeout=seconds)
    if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
        raise LabDeviceProtocolError("Trama demasiado grande")

    def reject_duplicates(pairs: list) -> dict:
        result = {}
        for name, value in pairs:
            if name in result:
                raise LabDeviceProtocolError("Clave JSON duplicada")
            result[name] = value
        return result

    result = json.loads(raw, object_pairs_hook=reject_duplicates)
    if type(result) is not dict:
        raise LabDeviceProtocolError("Trama JSON inválida")
    return result


async def send_virtual(ws: WebSocket, fence: AckFence, order: DeviceOrder) -> None:
    await ws.send_json(fence.queue(order))
    for expected in ("recibida", "neutral_reportado_no_fisico"):
        reply = await receive_strict(ws, seconds=5)
        if fence.consume(reply) != expected:
            raise WireProtocolError("Secuencia ACK virtual incompatible")


def create_55h_hotspot_lab_app(private_dir: Path = PRIVATE_DIR) -> FastAPI:
    cfg, device_key = read_private_identity(private_dir)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.active_device = False

    @app.get("/55h/estado", include_in_schema=False)
    async def status():
        return {"etapa": "55-H hotspot LAN", "simulado": True,
                "control_fisico": False, "canDrive": False,
                "salidas_reportadas": 0, "aws": False}

    @app.websocket(WSS_PATH)
    async def device(ws: WebSocket):
        if not verified_peer(ws, cfg["ip"]) or app.state.active_device:
            await ws.close(code=1008)
            return

        app.state.active_device = True
        accepted = False
        try:
            handshake = DeviceLabHandshake(1, device_key)
            await ws.accept()
            accepted = True
            await ws.send_json(handshake.challenge)
            print("[55-H] ESP conectado por WSS TLS; verificando desafio HMAC")
            response = await receive_strict(ws, 5)
            session, confirmation = handshake.verify(response)
            await ws.send_json(confirmation)
            print("[55-H] Autenticacion HMAC bidireccional: OK")
            fence = AckFence(CommandWire(session))
            for seq, code, duration in ((1, 9, 250), (2, 0, 0)):
                # Margen pequeño para compensar sincronización NTP del ESP.
                issued = int(time.time() * 1000) - 150
                order = DeviceOrder(
                    1, session.session_id, str(uuid4()),
                    1, seq, seq, issued, issued + 1000, duration, code,
                )
                await send_virtual(ws, fence, order)
                if code:
                    print("[55-H] Codigo 9 DIAGONAL VIRTUAL: ACKs firmados correctos; GPIO=0 por diseño")
                else:
                    print("[55-H] STOP 0 VIRTUAL: ACKs firmados correctos")
            print("[55-H] APROBADO: enlace TLS/HMAC de diagnostico; no se comprobo parada fisica")
            await ws.send_json({"tipo": "prueba_contrato_terminada",
                                "simulado": True,
                                "parada_fisica_verificada": False, "movimiento": 9, "detener": 0})
            await ws.close(code=1000)
        except (TimeoutError, LabDeviceProtocolError, WireProtocolError,
                json.JSONDecodeError, WebSocketDisconnect) as exc:
            print(f"[55-H] Sesion rechazada en modo seguro: {type(exc).__name__}")
            if accepted:
                try:
                    await ws.close(code=1008)
                except (RuntimeError, WebSocketDisconnect):
                    pass
        except Exception as exc:
            print(f"[55-H] Error de sesion: {type(exc).__name__}")
            if accepted:
                try:
                    await ws.close(code=1011)
                except (RuntimeError, WebSocketDisconnect):
                    pass
        finally:
            app.state.active_device = False

    return app


def main() -> None:
    cfg, _ = read_private_identity()
    server = create_55h_hotspot_lab_app()
    print("[55-H] SERVIDOR WSS HOTSPOT LOCAL - SOLO DIAGNOSTICO")
    print(f"[55-H] Escuchando en {cfg['ip']}:8443; bateria del RC DESCONECTADA")
    print("[55-H] NO abrir firewall, NAT o acceso de Internet automaticamente")
    uvicorn.run(
        server, host=cfg["ip"], port=8443, workers=1, proxy_headers=False,
        ssl_certfile=str(PRIVATE_DIR / "server.pem"),
        ssl_keyfile=str(PRIVATE_DIR / "server-key.pem"),
        access_log=False, log_level="warning",
    )


if __name__ == "__main__":
    main()
