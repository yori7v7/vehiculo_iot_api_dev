"""Contrato: TLS/WSS real local, CA efimera, nunca CA publica o motor."""
import ast
from pathlib import Path

import pytest

from scripts import kx_tls_loopback_preflight as tls


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "deploy/staging/kw/Caddyfile.kx_diagnostic_NOT_DEPLOY"


def test_tls_site_uses_sni_public_but_socket_bind_loopback_only():
    data = PROPOSAL.read_text(encoding="utf-8")
    result = tls.tls_caddy_candidate(
        data, 19443, 18000, Path("C:/Test/TLS/tls.crt"),
        Path("C:/Test/TLS/tls.key")
    )
    assert result.startswith("{\n    admin off\n    auto_https off\n}")
    assert "https://100-30-4-62.nip.io:19443 {\n    bind 127.0.0.1" in result
    assert 'tls "C:/Test/TLS/tls.crt" "C:/Test/TLS/tls.key"' in result
    assert "reverse_proxy 127.0.0.1:9444" in result
    assert "reverse_proxy 127.0.0.1:18000" in result
    assert "reverse_proxy 127.0.0.1:8000" not in result
    assert "bind 0.0.0.0" not in result


@pytest.mark.parametrize("missing", [
    "NO INSTALAR", "handle @kx_contract", "handle @legacy_write",
    "handle @legacy_websockets", "handle @legacy_upgrade",
    "header Upgrade *", "header_up X-Forwarded-Proto https",
    "header_up Host 100-30-4-62.nip.io",
    "reverse_proxy 127.0.0.1:9444",
])
def test_refuses_unsafe_candidate(missing):
    original = PROPOSAL.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError):
        tls.tls_caddy_candidate(
            original.replace(missing, "BROKEN"),
            19443, 18000, Path("C:/Test/TLS/tls.crt"),
            Path("C:/Test/TLS/tls.key"),
        )


def test_ephemeral_ca_is_verifiable_and_deletable(tmp_path):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    import ssl

    ca = tls.create_local_ca(tmp_path)
    server = tmp_path / "local_server.pem"
    key = tmp_path / "local_server_private.pem"
    assert ca.is_file() and server.is_file() and key.is_file()
    root_cert = x509.load_pem_x509_certificate(ca.read_bytes())
    leaf_cert = x509.load_pem_x509_certificate(server.read_bytes())
    alt_names = leaf_cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    assert tls.DOMAIN in alt_names.get_values_for_type(x509.DNSName)
    ctx = ssl.create_default_context(cafile=str(ca))
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert root_cert.subject == leaf_cert.issuer
    assert "PRIVATE KEY" in key.read_text(encoding="ascii")


def test_closed_by_default_without_windows_or_real_key(tmp_path, capsys):
    res = tls.main([
        "--repo", str(tmp_path),
        "--python", str(tmp_path / "python.exe"),
        "--caddy-exe", str(tmp_path / "caddy.exe"),
        "--candidate", str(PROPOSAL),
        "--active", str(tmp_path / "Caddyfile"),
        "--key-path", str(tmp_path / "kx.bin"),
    ])
    assert res == 2
    assert "NO-GO" in capsys.readouterr().out


def test_tls_source_has_no_insecure_ssl_or_open_network_bind():
    src = Path(tls.__file__).read_text(encoding="utf-8")
    ast.parse(src)
    assert "ssl.create_default_context(cafile=str(ca))" in src
    assert "ctx.verify_mode != ssl.CERT_REQUIRED" in src
    assert "ctx.check_hostname" in src
    assert "with context.wrap_socket(raw, server_hostname=DOMAIN)" in src
    assert "wss_challenge(edge, ctx)" in src
    assert "bind 127.0.0.1" in src
    assert "auto_https off" in src
    assert "DEVICE_LAB_ENABLED" in src
    assert "ssl._create_unverified_context" not in src
    assert "ssl.CERT_NONE" not in src
    assert "0.0.0.0:9444" not in src
    assert "GPIO" in src
