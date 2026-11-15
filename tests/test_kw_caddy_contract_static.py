"""K-W: contrato de Caddy FUTURO no modificable por accidente.

No abre puertos ni ejecuta Docker; son comprobaciones estaticas de diseño.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "deploy/windows/Caddyfile"
CANDIDATE = ROOT / "deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY"
ISOLATED = ROOT / "deploy/staging/kw/Caddyfile.ci"
MAIN = ROOT / "app/main.py"


def directives(contents):
    return [line.strip() for line in contents.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_kw_main_caddyfile_not_replaced_by_ci():
    current = directives(WINDOWS.read_text("utf-8"))
    assert current == [
        "100-30-4-62.nip.io {",
        "reverse_proxy 127.0.0.1:8000",
        "}",
    ]


def test_kw_candidate_preserves_legacy_and_isolates_virtual_admission():
    data = directives(CANDIDATE.read_text("utf-8"))
    assert data[0] == "100-30-4-62.nip.io {"
    assert "@kv_virtual_admission {" in data
    assert "handle @kv_virtual_admission {" in data
    assert "handle {" in data
    assert data.index("handle @kv_virtual_admission {") < data.index("handle {")
    assert "reverse_proxy 127.0.0.1:9444 {" in data
    assert "reverse_proxy 127.0.0.1:8000" in data
    assert "header_up X-Admission-Client-IP {remote_host}" in data
    assert "header_up X-Admission-Scheme https" in data
    assert "header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}" in data
    assert "header_up Host 100-30-4-62.nip.io" in data
    for spoofed in (
        "forwarded", "x-forwarded-for", "x-forwarded-host",
        "x-forwarded-proto", "x-real-ip", "cookie",
        "authorization", "proxy-authorization",
    ):
        assert "header_up -" + spoofed.lower() in [line.lower() for line in data]
    # NO usar la identidad artificial 8.8.8.8 en ningun candidato real.
    assert "8.8.8.8" not in CANDIDATE.read_text("utf-8")
    assert not any(line.startswith("header_up -X-Admission") for line in data)
    assert not any("header_up +X-Admission" in line for line in data)
    assert not any("reverse_proxy 0.0.0.0" in line for line in data)


def test_kw_ci_laboratory_explicitly_uses_fake_ip_and_no_legacy():
    data = directives(ISOLATED.read_text("utf-8"))
    assert "bind 127.0.0.1" in data
    assert "header_up X-Admission-Client-IP 8.8.8.8" in data
    assert "header_up X-Admission-Proxy-Token {$KW_PROXY_TEST_KEY}" in data
    assert "reverse_proxy 127.0.0.1:8000" not in data
    assert "respond \"Not Found\" 404" in data
    assert not any(line.startswith("header_up -X-Admission") for line in data)


def test_kw_virtual_cannot_be_imported_by_legacy_runtime():
    source = MAIN.read_text("utf-8")
    assert "kv_virtual_staging" not in source
    assert "servidor_55kw_ci" not in source
