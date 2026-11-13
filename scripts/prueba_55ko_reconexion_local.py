"""5.5-K-O: prueba LOCAL de fallo cerrado tras perder WSS (solo GET).

El operador desconecta y reconecta el USB del ESP (bateria desconectada,
firmware diagnostico y PC817 inhibidos) usando indicaciones manuales.
Sin AWS, RDS, router, POST, motores ni permisos concedidos.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import ssl
import sys
from pathlib import Path
from time import monotonic, sleep

KK = Path.home() / "Downloads" / "prueba_55kk_post_virtual_seguro.py"
if not KK.is_file():
    raise SystemExit("[K-O] Falta utilidad K-K validada en Descargas.")
sys.path.insert(0, str(KK.parent))
from prueba_55kk_post_virtual_seguro import (
    CheckedClient,
    TestStopped,
    certificate_file,
    local_ipv4,
    verify_diagnostic_template,
)

ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGIN = "https://yori7v7.github.io"


def read(client, headers):
    code, body = client.call("GET", ADMIN, headers=headers)
    if not isinstance(body, dict):
        raise TestStopped("Respuesta admin no JSON")
    return code, body


def safe_virtual(body):
    return (body.get("simulado") is True
            and body.get("control_fisico") is False)


def expect_closed(client, headers, *, seconds=15):
    deadline = monotonic() + seconds
    seen = []
    while monotonic() < deadline:
        status, body = read(client, headers)
        seen.append(status)
        if status == 503:
            return True, seen
        if status not in (200, 503):
            raise TestStopped(f"HTTP inesperado tras perder ESP: {status}")
        sleep(0.5)
    return False, seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.82")
    parser.add_argument("--puerto", type=int, default=8443)
    parser.add_argument("--diagnostico-confirmado", action="store_true")
    args = parser.parse_args()
    try:
        if not args.diagnostico_confirmado:
            raise TestStopped("Debes verificar firmware DIAGNOSTICO, GPIO inhibidos y bateria fuera")
        address = ipaddress.ip_address(args.ip)
        if address.version != 4 or args.ip not in local_ipv4() or args.puerto != 8443:
            raise TestStopped("Solo el servidor 8443 de ESTA laptop")
        verify_diagnostic_template()
        cert = certificate_file(None)
        public_pem = cert.read_text(encoding="ascii")
        if "-----BEGIN CERTIFICATE-----" not in public_pem or "PRIVATE KEY" in public_pem:
            raise TestStopped("Certificado incorrecto: usar solo CA publica")
        client = CheckedClient(args.ip, args.puerto, cert)
        key = getpass.getpass("X-API-Key del administrador (oculta): ")
        if not key or any(ch in key for ch in "\r\n"):
            raise TestStopped("Clave administrativa vacia/invalida")
        headers = {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site", "X-API-Key": key}

        print("\n[K-O] Fase 1 — ESP WSS autenticado, STOP virtual HMAC en Terminal 1.")
        code, body = read(client, headers)
        if code != 200 or not safe_virtual(body) or body.get("turno_activo") is not False or body.get("solicitudes") != []:
            raise TestStopped(f"Precondicion incumplida: HTTP {code}; debe estar limpio y simulado")
        print("[K-O] 1/3 OK: admin GET 200; sin turno ni pendientes; sin control fisico")

        check = input("\nDesconecta SOLO el USB del ESP (bateria ya desconectada). Escribe DESCONECTADO: ").strip()
        if check != "DESCONECTADO":
            raise TestStopped("Prueba cancelada por operador")
        closed, series = expect_closed(client, headers)
        if not closed:
            raise TestStopped(f"FALLO: K-G no cerro admin despues de desconexion; codigos {series}")
        print("[K-O] 2/3 OK: HTTP 503 tras perder el ESP")

        check = input("\nReconecta USB. Verifica el NUEVO log de autenticacion+STOP en Terminal 1. Escribe AUTENTICADO: ").strip()
        if check != "AUTENTICADO":
            raise TestStopped("Sin evidencia de reautenticacion; resultado parcial 2/3")
        # Reconexion WSS por si sola NO debe reabrir K-K sin otro handover seguro.
        sleep(2)
        statuses = []
        for _ in range(5):
            code, body = read(client, headers)
            statuses.append(code)
            if code != 503:
                raise TestStopped(f"FALLO: puerta admin se reabrio sin handover: {statuses}")
            sleep(0.5)
        print("[K-O] 3/3 OK: reconexion no reabre puertas administrativas")
        print("[K-O] RESULTADO: 3/3 de las barreras HTTP, SOLO laboratorio virtual.")
        print("[K-O] No demuestra STOP mecanico ni arbitraje de movimiento.")
        print("[K-O] Para volver a probar K-L, reiniciar K-G y validar nuevo handover.")
        return 0
    except (TestStopped, OSError, ssl.SSLError, ValueError) as error:
        print("[K-O] PRUEBA DETENIDA:", str(error))
        print("[K-O] No encender motores; revisar en Terminal 1.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
