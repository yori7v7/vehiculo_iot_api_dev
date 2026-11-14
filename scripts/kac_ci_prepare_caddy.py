"""K-AC: derivar SOLO EN CI dos Caddyfiles TLS/loopback.

No modifica los originales de git y nunca usa TLS / IP / secretos reales.
El candidato sigue usando {remote_host}; una conexión de loopback NO
recibe permiso de invitado. La vuelta atrás vuelve a servir solo legacy.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    cand = (root / "deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY").read_text("utf-8")
    orig = (root / "deploy/windows/Caddyfile").read_text("utf-8")
    assert orig.strip() == ("100-30-4-62.nip.io {\n"
                            "    reverse_proxy 127.0.0.1:8000\n}")
    assert cand.count("100-30-4-62.nip.io {") == 1
    assert "header_up X-Admission-Client-IP {remote_host}" in cand
    assert "reverse_proxy 127.0.0.1:9444" in cand
    assert "reverse_proxy 127.0.0.1:8000" in cand
    assert "8.8.8.8" not in cand
    out = Path(args.output).resolve()
    assert out.is_dir() and "kac" in out.name.lower()
    header = "{\n admin off\n auto_https disable_redirects\n}\n\n"

    def transform(source: str) -> str:
        site = "100-30-4-62.nip.io {"
        return header + source.replace(
            site, "https://100-30-4-62.nip.io:9443 {\n"
            "    bind 127.0.0.1\n"
            "    tls /lab/server.crt /lab/server.key", 1
        )

    (out / "candidate.caddy").write_text(transform(cand), encoding="utf-8")
    (out / "rollback.caddy").write_text(transform(orig), encoding="utf-8")
    print("[K-AC] Dos archivos de Caddy efímeros TLS/loopback preparados.")


if __name__ == "__main__":
    main()
