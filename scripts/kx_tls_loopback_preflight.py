"""K-X: HTTPS/WSS autenticando CA EFIMERA por Caddy REAL y FastAPI REAL.

Solo EC2 Windows; abre exclusivamente sockets 127.0.0.1 en puertos
descartables y un K-X temporal en 9444. NO modifica el Caddy activo, ni
tareas, ni RDS, ni firmware. WSS solo desafio; no autentica ESP ni GPIO.
La CA y clave TLS nacen en directorio temporal, fuera del repositorio,
y se eliminan DESPUES de cerrar ambos procesos hijos.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import base64

DOMAIN = "100-30-4-62.nip.io"
ORIGIN = "https://yori7v7.github.io"
HOST = "127.0.0.1"
GUEST = "/publico/vehiculos/1/solicitudes"
WSS_PATH = "/ws/kx-diagnostico/1"
PORT = 9444
EXPECTED = "AABB6EFF0F31B6171DA1795FE69C6DA62015A3B0AD61452494AD57F917A7D839"


def free_port(excluded: set[int]) -> int:
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((HOST, 0))
            p = int(sock.getsockname()[1])
            if p >= 1024 and p not in excluded:
                return p
    raise RuntimeError("No hay puerto efimero disponible")


def exact(sock: socket.socket, amount: int) -> bytes:
    data = b""
    while len(data) < amount:
        part = sock.recv(amount - len(data))
        if not part:
            raise RuntimeError("Socket cerrado antes de completar el desafio")
        data += part
    return data


def http_request(port: int, method: str, path: str) -> int:
    con = http.client.HTTPConnection(HOST, port, timeout=3)
    try:
        con.request(method, path)
        response = con.getresponse()
        response.read()
        return response.status
    finally:
        con.close()


@contextmanager
def legacy_stub(port: int):
    class Stub(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"legacy-stub-sin-API"
            self.send_response(200)
            self.send_header("X-KX-Stub", "legacy")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer((HOST, port), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)


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


def create_local_ca(directory: Path) -> Path:
    """Emitir CA y certificado de servidor por UNA ejecución, nunca persistir."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    now = datetime.now(timezone.utc)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "K-X Local Preflight Ephemeral CA")
    ])
    root_cert = (
        x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
        .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=8))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        # OpenSSL 3.5 / Python 3.14 VERIFY_X509_STRICT exige extensiones
        # RFC 5280 completas, no basta con CA+BasicConstraints.
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(digital_signature=False, content_commitment=False,
                          key_encipherment=False, data_encipherment=False,
                          key_agreement=False, key_cert_sign=True, crl_sign=True,
                          encipher_only=False, decipher_only=False), critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, DOMAIN)
    ])
    leaf_cert = (
        x509.CertificateBuilder().subject_name(leaf_name).issuer_name(root_name)
        .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=4))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(DOMAIN)]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False,
                          key_encipherment=True, data_encipherment=False,
                          key_agreement=False, key_cert_sign=False, crl_sign=False,
                          encipher_only=False, decipher_only=False), critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )
    ca = directory / "local_ca.pem"
    crt = directory / "local_server.pem"
    key = directory / "local_server_private.pem"
    ca.write_bytes(root_cert.public_bytes(serialization.Encoding.PEM))
    crt.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(leaf_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    return ca


def tls_caddy_candidate(text: str, port: int, fake_legacy_port: int,
                        cert: Path, key: Path) -> str:
    site = DOMAIN + " {"
    if (text.count(site) != 1
            or text.count("reverse_proxy 127.0.0.1:9444") != 1
            or text.count("reverse_proxy 127.0.0.1:8000") != 1):
        raise RuntimeError("Caddyfile candidato inesperado")
    for item in (
        "NO INSTALAR", "handle @kx_contract", "handle @legacy_websockets",
        "handle @legacy_upgrade", "handle @legacy_write",
        "header Upgrade *", "header_up Host " + DOMAIN,
        "header_up X-Forwarded-Proto https",
        'respond "Escrituras legacy cerradas durante K-X" 503',
    ):
        if item not in text:
            raise RuntimeError("Falta medida de seguridad de la ruta")
    if any('\n' in str(p) or '"' in str(p) for p in (cert, key)):
        raise RuntimeError("Ruta de certificado inesperada")
    # TLS con host real (SNI), pero bind exclusivamente a IPv4 LOOPBACK.
    site_header = (f"https://{DOMAIN}:{port} {{\n"
                   "    bind 127.0.0.1\n"
                   f'    tls "{cert.as_posix()}" "{key.as_posix()}"')
    updated = text.replace(site, site_header)
    updated = updated.replace("reverse_proxy 127.0.0.1:8000",
                              f"reverse_proxy 127.0.0.1:{fake_legacy_port}")
    for line in updated.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if ("reverse_proxy 127.0.0.1:8000" in stripped
                or "bind 0.0.0.0" in stripped
                or "reverse_proxy 0.0.0.0" in stripped):
            raise RuntimeError("Directiva de red no aislada")
    return "{\n    admin off\n    auto_https off\n}\n\n" + updated


def https_request(port: int, context: ssl.SSLContext, method: str,
                  path: str, headers: dict | None = None):
    # No resolver DNS: conectar a 127.0.0.1, pero verificar certificado
    # usando SNI de DOMAIN, con cadena CA en SSLContext y check_hostname.
    con = socket.create_connection((HOST, port), timeout=4)
    stream = None
    try:
        stream = context.wrap_socket(con, server_hostname=DOMAIN)
        stream.settimeout(4)
        host_headers = {"Host": DOMAIN}
        host_headers.update(headers or {})
        connection = http.client.HTTPConnection(DOMAIN, port, timeout=4)
        connection.sock = stream
        connection.request(method, path, headers=host_headers)
        reply = connection.getresponse()
        body = reply.read(4096)
        return reply.status, body, reply.getheader("X-KX-Stub")
    finally:
        if stream is not None:
            stream.close()
        else:
            con.close()


def wss_challenge(port: int, context: ssl.SSLContext) -> None:
    raw = socket.create_connection((HOST, port), timeout=4)
    with context.wrap_socket(raw, server_hostname=DOMAIN) as ws:
        ws.settimeout(4)
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        req = (
            f"GET {WSS_PATH} HTTP/1.1\r\n"
            f"Host: {DOMAIN}\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: websocket\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        ws.sendall(req.encode("ascii"))
        hdr = b""
        while not hdr.endswith(b"\r\n\r\n"):
            hdr += exact(ws, 1)
            if len(hdr) > 8192:
                raise RuntimeError("Respuesta WSS demasiado larga")
        if not hdr.startswith(b"HTTP/1.1 101 "):
            raise RuntimeError("WSS no devolvio HTTP 101")
        initial = exact(ws, 2)
        if (initial[0] & 0x0F) != 1 or (initial[1] & 0x80):
            raise RuntimeError("Desafio WSS invalido")
        size = initial[1] & 0x7F
        if size == 126:
            size = int.from_bytes(exact(ws, 2), "big")
        elif size == 127:
            raise RuntimeError("Marco WSS demasiado grande")
        if size > 512:
            raise RuntimeError("Desafio WSS fuera de contrato")
        payload = json.loads(exact(ws, size))
        if payload.get("tipo") != "desafio_dispositivo_lab" or payload.get("simulado") is not True:
            raise RuntimeError("Desafio virtual no confirmado")
        # Desconectar sin responder al desafio: nunca se autentica el ESP.


def port_is_free(p: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, p))


def cleanup(path: Path) -> None:
    for attempt in range(25):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="K-X TLS/WSS test, Windows localhost ONLY")
    for name in ("repo", "python", "caddy-exe", "candidate", "active", "key-path"):
        parser.add_argument("--" + name, required=True, type=Path)
    opts = parser.parse_args(argv)
    kx = None
    caddy = None
    temporary = None
    previous_caddy_hash = None
    problem = None
    phase = "preflight"
    edge = None
    try:
        if sys.platform != "win32":
            raise RuntimeError("Solo EC2 Windows")
        repo = opts.repo.resolve(strict=True)
        python = opts.python.resolve(strict=True)
        if python != (repo / ".venv" / "Scripts" / "python.exe").resolve(strict=True):
            raise RuntimeError("Entorno Python no aislado")
        if not all(p.is_file() and not p.is_symlink()
                   for p in (opts.caddy_exe, opts.candidate, opts.active, opts.key_path)):
            raise RuntimeError("Falta un archivo seguro")
        if opts.candidate.name != "Caddyfile.kx_diagnostic_NOT_DEPLOY":
            raise RuntimeError("Candidato Caddy no aceptado")
        if (repo / ".env").exists():
            raise RuntimeError("El codigo experimental contiene .env")
        hmac_key = opts.key_path
        if hmac_key.stat().st_size != 32 or hashlib.sha256(hmac_key.read_bytes()).hexdigest().upper() != EXPECTED:
            raise RuntimeError("HMAC del dispositivo no coincide")
        previous_caddy_hash = hashlib.sha256(opts.active.read_bytes()).hexdigest()
        port_is_free(PORT)
        edge = free_port({PORT, 443, 8000, 9444})
        legacy_port = free_port({PORT, edge, 443, 8000, 9444})
        temporary = Path(tempfile.mkdtemp(prefix="kx-tls-wss-"))
        phase = "certificados"
        ca = create_local_ca(temporary)
        server_crt = temporary / "local_server.pem"
        server_key = temporary / "local_server_private.pem"
        ctx = ssl.create_default_context(cafile=str(ca))
        if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
            raise RuntimeError("Validacion de certificado deshabilitada")
        text = opts.candidate.read_text(encoding="utf-8-sig")
        conf = tls_caddy_candidate(text, edge, legacy_port, server_crt, server_key)
        config_file = temporary / "Caddyfile.tls_loopback_NOT_DEPLOY"
        config_file.write_text(conf, encoding="utf-8")
        tested = subprocess.run(
            [str(opts.caddy_exe), "validate", "--config", str(config_file),
             "--adapter", "caddyfile"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12,
        )
        if tested.returncode != 0:
            raise RuntimeError("Caddy TLS local no valido configuracion")
        print("CERTIFICADOS TLS TEMPORALES: GENERADOS")
        print("CADDY TLS: CONFIGURACION VALIDADA")
        with legacy_stub(legacy_port):
            env = os.environ.copy()
            env.update({
                "APP_ENV": "production",
                "API_KEY": secrets.token_urlsafe(48),
                "PUBLIC_VIRTUAL_ADMISSION_ENABLED": "true",
                "PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH": str(temporary / "tickets.sqlite3"),
                "KX_DIAGNOSTIC_WSS_ENABLED": "true",
                "KX_DIAGNOSTIC_WSS_KEY_PATH": str(hmac_key.resolve(strict=True)),
                "CONTROL_PUBLICO_ENABLED": "false",
                "CONTROL_PUBLICO_SIMULATION": "false",
                "DEVICE_LAB_ENABLED": "false",
            })
            phase = "FastAPI"
            kx = subprocess.Popen(
                [str(python), "-m", "uvicorn", "app.main:app",
                 "--host", HOST, "--port", str(PORT), "--workers", "1",
                 "--proxy-headers", "--forwarded-allow-ips", HOST,
                 "--no-access-log", "--log-level", "warning"],
                cwd=str(repo), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for _ in range(100):
                if kx.poll() is not None:
                    raise RuntimeError("FastAPI salio antes del preflight")
                try:
                    if http_request(PORT, "GET", "/docs") == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("FastAPI no respondio")
            print("FASTAPI K-X REAL: LOOPBACK 9444")
            phase = "Caddy TLS"
            caddy = subprocess.Popen(
                [str(opts.caddy_exe), "run", "--config", str(config_file),
                 "--adapter", "caddyfile"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Diagnostico acotado: nunca imprimir cuerpos, cabeceras,
            # rutas de certificados, llaves o excepciones de Caddy.
            last_http_status = None
            stub_confirmed = False
            last_network_error = "NINGUNO"
            tls_verify_code = None
            tls_reason = "NINGUNA"
            for _ in range(100):
                if caddy.poll() is not None:
                    print("DIAG CADDY: PROCESO_TERMINADO")
                    print("DIAG CADDY EXIT:", caddy.returncode)
                    raise RuntimeError("Caddy TLS termino prematuramente")
                try:
                    status, _body, stub = https_request(edge, ctx, "GET", "/docs")
                    last_http_status = status
                    stub_confirmed = (stub == "legacy")
                    if status == 200 and stub_confirmed:
                        break
                except ssl.SSLCertVerificationError as exc:
                    last_network_error = "CERTIFICADO_NO_VALIDADO"
                    tls_verify_code = exc.verify_code
                except ssl.SSLError as exc:
                    last_network_error = "ERROR_TLS"
                    reason = getattr(exc, "reason", None)
                    if isinstance(reason, str) and reason.isidentifier() and len(reason) <= 64:
                        tls_reason = reason
                except (OSError, http.client.HTTPException) as exc:
                    last_network_error = type(exc).__name__
                time.sleep(0.1)
            else:
                print("DIAG CADDY: SIN_RESPUESTA_ESPERADA")
                print("DIAG PROCESO_CADDY_ACTIVO:", caddy.poll() is None)
                print("DIAG HTTP_STATUS:", last_http_status if last_http_status is not None else "NINGUNO")
                print("DIAG STUB_LEGACY:", stub_confirmed)
                print("DIAG TRANSPORTE:", last_network_error)
                print("DIAG TLS_REASON:", tls_reason)
                if tls_verify_code is not None:
                    print("DIAG TLS_VERIFY_CODE:", tls_verify_code)
                raise RuntimeError("Caddy TLS no respondio al sitio localhost")
            print("HTTPS CADDY > LEGACY FICTICIO: CA VALIDADA")
            phase = "contratos HTTPS/WSS"
            # Sin CA se debe RECHAZAR el certificado efimero.
            untrusted = ssl.create_default_context()
            try:
                https_request(edge, untrusted, "GET", "/docs")
            except ssl.SSLCertVerificationError:
                print("TLS SIN CA DE PRUEBA: RECHAZADO")
            else:
                raise RuntimeError("TLS sin confianza aceptado")
            if https_request(edge, ctx, "POST", "/vehiculos/1/movimientos")[0] != 503:
                raise RuntimeError("Escritura legacy no bloqueada por HTTPS")
            print("ESCRITURA LEGACY HTTPS: HTTP 503")
            if https_request(edge, ctx, "GET", "/ws/vehiculos/1")[0] != 403:
                raise RuntimeError("WebSocket legacy HTTPS no bloqueado")
            print("WEB SOCKET LEGACY HTTPS: HTTP 403")
            if https_request(edge, ctx, "GET", GUEST + "/estado", {"Origin": ORIGIN})[0] != 401:
                raise RuntimeError("K-X no interpreto esquema HTTPS")
            print("K-X HTTPS: RECONOCIDO")
            status, body, _ = https_request(
                edge, ctx, "POST", GUEST, {
                    "Origin": ORIGIN,
                    "Idempotency-Key": secrets.token_urlsafe(32),
                    "X-Browser-Proposal": secrets.token_urlsafe(32),
                }
            )
            data = json.loads(body)
            if (status != 201 or data.get("canDrive") is not False
                    or data.get("simulado") is not True
                    or data.get("control_fisico") is not False):
                raise RuntimeError("Solicitud invitado HTTPS invalida")
            print("SOLICITUD INVITADO HTTPS: HTTP 201, canDrive=false")
            wss_challenge(edge, ctx)
            print("WSS TLS REAL: HTTP 101, DESAFIO VIRTUAL RECIBIDO")
            print("ESP AUTENTICADO: NO")
            print("ORDENES/GPIO: NINGUNA")
    except Exception as error:
        problem = (phase, type(error).__name__)
    finally:
        try:
            close_child(caddy)
            close_child(kx)
            print("CADDY Y FASTAPI TEMPORALES: CERRADOS")
        except Exception:
            problem = ("cierre", "ProcesoNoCerro")
        if temporary is not None and (kx is None or kx.poll() is not None):
            try:
                cleanup(temporary)
                print("CERTIFICADOS Y SQLITE TEMPORALES: ELIMINADOS")
            except Exception:
                problem = ("limpieza", "TemporalBloqueado")
        else:
            problem = ("limpieza", "ProcesoRetieneArchivos")
        if previous_caddy_hash is not None:
            try:
                if hashlib.sha256(opts.active.read_bytes()).hexdigest() != previous_caddy_hash:
                    problem = ("Caddyfile activo", "CambioDetectado")
            except Exception:
                problem = ("Caddyfile activo", "NoVerificable")
        try:
            port_is_free(PORT)
            print("PUERTO 9444: LIBRE")
        except OSError:
            problem = ("puerto 9444", "Ocupado")
    if problem:
        print("NO-GO:", *problem, "| sin despliegue")
        return 2
    print("CADDYFILE REAL Y BACKEND ANTIGUO: SIN CAMBIOS")
    print("TLS PUBLICO INTERNET: NO PROBADO")
    print("=== K-X HTTPS/WSS LOOPBACK APROBADO ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
