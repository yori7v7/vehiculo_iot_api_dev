"""K-X preflight: Caddy REAL + FastAPI K-X REAL + legacy HTTP ficticio.

Todas las entradas son loopback Windows y temporales; NO es una prueba TLS
ni una instalacion: se representa la terminacion HTTPS con X-Forwarded-Proto
FIJADO por Caddy local, sin exponer el puerto 443 ni tocar la API legacy.
La autenticacion WSS NO se completa; ningun ESP ni salida fisica.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

HOST = "127.0.0.1"
DOMAIN = "100-30-4-62.nip.io"
ORIGIN = "https://yori7v7.github.io"
GUEST = "/publico/vehiculos/1/solicitudes"
WSS = "/ws/kx-diagnostico/1"
EXPECTED = "AABB6EFF0F31B6171DA1795FE69C6DA62015A3B0AD61452494AD57F917A7D839"
PROTECTED_PORTS = {443, 8000, 9444}
KEY_PORT = 9444


def free_port(exclude: set[int]) -> int:
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((HOST, 0))
            number = int(s.getsockname()[1])
            if number not in exclude and number >= 1024:
                return number
    raise RuntimeError("No se encontro puerto efimero")


def assert_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, port))


def http_request(port: int, method: str, path: str, headers=None):
    conn = http.client.HTTPConnection(HOST, port, timeout=4)
    try:
        h = {"Host": DOMAIN}
        h.update(headers or {})
        conn.request(method, path, headers=h)
        response = conn.getresponse()
        data = response.read(4096)
        return response.status, data, response.getheader("X-KX-Stub")
    finally:
        conn.close()


def exact(sock: socket.socket, count: int) -> bytes:
    result = b""
    while len(result) < count:
        block = sock.recv(count - len(result))
        if not block:
            raise RuntimeError("Socket cerrado durante desafio")
        result += block
    return result


def ws_challenge(port: int) -> None:
    with socket.create_connection((HOST, port), timeout=4) as ws:
        ws.settimeout(4)
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        packet = (
            "GET /ws/kx-diagnostico/1 HTTP/1.1\r\n"
            "Host: 100-30-4-62.nip.io\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: websocket\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        ws.sendall(packet.encode("ascii"))
        headers = b""
        while not headers.endswith(b"\r\n\r\n"):
            headers += exact(ws, 1)
            if len(headers) > 8192:
                raise RuntimeError("Cabeceras WS excesivas")
        if not headers.startswith(b"HTTP/1.1 101 "):
            raise RuntimeError("Proxy no devolvio HTTP 101")
        first = exact(ws, 2)
        if (first[0] & 0x0F) != 1 or first[1] & 0x80:
            raise RuntimeError("Marco WS inesperado")
        length = first[1] & 0x7F
        if length == 126:
            length = int.from_bytes(exact(ws, 2), "big")
        elif length == 127:
            raise RuntimeError("Marco WS demasiado grande")
        if length > 512:
            raise RuntimeError("Desafio WS demasiado grande")
        message = json.loads(exact(ws, length))
        if message.get("tipo") != "desafio_dispositivo_lab" or message.get("simulado") is not True:
            raise RuntimeError("No se recibio desafio virtual")


@contextmanager
def legacy_stub(port: int):
    class Stub(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"legacy-read-stub"
            self.send_response(200)
            self.send_header("X-KX-Stub", "legacy")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer((HOST, port), Stub)
    runner = threading.Thread(target=server.serve_forever, daemon=True)
    runner.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        runner.join(timeout=4)


def loopback_config(candidate: str, port: int, old_port: int) -> str:
    if candidate.count(DOMAIN + " {") != 1:
        raise RuntimeError("Sitio candidato inesperado")
    if candidate.count("reverse_proxy 127.0.0.1:9444") != 1:
        raise RuntimeError("Falta upstream K-X")
    if candidate.count("reverse_proxy 127.0.0.1:8000") != 1:
        raise RuntimeError("Falta upstream de lectura legacy")
    for required in (
        "NO INSTALAR", "handle @kx_contract", "handle @legacy_write",
        "handle @legacy_websockets", "handle @legacy_upgrade",
        "header Upgrade *", "header_up X-Forwarded-Proto https",
        'respond "Escrituras legacy cerradas durante K-X" 503'
    ):
        if required not in candidate:
            raise RuntimeError("Falta proteccion obligatoria en candidato")
    cfg = candidate.replace(DOMAIN + " {", f"http://127.0.0.1:{port} {{")
    cfg = cfg.replace("reverse_proxy 127.0.0.1:8000",
                      f"reverse_proxy 127.0.0.1:{old_port}")
    # K-X conserva 9444 LOCAL; 443 nunca se abre en este ensayo.
    return "{\n    admin off\n    auto_https off\n}\n\n" + cfg


def close_child(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)


def cleanup_state(root: Path) -> None:
    for attempt in range(25):
        try:
            shutil.rmtree(root)
            return
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="K-X proxy and real app, loopback only")
    for name in ("repo", "python", "caddy-exe", "candidate", "active", "key-path"):
        parser.add_argument("--" + name, type=Path, required=True)
    opts = parser.parse_args(argv)
    kx = None
    proxy = None
    temp = None
    active_hash = None
    phase = "preflight"
    failure = None
    ports = []
    try:
        if sys.platform != "win32":
            raise RuntimeError("Solo Windows Server")
        repo = opts.repo.resolve(strict=True)
        python = opts.python.resolve(strict=True)
        if python != (repo / ".venv" / "Scripts" / "python.exe").resolve(strict=True):
            raise RuntimeError("Python no pertenece al candidato")
        if not all(p.is_file() and not p.is_symlink()
                   for p in (opts.caddy_exe, opts.candidate, opts.active, opts.key_path)):
            raise RuntimeError("Falta archivo seguro")
        if opts.candidate.name != "Caddyfile.kx_diagnostic_NOT_DEPLOY":
            raise RuntimeError("No se uso candidato protegido")
        if (repo / ".env").exists():
            raise RuntimeError("Configuracion privada inesperada en el repositorio")
        key = opts.key_path
        if key.stat().st_size != 32 or hashlib.sha256(key.read_bytes()).hexdigest().upper() != EXPECTED:
            raise RuntimeError("Identidad HMAC no coincide")
        active_hash = hashlib.sha256(opts.active.read_bytes()).hexdigest()
        assert_available(KEY_PORT)
        ports = [KEY_PORT]
        edge = free_port(set(ports) | PROTECTED_PORTS)
        ports.append(edge)
        old = free_port(set(ports) | PROTECTED_PORTS)
        ports.append(old)
        temporary_caddy = loopback_config(
            opts.candidate.read_text(encoding="utf-8-sig"), edge, old
        )
        for line in temporary_caddy.splitlines():
            if line.strip().startswith("#"):
                continue
            if "reverse_proxy 127.0.0.1:8000" in line or "127.0.0.1:443" in line:
                raise RuntimeError("Direccion legacy real en configuracion de prueba")
        temp = Path(tempfile.mkdtemp(prefix="kx-proxy-integracion-"))
        caddyfile = temp / "Caddyfile.loopback_NOT_DEPLOY"
        caddyfile.write_text(temporary_caddy, encoding="utf-8")
        phase = "validacion Caddy temporal"
        validated = subprocess.run(
            [str(opts.caddy_exe), "validate", "--config", str(caddyfile),
             "--adapter", "caddyfile"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12,
        )
        if validated.returncode != 0:
            raise RuntimeError("Caddy no valido configuracion temporal")
        print("CADDY LOCAL: CONFIGURACION VALIDADA")
        with legacy_stub(old):
            env = os.environ.copy()
            env.update({
                "APP_ENV": "production",
                "API_KEY": secrets.token_urlsafe(48),
                "PUBLIC_VIRTUAL_ADMISSION_ENABLED": "true",
                "PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH": str(temp / "tickets.sqlite3"),
                "KX_DIAGNOSTIC_WSS_ENABLED": "true",
                "KX_DIAGNOSTIC_WSS_KEY_PATH": str(key.resolve(strict=True)),
                "CONTROL_PUBLICO_ENABLED": "false",
                "CONTROL_PUBLICO_SIMULATION": "false",
                "DEVICE_LAB_ENABLED": "false",
            })
            phase = "FastAPI K-X"
            kx = subprocess.Popen(
                [str(python), "-m", "uvicorn", "app.main:app", "--host", HOST,
                 "--port", str(KEY_PORT), "--workers", "1",
                 "--proxy-headers", "--forwarded-allow-ips", HOST,
                 "--no-access-log", "--log-level", "warning"],
                cwd=str(repo), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for _ in range(110):
                if kx.poll() is not None:
                    raise RuntimeError("FastAPI K-X no inicio")
                try:
                    if http_request(KEY_PORT, "GET", "/docs")[0] == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("FastAPI K-X no respondio")
            print("FASTAPI K-X REAL: ACTIVO SOLO EN LOOPBACK")
            phase = "Caddy local"
            proxy = subprocess.Popen(
                [str(opts.caddy_exe), "run", "--config", str(caddyfile),
                 "--adapter", "caddyfile"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for _ in range(90):
                if proxy.poll() is not None:
                    raise RuntimeError("Caddy temporal no inicio")
                try:
                    status, _body, stub = http_request(edge, "GET", "/docs")
                    if status == 200 and stub == "legacy":
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Caddy temporal no respondio")
            print("CADDY + LEGACY FICTICIO: SOLO LECTURA")
            phase = "contratos HTTP y WS"
            status, _body, _ = http_request(edge, "POST", "/vehiculos/1/movimientos")
            if status != 503:
                raise RuntimeError("Caddy no bloqueo escritura legacy")
            print("ESCRITURA LEGACY: HTTP 503")
            status, _body, _ = http_request(edge, "GET", "/ws/vehiculos/1")
            if status != 403:
                raise RuntimeError("Caddy no bloqueo WebSocket legacy")
            print("WEBSOCKET LEGACY: HTTP 403")
            status, _body, _ = http_request(
                edge, "GET", GUEST + "/estado", {"Origin": ORIGIN},
            )
            if status != 401:
                raise RuntimeError("K-X no reconocio HTTPS virtualizado por Caddy")
            print("K-X A TRAVES DE PROXY: ESQUEMA HTTPS RECONOCIDO")
            token = lambda: secrets.token_urlsafe(32)
            status, body, _ = http_request(edge, "POST", GUEST, {
                "Origin": ORIGIN,
                "Idempotency-Key": token(),
                "X-Browser-Proposal": token(),
            })
            payload = json.loads(body)
            if (status != 201 or payload.get("canDrive") is not False
                    or payload.get("simulado") is not True
                    or payload.get("control_fisico") is not False):
                raise RuntimeError("Solicitud virtual invitado rechazada o insegura")
            print("SOLICITUD INVITADO: HTTP 201, canDrive=false")
            ws_challenge(edge)
            print("WEBSOCKET CADDY > K-X: HTTP 101, DESAFIO VIRTUAL")
            print("AUTENTICACION DEL ESP: NO")
            print("ORDENES / GPIO: NINGUNA")
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError,
            http.client.HTTPException, subprocess.SubprocessError) as exc:
        failure = (phase, type(exc).__name__)
    finally:
        try:
            close_child(proxy)
            close_child(kx)
            print("CADDY Y FASTAPI TEMPORALES: CERRADOS")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            failure = ("cierre", "ProcesoNoCerro")
        if temp is not None and (kx is None or kx.poll() is not None):
            try:
                cleanup_state(temp)
                print("SQLITE Y ARCHIVOS TEMPORALES: ELIMINADOS")
            except OSError:
                failure = ("limpieza", "SQLiteBloqueado")
        if active_hash is not None:
            try:
                if hashlib.sha256(opts.active.read_bytes()).hexdigest() != active_hash:
                    failure = ("Caddyfile activo", "CambioDetectado")
            except OSError:
                failure = ("Caddyfile activo", "NoVerificable")
        try:
            assert_available(KEY_PORT)
            print("PUERTO 9444: LIBRE")
        except OSError:
            failure = ("puerto 9444", "Ocupado")
    if failure is not None:
        print("NO-GO:", failure[0], failure[1], "| no desplegar")
        return 2
    print("CADDYFILE Y BACKEND ORIGINALES: INTACTOS")
    print("HTTPS TLS REAL: NO PROBADO")
    print("=== INTEGRACION PROXY K-X APROBADA ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
