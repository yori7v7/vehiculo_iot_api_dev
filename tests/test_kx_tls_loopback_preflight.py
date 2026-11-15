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


def test_http_startup_probe_consumes_integer_status_from_actual_local_stub():
    """Regresion WinError NO-GO TypeError: 200[0] nunca es valido."""
    port = tls.free_port({443, 8000, 9444})
    with tls.legacy_stub(port):
        code = tls.http_request(port, "GET", "/docs")
        assert type(code) is int
        assert code == 200
    source = Path(tls.__file__).read_text(encoding="utf-8")
    assert 'if http_request(PORT, "GET", "/docs") == 200:' in source
    assert 'http_request(PORT, "GET", "/docs")[0]' not in source


def test_tls_readiness_diagnostics_are_bounded_and_never_log_secrets():
    source = Path(tls.__file__).read_text(encoding="utf-8")
    ast.parse(source)
    for marker in (
        "DIAG CADDY: SIN_RESPUESTA_ESPERADA",
        "DIAG CADDY: PROCESO_TERMINADO",
        "DIAG HTTP_STATUS:",
        "DIAG STUB_LEGACY:",
        "DIAG TRANSPORTE:",
        "DIAG TLS_REASON:",
        "DIAG TLS_VERIFY_CODE:",
    ):
        assert marker in source
    # El traceback completo puede revelar rutas o material privado:
    # se imprime solamente la clase y diagnosticos acotados.
    assert "traceback.print_exc" not in source
    assert "print(exc)" not in source
    assert "print(error)" not in source
    assert "print(_body)" not in source
    assert "print(server_key)" not in source


def test_ephemeral_cert_chain_passes_python_x509_strict_tls_handshake(tmp_path):
    """Regresion exacta del OpenSSL verify_code=85 en Python 3.14.

    No se relaja VERIFY_X509_STRICT. El cliente valida la CA y el SNI
    por TLS real en 127.0.0.1, sin Caddy ni abrir puertos publicos.
    """
    from cryptography import x509
    import socket
    import ssl
    import threading

    ca = tls.create_local_ca(tmp_path)
    crt_path = tmp_path / "local_server.pem"
    key_path = tmp_path / "local_server_private.pem"
    root = x509.load_pem_x509_certificate(ca.read_bytes())
    leaf = x509.load_pem_x509_certificate(crt_path.read_bytes())
    root_ski = root.extensions.get_extension_for_class(
        x509.SubjectKeyIdentifier
    ).value.digest
    root_aki = root.extensions.get_extension_for_class(
        x509.AuthorityKeyIdentifier
    ).value.key_identifier
    leaf_aki = leaf.extensions.get_extension_for_class(
        x509.AuthorityKeyIdentifier
    ).value.key_identifier
    leaf.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
    assert root_ski == root_aki == leaf_aki

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(crt_path), str(key_path))
    client_ctx = ssl.create_default_context(cafile=str(ca))
    client_ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    assert client_ctx.check_hostname
    assert client_ctx.verify_mode == ssl.CERT_REQUIRED

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]
        failures = []

        def serve_one():
            try:
                conn, _address = listener.accept()
                with conn:
                    with server_ctx.wrap_socket(conn, server_side=True) as stream:
                        stream.recv(1)
            except Exception as exc:
                failures.append(type(exc).__name__)

        thread = threading.Thread(target=serve_one, daemon=True)
        thread.start()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with client_ctx.wrap_socket(
                raw, server_hostname=tls.DOMAIN
            ) as client:
                assert client.version() in ("TLSv1.2", "TLSv1.3")
                client.sendall(b"X")
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert failures == []
