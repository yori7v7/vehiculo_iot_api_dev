"""Contrato del ensayo REAL de Caddy con puertos efimeros y stubs ficticios."""
from pathlib import Path
import pytest
from scripts import kx_caddy_loopback_smoke as smoke


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "deploy/staging/kw/Caddyfile.kx_diagnostic_NOT_DEPLOY"


def test_transform_to_loopback_ports_without_public_exposure():
    source = PROPOSAL.read_text(encoding="utf-8")
    transformed = smoke._loopback_config(source, 19080, 19444, 18000)
    assert transformed.startswith("{\n    admin off\n    auto_https off\n}")
    assert "http://127.0.0.1:19080 {" in transformed
    assert "reverse_proxy 127.0.0.1:19444" in transformed
    assert "reverse_proxy 127.0.0.1:18000" in transformed
    assert "100-30-4-62.nip.io {" not in transformed
    assert "reverse_proxy 127.0.0.1:9444" not in transformed
    assert "reverse_proxy 127.0.0.1:8000" not in transformed
    assert "header Upgrade *" in transformed
    assert "handle @legacy_upgrade {" in transformed


@pytest.mark.parametrize("removed", [
    "NO INSTALAR",
    "handle @legacy_upgrade",
    "header Upgrade *",
    "handle @legacy_write",
    "reverse_proxy 127.0.0.1:9444",
])
def test_refuses_unsafe_or_unexpected_candidate(removed):
    source = PROPOSAL.read_text(encoding="utf-8")
    broken = source.replace(removed, "NOT-A-VALID-MARKER")
    with pytest.raises(ValueError):
        smoke._loopback_config(broken, 19080, 19444, 18000)


def test_test_matrix_blocks_legacy_wss_and_writes(monkeypatch):
    calls = []

    def mock_request(port, method, path, headers=None):
        calls.append((port, method, path, headers))
        # Validate the declared matrix in a benign mock; real routing is
        # intentionally left to caddy.exe loopback smoke during EC2 review.
        if path.startswith((smoke.WSS, smoke.GUEST, smoke.ADMIN)):
            return 200, "kx"
        if path.startswith("/ws") or (headers and headers.get("Upgrade")):
            return 403, ""
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return 503, ""
        if method == "TRACE":
            return 405, ""
        return 200, "legacy"

    monkeypatch.setattr(smoke, "_request", mock_request)
    assert smoke._test_routing(19080) == 20
    assert any(method == "POST" and path.endswith("/movimientos")
               for _, method, path, _ in calls)
    assert any(method == "GET" and path == "/ws%2Fvehiculos%2F1"
               for _, method, path, _ in calls)


def test_comments_may_mention_legacy_port_without_failing_real_port_fence():
    source = PROPOSAL.read_text(encoding="utf-8")
    transformed = smoke._loopback_config(source, 19080, 19444, 18000)
    # Documentacion para rollback, no una directiva ejecutable.
    assert "# El backend original 127.0.0.1:8000" in transformed
    assert smoke._has_real_port_in_active_directives(transformed) is False


@pytest.mark.parametrize("port", (443, 8000, 9444))
def test_active_reference_to_protected_port_remains_a_hard_failure(port):
    base = smoke._loopback_config(
        PROPOSAL.read_text(encoding="utf-8"), 19080, 19444, 18000
    )
    tampered = base.replace(
        "reverse_proxy 127.0.0.1:18000",
        "reverse_proxy 127.0.0.1:" + str(port),
    )
    assert smoke._has_real_port_in_active_directives(tampered) is True


def test_comment_only_protected_ports_are_ignored():
    text = """
    # 127.0.0.1:443
    # 127.0.0.1:8000
    # 127.0.0.1:9444
    reverse_proxy 127.0.0.1:18000
    """
    assert smoke._has_real_port_in_active_directives(text) is False
