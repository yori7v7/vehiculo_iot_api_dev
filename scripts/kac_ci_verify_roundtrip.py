"""K-AC: verificar coexistencia HTTPS y vuelta atrás en runner efímero.

No consulta DNS externo: curl --resolve fuerza 127.0.0.1. La IP del
cliente es loopback y por tanto la admisión privada DEBE responder 403.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


HOST = "100-30-4-62.nip.io"
HTTPS = "https://" + HOST + ":9443"
LEGACY = "/__kac_legacy_probe"
VIRTUAL = "/publico/vehiculos/1/solicitudes/estado"


def get(path: str, *, origin: bool = False, spoof_proxy: bool = False):
    assert path.startswith("/") and "?" not in path
    args = [
        "curl", "--silent", "--show-error", "--http1.1",
        "--noproxy", "*", "--max-redirs", "0", "--max-time", "5",
        "--cacert", os.environ["KAC_ROOT_CA"],
        "--resolve", HOST + ":9443:127.0.0.1",
    ]
    if origin:
        args += ["-H", "Origin: https://yori7v7.github.io"]
    if spoof_proxy:
        # Solicitud a Caddy con cabeceras falsas. Debe sobrescribirlas
        # con IP real de loopback; la admisión permanece 403.
        args += [
            "-H", "X-Admission-Proxy-Token: cliente-no-confiable",
            "-H", "X-Admission-Client-IP: 8.8.8.8",
            "-H", "X-Admission-Scheme: https",
            "-H", "X-Forwarded-For: 8.8.8.8",
        ]
    args += ["--write-out", "\n__KAC_STATUS__%{http_code}", HTTPS + path]
    p = subprocess.run(args, text=True, capture_output=True, timeout=7)
    if p.returncode:
        raise AssertionError("HTTPS con CA verificada falló: " + str(p.returncode))
    body, sep, status = p.stdout.rpartition("\n__KAC_STATUS__")
    assert sep and status.isdecimal()
    return int(status), body


def check_legacy():
    status, body = get(LEGACY)
    assert status == 200, "Legacy no responde en HTTPS: " + str(status)
    response = json.loads(body)
    assert response["legacy"] is True and response["control_fisico"] is False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["candidate", "sidecar_off", "rollback"])
    phase = p.parse_args().phase
    assert os.getenv("GITHUB_ACTIONS") == "true"
    assert Path(os.environ["KAC_ROOT_CA"]).is_file()
    check_legacy()
    if phase == "candidate":
        status, _ = get(VIRTUAL, origin=True)
        assert status == 403, (
            "La IP loopback no debe autorizar tickets; resultado " + str(status)
        )
        spoofed_status, _ = get(VIRTUAL, origin=True, spoof_proxy=True)
        assert spoofed_status == 403, (
            "El proxy aceptó identidad falsa; status " + str(spoofed_status)
        )
        assert get("/vehiculos/1/movimientos")[0] == 404
        print("[K-AC] Candidato TLS: legacy 200, virtual 403, spoofing rechazado, sin motores.")
    elif phase == "sidecar_off":
        status, _ = get(VIRTUAL, origin=True)
        assert status == 502, (
            "Sin sidecar el virtual debe fallar cerrado en proxy; recibió "
            + str(status)
        )
        print("[K-AC] Sidecar detenido: virtual 502, legacy continúa 200.")
    else:
        assert get(VIRTUAL, origin=True)[0] == 404, (
            "Tras rollback la ruta virtual debe volver al legacy dummy 404"
        )
        print("[K-AC] Rollback CI: Caddy original sin admisión, legacy HTTPS 200.")


if __name__ == "__main__":
    main()
