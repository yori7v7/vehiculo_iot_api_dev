"""55-I: PASARELA WSS exclusiva ESP8266 + autoridad K-V/K-X IN-PROCESS.

Solo laboratorio: expone a la LAN UNICAMENTE la ruta WSS del ESP.
El resto de endpoints K-V son INACCESIBLES por cualquier socket de red.
La demostracion de solicitud/aprobacion/orden/revocacion usa un cliente
ASGITransport interno, no crea proxy, rutas admin publicas ni AWS.
NO habilita fisicamente el 74HC595: requiere firmware 55-H diagnostico.
"""
from __future__ import annotations

import asyncio
from ipaddress import ip_address, ip_network
from pathlib import Path
import os
import secrets
import socket
import tempfile

import httpx
import uvicorn

from app.public_control.kv_virtual_staging import PAGES_ORIGIN, STAGING_HOST
from app.public_control.kv_kx_virtual_bridge_lab import (
    HOTSPOT_PATH, LOCAL_ACTION, create_kv_kx_virtual_lab_app,
)
from scripts.servidor_55h_hotspot_seguro import PRIVATE_DIR, read_private_identity


# Bind to the only explicitly tested phone-hotspot ESP IP, fail closed if changed.
ESP_IP = "172.22.82.5"
LAB_PORT = 8443


class WssOnlyFromESP:
    """Network-facing ASGI perimeter; all HTTP blocked (even from loopback).

    The underlying K-V/K-X app can only receive administrative requests
    from code in the SAME process via httpx.ASGITransport(app=app).
    """

    def __init__(self, app, *, esp_ip: str, host: str):
        ip = ip_address(esp_ip)
        if ip.version != 4 or not ip.is_private or ip.is_loopback:
            raise ValueError("NO-GO: peer ESP debe ser IPv4 privada")
        if not host or ":" not in host:
            raise ValueError("NO-GO: Host del servidor invalido")
        self._app = app
        self._esp = str(ip)
        self._host = host

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan":
            return await self._app(scope, receive, send)
        if kind == "http":
            # Ni siquiera se enruta a los controladores: no exponer REST K-V.
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"cache-control", b"no-store")]})
            return await send({"type": "http.response.body", "body": b""})
        if kind != "websocket":
            return
        peer = scope.get("client")
        headers = [(k.lower(), v) for k, v in scope.get("headers", [])]
        host = [v.decode("ascii", "replace") for k, v in headers if k == b"host"]
        blocked = {b"origin", b"authorization", b"cookie",
                   b"forwarded", b"x-forwarded-for", b"x-real-ip"}
        invalid = (
            not peer or peer[0] != self._esp or
            scope.get("path") != HOTSPOT_PATH or
            scope.get("query_string", b"") != b"" or
            host != [self._host] or any(k in blocked for k, _ in headers)
        )
        if invalid:
            await send({"type": "websocket.close", "code": 1008})
            return
        await self._app(scope, receive, send)


def preflight():
    cfg, key = read_private_identity()
    host = cfg["ip"]
    server_ip = ip_address(host)
    esp = ip_address(ESP_IP)
    if (server_ip.version != 4 or esp.version != 4 or
            esp not in ip_network(f"{host}/24", strict=False) or
            esp == server_ip or not server_ip.is_private):
        raise ValueError("NO-GO: hotspot cambio de segmento")
    # Do not attempt installation or automatic firewall changes.
    if len(key) != 32 or not (PRIVATE_DIR / "server-key.pem").is_file():
        raise ValueError("NO-GO: identidad 55-H incompleta")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((host, LAB_PORT)) == 0:
            raise ValueError("NO-GO: 8443 ocupado por otro servidor")
    return host, key


async def wait_for_esp(hub, *, seconds=150):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        if hub.ready:
            return
        await asyncio.sleep(.15)
    raise TimeoutError("NO-GO: ESP no autentico WSS / STOP inicial")


