"""Ensayo K-X con Caddy REAL, pero SOLO loopback y servidores HTTP ficticios.

No instala Caddy, no recarga sus tareas, no abre 443/8000/9444 y no contacta
AWS ni un vehículo. Comprueba la precedencia de rutas, no un WSS real.
Ejecución manual con el Caddyfile candidato NO DESPLEGADO y caddy.exe.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import http.client
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

DOMAIN = "100-30-4-62.nip.io"
WSS = "/ws/kx-diagnostico/1"
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGINAL_PORTS = {443, 8000, 9444}


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
        if port in ORIGINAL_PORTS:
            return _free_local_port()
        return port


def _request(port: int, method: str, path: str, headers=None) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        response.read()
        return response.status, response.getheader("X-KX-Stub", "")
    finally:
        conn.close()


def _handler(label: str):
    class Stub(BaseHTTPRequestHandler):
        def _reply(self):
            body = ("KX-STUB-" + label).encode("ascii")
            self.send_response(200)
            self.send_header("X-KX-Stub", label)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = _reply
        do_POST = _reply
        do_PUT = _reply
        do_PATCH = _reply
        do_DELETE = _reply
        do_HEAD = _reply
        do_OPTIONS = _reply
        do_TRACE = _reply

        def log_message(self, *args):
            pass

    return Stub


@contextmanager
def _stub_server(port: int, label: str):
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(label))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)


def _loopback_config(text: str, port: int, kx_port: int, old_port: int) -> str:
    required = (
        (DOMAIN + " {", "http://127.0.0.1:" + str(port) + " {"),
        ("reverse_proxy 127.0.0.1:9444", "reverse_proxy 127.0.0.1:" + str(kx_port)),
        ("reverse_proxy 127.0.0.1:8000", "reverse_proxy 127.0.0.1:" + str(old_port)),
    )
    for before, _after in required:
        if text.count(before) != 1:
            raise ValueError("Caddyfile candidato con estructura inesperada")
    for marker in (
        "NO INSTALAR",
        "handle @kx_contract",
        "handle @legacy_websockets",
        "handle @legacy_upgrade",
        "header Upgrade *",
        "handle @legacy_write",
        "handle @legacy_read",
        'respond "Escrituras legacy cerradas durante K-X" 503',
        'respond "WebSocket legacy cerrado durante K-X" 403',
        'respond "Upgrade legacy cerrado durante K-X" 403',
    ):
        if marker not in text:
            raise ValueError("Falta control de seguridad de ruta K-X")
    out = text
    for old, new in required:
        out = out.replace(old, new)
    # Desactivar admin API y auto-TLS del Caddy de PRUEBA.
    return "{\n    admin off\n    auto_https off\n}\n\n" + out


def _test_routing(port: int) -> int:
    # La columna final es el stub que DEBE recibir la petición.
    tests = (
        ("GET", "/docs", 200, "legacy", None),
        ("HEAD", "/openapi.json", 200, "legacy", None),
        ("OPTIONS", "/vehiculos/1", 200, "legacy", None),
        ("POST", "/vehiculos/1/movimientos", 503, "", None),
        ("POST", "/vehiculos/1/demos/1/ejecutar", 503, "", None),
        ("DELETE", "/publico/vehiculos/1/sesion", 503, "", None),
        ("POST", "/publico/vehiculos/1/sesion/acciones", 503, "", None),
        ("GET", "/ws/vehiculos/1", 403, "", None),
        ("GET", "/ws/dispositivos-lab/1/contrato", 403, "", None),
        ("GET", "/ws/vehiculos/1", 403, "", {"Connection": "Upgrade", "Upgrade": "websocket"}),
        # Incluso una ruta que NO empieza por /ws/ NO debe poder pasar
        # un Upgrade a FastAPI legacy.
        ("GET", "/vehiculos/1", 403, "", {"Connection": "Upgrade", "Upgrade": "websocket"}),
        ("GET", "/ws%2Fvehiculos%2F1", 403, "", {"Connection": "Upgrade", "Upgrade": "websocket"}),
        ("GET", WSS, 200, "kx", None),
        ("GET", WSS, 200, "kx", {"Connection": "Upgrade", "Upgrade": "websocket"}),
        ("POST", GUEST, 200, "kx", None),
        ("GET", GUEST + "/estado", 200, "kx", None),
        ("POST", GUEST + "/verificar-accion", 200, "kx", None),
        ("GET", ADMIN, 200, "kx", None),
        ("POST", ADMIN + "/revocar", 200, "kx", None),
        ("TRACE", "/docs", 405, "", None),
    )
    for number, (method, path, status, marker, headers) in enumerate(tests, 1):
        actual_status, actual_marker = _request(port, method, path, headers)
        if actual_status != status or actual_marker != marker:
            raise AssertionError(
                f"Prueba {number} fallo: HTTP {actual_status}, "
                f"upstream={'NOMBRE_FICTICIO' if actual_marker else 'NINGUNO'}, "
                f"esperado HTTP {status}. Ruta {path}"
            )
    return len(tests)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Caddy K-X local, 0 escrituras reales")
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        if not all(x.is_file() for x in (options.caddy, options.candidate, options.active)):
            raise ValueError("Falta Caddy, la propuesta o el Caddyfile activo")
        if options.caddy.is_symlink() or options.candidate.is_symlink() or options.active.is_symlink():
            raise ValueError("Archivos de enlace no permitidos")
        if options.candidate.name != "Caddyfile.kx_diagnostic_NOT_DEPLOY":
            raise ValueError("Solo se acepta el candidato aislado NO DESPLEGADO")
        # Comparar antes/después, nunca escribir al archivo activo.
        active_before = sha256(options.active.read_bytes()).hexdigest()
        candidate_text = options.candidate.read_text(encoding="utf-8-sig")
        with tempfile.TemporaryDirectory(prefix="kx-loopback-") as tmp:
            temp = Path(tmp)
            ports = set()
            while len(ports) < 3:
                ports.add(_free_local_port())
            public, kx_port, legacy_port = sorted(ports)
            cfg = temp / "Caddyfile.loopback_TEST_ONLY"
            cfg.write_text(
                _loopback_config(candidate_text, public, kx_port, legacy_port),
                encoding="utf-8",
            )
            if re.search(
                r"127\\.0\\.0\\.1:(?:443|8000|9444)(?!\\d)",
                cfg.read_text(encoding="utf-8"),
            ):
                raise RuntimeError("Puerto real encontrado en ensayo aislado")
            validate = subprocess.run(
                [str(options.caddy), "validate", "--config", str(cfg), "--adapter", "caddyfile"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12,
            )
            if validate.returncode != 0:
                raise RuntimeError("Caddy no pudo validar el ensayo local")
            with ExitStack() as stack:
                stack.enter_context(_stub_server(kx_port, "kx"))
                stack.enter_context(_stub_server(legacy_port, "legacy"))
                process = subprocess.Popen(
                    [str(options.caddy), "run", "--config", str(cfg), "--adapter", "caddyfile"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    for attempt in range(70):
                        if process.poll() is not None:
                            raise RuntimeError("Caddy de prueba no inicio")
                        try:
                            if _request(public, "GET", "/docs") == (200, "legacy"):
                                break
                        except (OSError, http.client.HTTPException):
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Caddy de prueba no disponible")
                    count = _test_routing(public)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
        if sha256(options.active.read_bytes()).hexdigest() != active_before:
            raise RuntimeError("Caddyfile activo ha cambiado; NO-GO")
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError,
            http.client.HTTPException) as error:
        # Los detalles NO contienen secretos de sesión, pero no imprimir paths.
        print("NO-GO:", type(error).__name__, str(error)[:350])
        return 2
    print("=== K-X CADDY LOOPBACK AISLADO ===")
    print("PRUEBAS DE ENRUTAMIENTO:", count, "APROBADAS")
    print("K-X FICTICIO: SOLO LOOPBACK")
    print("LEGACY FICTICIO: SOLO LOOPBACK")
    print("CADDY DE PRUEBA: TERMINADO")
    print("PUERTOS REALES 443 / 8000 / 9444: SIN CAMBIOS")
    print("CADDYFILE ACTIVO: INTACTO")
    print("AWS/RDS/ESP: SIN TRAFICO NI CAMBIOS")
    print("WSS REAL: NO PROBADO; SOLO ENRUTAMIENTO HTTP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
