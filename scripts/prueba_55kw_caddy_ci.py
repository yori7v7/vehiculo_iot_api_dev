"""K-W: integración TCP/TLS/Caddy -> FastAPI REAL en GitHub Actions.

El navegador NO está simulado en esta fase: se ejercita curl HTTPS real con
la CA efímera verificada. La IP 8.8.8.8 está inyectada SOLO en Caddyfile.ci.
No se consultan API legacy, AWS ni el vehículo. Nunca imprimir secretos.
"""
from __future__ import annotations

import json
import os
import subprocess
from secrets import token_urlsafe


HOST = "100-30-4-62.nip.io"
BASE = "https://" + HOST + ":9443"
GUEST = "/publico/vehiculos/1/solicitudes"
ADMIN = "/admin/vehiculos/1/control-publico/solicitudes"
ORIGIN = "https://yori7v7.github.io"
END = "\n__KW_HTTP_STATUS__"


def request(method, path, headers=(), json_body=None):
    assert path.startswith("/") and "?" not in path
    command = [
        "curl", "--silent", "--show-error", "--http1.1", "--noproxy", "*",
        "--max-time", "7", "--max-redirs", "0",
        "--cacert", os.environ["KW_ROOT_CA"],
        "--resolve", HOST + ":9443:127.0.0.1",
        "-X", method,
    ]
    for value in headers:
        command.extend(["-H", value])
    if json_body is not None:
        command.extend(["-H", "Content-Type: application/json",
                        "--data-binary", json.dumps(json_body)])
    command += ["--write-out", END + "%{http_code}", BASE + path]
    completed = subprocess.run(command, capture_output=True,
                               text=True, timeout=10, check=False)
    if completed.returncode:
        # No exponer stdout ni stderr del curl con datos sensibles.
        raise AssertionError(
            "Fallo transporte HTTPS con CA validada (" + str(completed.returncode) + ")"
        )
    body, sep, code = completed.stdout.rpartition(END)
    assert sep and code.isdigit(), "Respuesta HTTP sin delimitador valido"
    status = int(code)
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    return status, payload


def expect(status, expected, step):
    assert status == expected, step + ": HTTP " + str(status) + " esperado " + str(expected)


def bearer_identity():
    return [
        "Idempotency-Key: " + token_urlsafe(32),
        "X-Browser-Proposal: " + token_urlsafe(32),
    ]


def main():
    assert (os.getenv("GITHUB_ACTIONS") == "true"
            and os.getenv("KW_TEST_LAB") == "isolated-loopback-only")
    admin = os.environ["KW_ADMIN_TEST_KEY"]
    guest = ["Origin: " + ORIGIN]
    owner = guest + ["X-API-Key: " + admin]

    # Cada request cruza TLS validado por la CA, luego Caddy, luego ASGI.
    expect(request("GET", "/")[0], 404, "sin legacy root")
    expect(request("POST", "/vehiculos/1/movimientos")[0], 404, "sin movimiento")
    expect(request("POST", "/vehiculos/1/demos/1/ejecutar")[0], 404, "sin demo")
    expect(request("GET", "/docs")[0], 404, "sin swagger")
    expect(request("GET", "/ws/vehiculos/1")[0], 404, "sin websocket")
    expect(request("POST", "/publico/vehiculos/2/solicitudes", guest)[0],
           404, "otro vehiculo")
    expect(request("GET", ADMIN)[0], 403, "origin obligatorio")
    expect(request("GET", ADMIN, guest)[0], 401, "clave requerida")
    expect(request("GET", ADMIN, guest + ["X-API-Key: fake"])[0],
           403, "clave errónea")

    preflight = guest + [
        "Access-Control-Request-Method: POST",
        "Access-Control-Request-Headers: idempotency-key,x-browser-proposal",
    ]
    expect(request("OPTIONS", GUEST, preflight)[0], 200, "CORS preflight")
    expect(request("OPTIONS", GUEST,
                   ["Origin: https://evil.example",
                    "Access-Control-Request-Method: POST"])[0],
           400, "CORS origen ajeno")
    expect(request("POST", GUEST, guest)[0], 428, "idempotencia requerida")

    idem = bearer_identity()
    first_status, first = request("POST", GUEST, guest + idem)
    expect(first_status, 201, "solicitud inicial")
    assert first["canDrive"] is False
    assert first["simulado"] is True
    assert first["control_fisico"] is False
    assert first["idempotent_replay"] is False
    again_status, again = request("POST", GUEST, guest + idem)
    expect(again_status, 200, "repeticion")
    assert again["request_id"] == first["request_id"]
    assert again["idempotent_replay"] is True

    # El cliente HTTP malicioso falsifica cabeceras de identidad y proxy.
    # Caddy las ELIMINA, luego inyecta las suyas; no las acepta de Internet.
    forged = guest + bearer_identity() + [
        "X-Admission-Proxy-Token: forged-not-authoritative",
        "X-Admission-Client-IP: 9.9.9.9",
        "X-Admission-Scheme: http",
        "X-Forwarded-For: 9.9.9.9",
        "X-Forwarded-Proto: http",
        "X-Real-IP: 9.9.9.9",
    ]
    status, spoof = request("POST", GUEST, forged)
    expect(status, 201, "sanitizacion proxy")
    assert spoof["request_id"] != first["request_id"]
    assert spoof["canDrive"] is False

    queue_status, queue = request("GET", ADMIN, owner)
    expect(queue_status, 200, "inbox admin")
    assert len(queue["solicitudes"]) == 2
    assert queue["canDrive"] is False
    assert first["browser_secret"] not in json.dumps(queue)
    expect(request("POST", ADMIN + "/supervision", owner)[0],
           200, "supervision")
    status, approved = request("POST", ADMIN + "/" + first["request_id"]
                               + "/aprobar", owner,
                               {"modo": "timed", "segundos": 60})
    expect(status, 200, "aprobacion virtual")
    assert approved["canDrive"] is False
    session = guest + ["X-Browser-Session: " + first["browser_secret"]]
    status, current = request("GET", GUEST + "/estado", session)
    expect(status, 200, "estado visitante")
    assert current["estado"] == "autorizado"
    assert current["canDrive"] is False

    status, revoked = request("POST", ADMIN + "/revocar", owner)
    expect(status, 200, "revocacion")
    assert revoked["stop_fisico_confirmado"] is False
    assert revoked["canDrive"] is False
    status, ended = request("GET", GUEST + "/estado", session)
    expect(status, 200, "estado revocado")
    assert ended["estado"] == "revocado_o_caducado"
    assert ended["canDrive"] is False

    print("[K-W] Caddy TLS/CA + FastAPI real: 21 comprobaciones OK, SOLO VIRTUAL")
    print("[K-W] Sin rutas de movimiento/DEMO/WSS ni AWS. No demuestra STOP físico.")


if __name__ == "__main__":
    main()