async def run_internal_kv_demo(app):
    """Run real lease ledger and signed virtual command through live hub."""
    admin = app.state.lab55i_admin
    proxy = app.state.lab55i_proxy
    headers = {
        "Host": STAGING_HOST,
        "Origin": PAGES_ORIGIN,
        "X-Admission-Proxy-Token": proxy,
        "X-Admission-Client-IP": "8.8.8.8",
        "X-Admission-Scheme": "https",
    }
    inbox = "/admin/vehiculos/1/control-publico/solicitudes"
    guest = "/publico/vehiculos/1/solicitudes"
    token = secrets.token_urlsafe(32)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50001))
    async with httpx.AsyncClient(
        transport=transport, base_url=f"https://{STAGING_HOST}",
        timeout=8.0,
    ) as client:
        def good(response, status):
            if response.status_code != status:
                raise RuntimeError(
                    f"NO-GO: K-V estado HTTP {response.status_code}, esperado {status}"
                )
            return response.json()

        approval = good(await client.post(guest, headers={
            **headers,
            "Idempotency-Key": secrets.token_urlsafe(32),
            "X-Browser-Proposal": token,
        }), 201)
        admin_headers = {**headers, "X-API-Key": admin}
        good(await client.post(inbox + "/supervision",
                               headers=admin_headers), 200)
        good(await client.post(
            inbox + f"/{approval['request_id']}/aprobar",
            headers=admin_headers,
            json={"modo": "timed", "segundos": 120},
        ), 200)
        print("[55-I] K-V: invitado aprobado en ledger LOCAL, sin control fisico", flush=True)
        action_path = LOCAL_ACTION.replace("{id_vehiculo}", "1")
        try:
            result = good(await client.post(
                action_path, headers={**headers, "X-Browser-Session": token},
                json={"codigo": 9, "duracion_ms": 250},
            ), 200)
            if (result.get("control_fisico") is not False or
                    result.get("motor") is not False or
                    result.get("stop_fisico_confirmado") is not False or
                    result.get("neutral_virtual_reportado") is not True):
                raise RuntimeError("NO-GO: respuesta virtual no cumple contrato")
            print("[55-I] Orden 9 + STOP 0: ACKs HMAC del ESP verificados", flush=True)
        finally:
            # Revocation is idempotent and acts before reporting completion.
            revoked = await client.post(inbox + "/revocar",
                                        headers=admin_headers)
            if revoked.status_code != 200:
                raise RuntimeError("NO-GO: no se pudo revocar turno de prueba")
            print("[55-I] K-V revocado; sesion dispositivo invalidada", flush=True)
        denied = await client.post(
            action_path, headers={**headers, "X-Browser-Session": token},
            json={"codigo": 9, "duracion_ms": 250},
        )
        if denied.status_code != 403:
            raise RuntimeError("NO-GO: orden posterior a revocacion no fue denegada")
        print("[55-I] APROBADO: solicitud, orden, STOP, revocacion y denegacion", flush=True)


async def main_async():
    host, key = preflight()
    old_vars = {
        name: os.environ.get(name)
        for name in ("APP_ENV", "ADMISSION_VIRTUAL_ONLY", "KX_KV_VIRTUAL_BRIDGE_LAB")
    }
    os.environ.update({
        "APP_ENV": "staging",
        "ADMISSION_VIRTUAL_ONLY": "enabled",
        "KX_KV_VIRTUAL_BRIDGE_LAB": "isolated_lab_local",
    })
    try:
        with tempfile.TemporaryDirectory(prefix="55i_virtual_sqlite_") as tmp:
            admin = secrets.token_urlsafe(40)
            proxy = secrets.token_urlsafe(40)
            app = create_kv_kx_virtual_lab_app(
                Path(tmp) / "kv55i.sqlite3", admin, proxy, key,
                hotspot_host=f"{host}:{LAB_PORT}", hotspot_device_ip=ESP_IP,
            )
            app.state.lab55i_admin = admin
            app.state.lab55i_proxy = proxy
            gateway = WssOnlyFromESP(app, esp_ip=ESP_IP, host=f"{host}:{LAB_PORT}")
            config = uvicorn.Config(
                gateway, host=host, port=LAB_PORT, workers=1,
                proxy_headers=False, access_log=False, log_level="warning",
                ws="wsproto", lifespan="on",
                ssl_certfile=str(PRIVATE_DIR / "server.pem"),
                ssl_keyfile=str(PRIVATE_DIR / "server-key.pem"),
            )
            server = uvicorn.Server(config)
            task = asyncio.create_task(server.serve())
            try:
                for _ in range(100):
                    if server.started or task.done():
                        break
                    await asyncio.sleep(.1)
                if not server.started:
                    raise RuntimeError("NO-GO: servicio TLS no pudo iniciar")
                print(f"[55-I] LAB WSS EXCLUSIVO {host}:{LAB_PORT} -> ESP {ESP_IP}", flush=True)
                print("[55-I] HTTP de red siempre 404; K-V solo en proceso privado", flush=True)
                print("[55-I] BATERIA DESCONECTADA, GPIO siempre cero, AWS APAGADO", flush=True)
                print("[55-I] Esperando ESP autenticado y STOP inicial virtual...", flush=True)
                await wait_for_esp(app.state.kx_diag_hub)
                print("[55-I] ESP autenticado, STOP inicial firmado: OK", flush=True)
                await run_internal_kv_demo(app)
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=15)
    finally:
        for name, before in old_vars.items():
            if before is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = before


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
