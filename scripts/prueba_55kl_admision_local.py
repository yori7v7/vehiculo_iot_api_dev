"""5.5-K-L: prueba segura del contrato del invitado en laboratorio K-G.

IMPORTANTE: usa funciones de prueba K-K que el alumno ya ejecuto 19/19.
Mismo PC, mismo certificado publico CA, mismo controlador K-C.
Nunca invoca movimiento/DEMO; las aprobaciones y STOP son VIRTUALES.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import ssl
import sys
import time
from pathlib import Path
from uuid import UUID

# La utilidad K-K ya fue descargada/ejecutada por el usuario en Descargas.
# El script K-L se ejecuta desde el subdirectorio scripts/ del repositorio.
UTILIDAD_KK = Path.home() / "Downloads" / "prueba_55kk_post_virtual_seguro.py"
if not UTILIDAD_KK.is_file():
    raise SystemExit("[55-K-L] Falta prueba_55kk_post_virtual_seguro.py en Descargas.")
sys.path.insert(0, str(UTILIDAD_KK.parent))

from prueba_55kk_post_virtual_seguro import (
    CheckedClient,
    TestStopped,
    local_ipv4,
    certificate_file,
    verify_diagnostic_template,
)

ORIGIN = "https://yori7v7.github.io"
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
HEAD_GUEST = {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}


def virtual(body):
    return isinstance(body, dict) and body.get("simulado") is True and body.get("control_fisico") is False


def safe_admin(body, active, pending):
    serialized = json.dumps(body)
    return (
        virtual(body) and body.get("turno_activo") is active
        and isinstance(body.get("solicitudes"), list)
        and len(body["solicitudes"]) == pending
        and "browser_secret" not in serialized and "guest_token" not in serialized
    )


class Lab:
    def __init__(self, conn, key):
        self.conn = conn
        self.head_admin = {**HEAD_GUEST, "X-API-Key": key}
        self.count = 0
        self.ticket = None
        self.may_be_active = False
        self.done = False

    def check(self, label, method, route, expected, *, headers=None, data=None, validate=None):
        if method not in ("GET", "POST"):
            raise TestStopped("Metodo fuera del contrato de laboratorio")
        self.count += 1
        status, response = self.conn.call(
            method, route, headers=headers if headers is not None else HEAD_GUEST, payload=data
        )
        ok = status == expected and (validate is None or validate(response))
        print(f"{self.count:02d}. {label:<47} {status:>3}/{expected:<3} {'OK' if ok else 'FALLO'}")
        if not ok:
            raise TestStopped(f"{label}: respuesta no coincidente, status {status}")
        return response

    def start(self):
        self.check("Admin limpio al inicio", "GET", ADMIN, 200,
                   headers=self.head_admin, validate=lambda r: safe_admin(r, False, 0))
        time.sleep(2)
        self.check("ESP conectado y cola estable", "GET", ADMIN, 200,
                   headers=self.head_admin, validate=lambda r: safe_admin(r, False, 0))
        self.check("Origen ajeno rechazado", "POST", GUEST, 403,
                   headers={"Origin": "https://invalid.example"})
        self.check("Invitado sin API key (rechazo de clave)", "POST", GUEST, 403,
                   headers={**HEAD_GUEST, "X-API-Key": "INVALIDA"})
        self.check("Consulta sin sesion bloqueada", "GET", GUEST + "/estado", 401)

        ticket = self.check("Invitado pide turno sin contraseña", "POST", GUEST, 201,
                            validate=lambda r: virtual(r)
                            and r.get("estado") == "esperando_autorizacion"
                            and isinstance(r.get("browser_secret"), str)
                            and len(r["browser_secret"]) == 43
                            and isinstance(r.get("display_code"), str)
                            and len(r["display_code"]) == 8)
        try:
            UUID(ticket["request_id"])
        except (KeyError, ValueError, TypeError) as error:
            raise TestStopped("Ticket del invitado sin UUID valido") from error
        self.ticket = ticket
        identity = {"X-Browser-Session": ticket["browser_secret"], **HEAD_GUEST}
        ident = ticket["request_id"]

        self.check("Invitado espera autorizacion", "GET", GUEST + "/estado", 200,
                   headers=identity, validate=lambda r: virtual(r)
                   and r.get("estado") == "esperando_autorizacion"
                   and r.get("display_code") == ticket["display_code"]
                   and "guest_token" not in r)
        self.check("Admin ve EXACTAMENTE ese ticket", "GET", ADMIN, 200,
                   headers=self.head_admin, validate=lambda r: safe_admin(r, False, 1)
                   and r["solicitudes"][0].get("request_id") == ident)
        self.check("Clave incorrecta no inicia supervision", "POST", ADMIN + "/supervision", 403,
                   headers={**HEAD_GUEST, "X-API-Key": "INVALIDA"})
        self.check("Supervisor habilita pulso", "POST", ADMIN + "/supervision", 200,
                   headers=self.head_admin, validate=lambda r: virtual(r)
                   and r.get("supervision") is True and r.get("vigencia_s") == 15)

        self.may_be_active = True  # fail closed even if approval later times out
        self.check("Admin concede 120 s virtuales", "POST", ADMIN + f"/{ident}/aprobar", 200,
                   headers=self.head_admin, data={"modo": "timed", "segundos": 120},
                   validate=lambda r: virtual(r) and r.get("aprobada") is True)
        self.check("Visitante autorizado (solo VIRTUAL)", "GET", GUEST + "/estado", 200,
                   headers=identity, validate=lambda r: virtual(r)
                   and r.get("estado") == "autorizado" and "guest_token" not in r)
        self.check("Admin ve turno activo", "GET", ADMIN, 200,
                   headers=self.head_admin, validate=lambda r: safe_admin(r, True, 0))
        self.check("Admin revoca y confirma STOP virtual", "POST", ADMIN + "/revocar", 200,
                   headers=self.head_admin, validate=lambda r: virtual(r) and r.get("revocado") is True)
        self.may_be_active = False
        self.check("Invitado reconoce revocacion", "GET", GUEST + "/estado", 200,
                   headers=identity, validate=lambda r: virtual(r)
                   and r.get("estado") == "revocado_o_caducado" and "guest_token" not in r)
        self.check("Admin sin turnos ni pendientes", "GET", ADMIN, 200,
                   headers=self.head_admin, validate=lambda r: safe_admin(r, False, 0))
        self.done = True
        print(f"\n[55-K-L] RESULTADO: {self.count}/{self.count} correcto en laboratorio local.")
        print("[55-K-L] Ningun movimiento, nunca control fisico; NO publicar en Internet.")

    def cleanup(self):
        if self.may_be_active:
            try:
                status, response = self.conn.call("POST", ADMIN + "/revocar", self.head_admin)
                print("[55-K-L] Revocacion de contingencia:",
                      "CONFIRMADA (VIRTUAL)" if status == 200 and virtual(response)
                      and response.get("revocado") is True else "NO CONFIRMADA")
            except (OSError, ssl.SSLError):
                print("[55-K-L] Revocacion virtual NO CONFIRMADA")
        if self.ticket:
            try:
                self.conn.call("POST", ADMIN + f"/{self.ticket['request_id']}/rechazar",
                               self.head_admin)
            except (OSError, ssl.SSLError):
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.82")
    parser.add_argument("--puerto", type=int, default=8443)
    parser.add_argument("--confirmar-simulacion", action="store_true")
    args = parser.parse_args()
    runner = None
    try:
        if not args.confirmar_simulacion:
            raise TestStopped("Falta confirmar modo diagnostico y bateria desconectada")
        ip = ipaddress.ip_address(args.ip)
        if ip.version != 4 or args.ip not in local_ipv4() or args.puerto != 8443:
            raise TestStopped("Solo el puerto 8443 de la propia laptop")
        verify_diagnostic_template()
        cert = certificate_file(None)
        pem = cert.read_text(encoding="ascii")
        if "-----BEGIN CERTIFICATE-----" not in pem or "PRIVATE KEY" in pem:
            raise TestStopped("No se encontro certificado publico valido")
        print("[55-K-L] Bateria desconectada; GPIO inhibidos; AWS/RDS apagados.")
        conn = CheckedClient(args.ip, args.puerto, cert)
        key = getpass.getpass("X-API-Key del ADMIN (oculta): ")
        if not key.strip() or "\r" in key or "\n" in key:
            raise TestStopped("API key incorrecta o vacia")
        runner = Lab(conn, key)
        runner.start()
        return 0
    except (TestStopped, OSError, ssl.SSLError, ValueError) as error:
        print("[55-K-L] PRUEBA INTERRUMPIDA:", str(error))
        return 1
    finally:
        if runner is not None and not runner.done:
            runner.cleanup()


if __name__ == "__main__":
    sys.exit(main())
