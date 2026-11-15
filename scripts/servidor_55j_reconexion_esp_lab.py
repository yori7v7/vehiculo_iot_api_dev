"""55-J: real ESP8266 reconnection test, virtual-only and local hotspot.

Builds on the approved 55-I WSS-only network perimeter. Never starts
AWS/RDS, never opens firewall rules, never enables any GPIO output.
The ESP must run the existing diagnostic-only 55-H firmware.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import secrets
import tempfile

import httpx
import uvicorn

from app.public_control.kv_virtual_staging import PAGES_ORIGIN, STAGING_HOST
from app.public_control.kv_kx_virtual_bridge_lab import (
    LOCAL_ACTION, create_kv_kx_virtual_lab_app,
)
from scripts.servidor_55h_hotspot_seguro import PRIVATE_DIR
from scripts.servidor_55i_kv_kx_esp_lab import (
    ESP_IP, LAB_PORT, WssOnlyFromESP, preflight, wait_for_esp,
)


class DisconnectGate:
    """Permit only WSS connections while explicitly enabled by test."""

    def __init__(self, app):
        self.app = app
        self.allow_wss = True

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" and not self.allow_wss:
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def _headers(proxy):
    return {
        "Host": STAGING_HOST,
        "Origin": PAGES_ORIGIN,
        "X-Admission-Proxy-Token": proxy,
        "X-Admission-Client-IP": "8.8.8.8",
        "X-Admission-Scheme": "https",
    }


async def run_reconnection_demo(app, gate: DisconnectGate, *, timeout=75):
    """Drop a real authenticated ESP, deny offline and require new HMAC."""
    hub = app.state.kx_diag_hub
    headers = _headers(app.state.lab55j_proxy)
    admin_headers = {**headers, "X-API-Key": app.state.lab55j_admin}
    inbox = "/admin/vehiculos/1/control-publico/solicitudes"
    guest = "/publico/vehiculos/1/solicitudes"
    action = LOCAL_ACTION.replace("{id_vehiculo}", "1")
    browser_session = secrets.token_urlsafe(32)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50001))
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"https://{STAGING_HOST}", timeout=8.0,
    ) as client:
        def expect(response, code, stage):
            if response.status_code != code:
                raise RuntimeError(
                    f"NO-GO: {stage}: HTTP {response.status_code}, esperado {code}"
                )
            return response.json()

        created = expect(await client.post(guest, headers={
            **headers,
            "Idempotency-Key": secrets.token_urlsafe(32),
            "X-Browser-Proposal": browser_session,
        }), 201, "solicitud")
        expect(await client.post(inbox + "/supervision", headers=admin_headers),
               200, "supervision")
        expect(await client.post(
            inbox + f"/{created['request_id']}/aprobar",
            headers=admin_headers,
            json={"modo": "timed", "segundos": 120},
        ), 200, "aprobacion")
        session_headers = {**headers, "X-Browser-Session": browser_session}

        # The current live ESP completed mutual HMAC and the initial STOP.
        if not hub.ready or hub._session is None:
            raise RuntimeError("NO-GO: ESP no listo antes del corte")
        original_session = hub._session.session_id

        gate.allow_wss = False
        try:
            await hub.shutdown()  # closes real WSS; no simulated GPIO claims
            if hub.ready:
                raise RuntimeError("NO-GO: WSS sigue disponible tras el corte")
            print("[55-J] WSS cortado desde el servidor; nueva entrada bloqueada",
                  flush=True)
            denied = await client.post(
                action, headers=session_headers,
                json={"codigo": 9, "duracion_ms": 250},
            )
            expect(denied, 503, "orden mientras WSS caido")
            print("[55-J] Sin WSS autenticado: codigo 9 denegado (503)", flush=True)
        finally:
            gate.allow_wss = True

        print("[55-J] Reconexion WSS habilitada; requiere nuevo TLS/HMAC",
              flush=True)
        await wait_for_esp(hub, seconds=timeout)
        if hub._session is None or hub._session.session_id == original_session:
            raise RuntimeError("NO-GO: reconexion reutilizo sesion anterior")
        print("[55-J] Nueva sesion HMAC + STOP inicial firmado: OK", flush=True)
        # K-V supervision is only a 15-second heartbeat. Refresh using
        # the in-process authenticated admin after the network gap.
        expect(await client.post(inbox + "/supervision",
                                 headers=admin_headers), 200,
               "supervision tras reconectar")
        try:
            result = expect(await client.post(
                action, headers=session_headers,
                json={"codigo": 9, "duracion_ms": 250},
            ), 200, "orden tras autenticar")
            if (result.get("motor") is not False or
                    result.get("control_fisico") is not False or
                    result.get("neutral_virtual_reportado") is not True):
                raise RuntimeError("NO-GO: respuesta virtual invalida")
            print("[55-J] Nuevo WSS: orden 9 y STOP 0 firmados OK", flush=True)
        finally:
            revoked = await client.post(inbox + "/revocar",
                                        headers=admin_headers)
            expect(revoked, 200, "revocacion")
            print("[55-J] Turno K-V revocado; canal cerrado", flush=True)
        rejected = await client.post(
            action, headers=session_headers,
            json={"codigo": 9, "duracion_ms": 250},
        )
        expect(rejected, 403, "orden tras revocar")
        print("[55-J] APROBADO: desconexion, 503, nueva HMAC, STOP y 403",
              flush=True)


async def main_async():
    host, key = preflight()
    old_vars = {
        name: os.environ.get(name)
        for name in ("APP_ENV", "ADMISSION_VIRTUAL_ONLY",
                     "KX_KV_VIRTUAL_BRIDGE_LAB")
    }
    os.environ.update({
        "APP_ENV": "staging",
        "ADMISSION_VIRTUAL_ONLY": "enabled",
        "KX_KV_VIRTUAL_BRIDGE_LAB": "isolated_lab_local",
    })
    try:
        with tempfile.TemporaryDirectory(prefix="55j_virtual_sqlite_") as tmp:
            admin, proxy = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
            app = create_kv_kx_virtual_lab_app(
                Path(tmp) / "kv55j.sqlite3", admin, proxy, key,
                hotspot_host=f"{host}:{LAB_PORT}", hotspot_device_ip=ESP_IP,
            )
            app.state.lab55j_admin = admin
            app.state.lab55j_proxy = proxy
            gate = DisconnectGate(WssOnlyFromESP(
                app, esp_ip=ESP_IP, host=f"{host}:{LAB_PORT}",
            ))
            cfg = uvicorn.Config(
                gate, host=host, port=LAB_PORT, workers=1,
                proxy_headers=False, access_log=False, log_level="warning",
                ws="wsproto", lifespan="on",
                # Uvicorn sin limite espera websockets hasta que vence
                # el timeout externo y Windows deja SQLite.lock abierto.
                # Cancelar tareas residuales antes del cierre lifespan.
                timeout_graceful_shutdown=5,
                ssl_certfile=str(PRIVATE_DIR / "server.pem"),
                ssl_keyfile=str(PRIVATE_DIR / "server-key.pem"),
            )
            server = uvicorn.Server(cfg)
            task = asyncio.create_task(server.serve())
            try:
                for _ in range(100):
                    if server.started or task.done():
                        break
                    await asyncio.sleep(.1)
                if not server.started:
                    raise RuntimeError("NO-GO: servicio TLS no pudo iniciar")
                print(f"[55-J] WSS SOLO {host}:{LAB_PORT} -> ESP {ESP_IP}",
                      flush=True)
                print("[55-J] HTTP siempre 404; K-V solo en proceso privado",
                      flush=True)
                print("[55-J] AWS APAGADO, BATERIA DESCONECTADA, GPIO=0",
                      flush=True)
                print("[55-J] Esperando WSS/HMAC + STOP inicial ESP...",
                      flush=True)
                await wait_for_esp(app.state.kx_diag_hub, seconds=150)
                print("[55-J] ESP autenticado inicialmente: OK", flush=True)
                await run_reconnection_demo(app, gate)
            finally:
                # Antes del shutdown se rechazan nuevos reintentos WSS:
                # el ESP 55-H intenta reconectar automaticamente.
                gate.allow_wss = False
                server.should_exit = True
                # El cierre con timeout propio Uvicorn debe finalizar
                # lifespan (ledger.close/fence.close) ANTES de que se
                # elimine el directorio temporal de Windows.
                await asyncio.wait_for(task, timeout=25)
    finally:
        for name, before in old_vars.items():
            if before is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = before
    # Este mensaje se imprime SOLO tras borrar SQLite temporal.
    print("[55-J] CIERRE LIMPIO: Uvicorn detenido y SQLite temporal liberado",
          flush=True)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
