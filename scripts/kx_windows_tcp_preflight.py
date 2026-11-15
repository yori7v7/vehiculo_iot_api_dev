"""K-X: ensayo TCP/HTTP/WS local en EC2 Windows, sin Caddy ni actuadores.

Solo se inicia un proceso Uvicorn HIJO en 127.0.0.1:9444 con DB descartable.
IMPORTANTE: detener el hijo y comprobar liberacion del puerto ANTES de
limpiar el SQLite temporal (evita WinError 32 con tickets.sqlite3.lock).
No levantar servicios persistentes, no acceder a RDS ni publicar la clave.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HOST = "127.0.0.1"
PUBLIC_HOST = "100-30-4-62.nip.io"
PORT = 9444
EXPECTED_FINGERPRINT = "AABB6EFF0F31B6171DA1795FE69C6DA62015A3B0AD61452494AD57F917A7D839"


def request(method: str, path: str) -> int:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=3)
    try:
        conn.request(method, path)
        res = conn.getresponse()
        res.read()
        return res.status
    finally:
        conn.close()


def exact(sock: socket.socket, count: int) -> bytes:
    result = b""
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise RuntimeError("WebSocket cerrado sin desafio")
        result += chunk
    return result


def challenge_only() -> None:
    """Solo leer el desafio: no firmar, autenticar ni mandar ordenes."""
    with socket.create_connection((HOST, PORT), timeout=4) as ws:
        ws.settimeout(4)
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        req = (
            "GET /ws/kx-diagnostico/1 HTTP/1.1\r\n"
            "Host: 100-30-4-62.nip.io\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        ws.sendall(req.encode("ascii"))
        headers = b""
        while not headers.endswith(b"\r\n\r\n"):
            headers += exact(ws, 1)
            if len(headers) > 8192:
                raise RuntimeError("Cabeceras WebSocket invalidas")
        if not headers.startswith(b"HTTP/1.1 101 "):
            raise RuntimeError("Handshake HTTP 101 no confirmado")
        first = exact(ws, 2)
        if (first[0] & 0x0F) != 1 or (first[1] & 0x80):
            raise RuntimeError("Primer marco WebSocket no valido")
        length = first[1] & 127
        if length == 126:
            length = int.from_bytes(exact(ws, 2), "big")
        elif length == 127:
            raise RuntimeError("Marco WebSocket largo no permitido")
        if length > 512:
            raise RuntimeError("Desafio demasiado grande")
        data = json.loads(exact(ws, length))
        if data.get("tipo") != "desafio_dispositivo_lab" or data.get("simulado") is not True:
            raise RuntimeError("Desafio inesperado")


def assert_port_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Bind SIN SO_REUSEADDR. No abrir una conexion al servicio antiguo.
        s.bind((HOST, PORT))


def terminate_own_child(process: subprocess.Popen | None) -> None:
    """Detener SOLO el PID creado por este ensayo, nunca buscar/kill otro PID."""
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)
    # Ya no debe haber un listener en ese puerto.
    for _ in range(40):
        try:
            assert_port_free()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Puerto de ensayo aun ocupado tras cerrar su proceso")


def cleanup_temporary_state(path: Path) -> None:
    """Solo borrar la carpeta creada por mkdtemp cuando el hijo ha salido."""
    for retry in range(20):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if retry == 19:
                raise
            time.sleep(0.2)


def main(args=None) -> int:
    p = argparse.ArgumentParser(description="K-X Windows loopback only; no deploy")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--key-path", required=True, type=Path)
    p.add_argument("--active-caddy", required=True, type=Path)
    opt = p.parse_args(args)
    process = None
    temporary = None
    parent_caddy_hash = None
    error = None
    try:
        if sys.platform != "win32":
            raise RuntimeError("Esta prueba requiere EC2 Windows")
        repo = opt.repo.resolve(strict=True)
        key = opt.key_path
        caddy = opt.active_caddy
        expected_python = repo / ".venv" / "Scripts" / "python.exe"
        if (not expected_python.is_file() or
                Path(sys.executable).resolve() != expected_python.resolve() or
                not (repo / "app" / "public_control" / "kx_signed_wss.py").is_file() or
                not caddy.is_file() or caddy.is_symlink() or key.is_symlink() or
                not key.is_file() or (repo / ".env").exists()):
            raise RuntimeError("Estructura local privada inesperada")
        if key.stat().st_size != 32 or hashlib.sha256(key.read_bytes()).hexdigest().upper() != EXPECTED_FINGERPRINT:
            raise RuntimeError("Identidad privada distinta de la comprobada")
        parent_caddy_hash = hashlib.sha256(caddy.read_bytes()).hexdigest()
        print("IDENTIDAD PRIVADA: VERIFICADA")
        assert_port_free()
        print("PUERTO 9444: DISPONIBLE")
        # El temp NO pertenece al proceso hijo; no se limpia hasta que este salga.
        temporary = Path(tempfile.mkdtemp(prefix="kx-9444-"))
        env = os.environ.copy()
        env.update({
            "APP_ENV": "production",
            "API_KEY": secrets.token_urlsafe(48),
            "PUBLIC_VIRTUAL_ADMISSION_ENABLED": "true",
            "PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH": str(temporary / "tickets.sqlite3"),
            "KX_DIAGNOSTIC_WSS_ENABLED": "true",
            "KX_DIAGNOSTIC_WSS_KEY_PATH": str(key.resolve(strict=True)),
            "CONTROL_PUBLICO_ENABLED": "false",
            "CONTROL_PUBLICO_SIMULATION": "false",
            "DEVICE_LAB_ENABLED": "false",
        })
        print("INICIANDO FASTAPI LOCAL K-X...")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", HOST, "--port", str(PORT), "--workers", "1",
             "--no-proxy-headers", "--no-access-log", "--log-level", "warning"],
            cwd=str(repo), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("FastAPI K-X cerro antes de iniciar")
            try:
                if request("GET", "/docs") == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("FastAPI K-X no respondio en localhost")
        print("FASTAPI 127.0.0.1:9444: ACTIVO")
        if request("POST", "/vehiculos/1/movimientos") != 503:
            raise RuntimeError("Escritura legacy no fue bloqueada")
        print("ESCRITURAS LEGACY: HTTP 503")
        if request("GET", "/publico/vehiculos/1/solicitudes/estado") != 403:
            raise RuntimeError("Ingreso HTTP sin HTTPS aceptado")
        print("ADMISION HTTP SIN HTTPS: HTTP 403")
        challenge_only()
        print("HANDSHAKE WEBSOCKET LOCAL: HTTP 101")
        print("DESAFIO DEL DISPOSITIVO: RECIBIDO")
        print("AUTENTICACION DEL ESP: NO REALIZADA")
        print("ORDENES FISICAS: NINGUNA")
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError,
            http.client.HTTPException, subprocess.SubprocessError) as exc:
        error = type(exc).__name__
    finally:
        # CORRECCION PRINCIPAL: cerrar y esperar al proceso ANTES de rmtree.
        try:
            terminate_own_child(process)
            print("PROCESO K-X TEMPORAL: CERRADO")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            error = "CierreDeProcesoFallido"
            print("NO-GO: proceso temporal requiere revision")
        if temporary is not None:
            if process is None or process.poll() is not None:
                try:
                    cleanup_temporary_state(temporary)
                    print("SQLITE TEMPORAL: ELIMINADA")
                except (OSError, PermissionError):
                    error = "LimpiezaTemporalFallida"
                    print("NO-GO: limpieza SQLite pendiente; no borrar a la fuerza")
            else:
                error = "ProcesoRetieneEstado"
                print("NO-GO: no limpiar SQLite mientras el proceso vive")
        if parent_caddy_hash is not None:
            try:
                if hashlib.sha256(caddy.read_bytes()).hexdigest() != parent_caddy_hash:
                    error = "CaddyfileActivoCambio"
            except OSError:
                error = "CaddyfileNoVerificable"
    if error is not None:
        print("NO-GO:", error, "| NO habilitar Caddy")
        return 2
    print("CADDY Y BACKEND ORIGINAL: NO MODIFICADOS POR LA PRUEBA")
    print("PUERTOS PUBLICOS: SIN CAMBIOS")
    print("=== PRUEBA TCP K-X APROBADA ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
