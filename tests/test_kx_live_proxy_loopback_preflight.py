"""K-X: prueba de contrato del ensayo local conjunto Caddy/FastAPI."""
import ast
from pathlib import Path
import pytest

from scripts import kx_live_proxy_loopback_preflight as testapp


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "deploy/staging/kw/Caddyfile.kx_diagnostic_NOT_DEPLOY"


def test_candidate_transforms_only_reachable_routes_to_loopback():
    source = CANDIDATE.read_text(encoding="utf-8")
    modified = testapp.loopback_config(source, 19080, 18080)
    assert modified.startswith("{\n    admin off\n    auto_https off\n}")
    assert "http://127.0.0.1:19080 {" in modified
    assert "reverse_proxy 127.0.0.1:18080" in modified
    assert "reverse_proxy 127.0.0.1:9444" in modified
    assert "handle @legacy_upgrade" in modified
    assert "header_up X-Forwarded-Proto https" in modified
    assert "reverse_proxy 127.0.0.1:8000" not in modified
    assert "0.0.0.0:19080" not in modified


@pytest.mark.parametrize("to_remove", [
    "NO INSTALAR", "handle @legacy_write", "handle @legacy_websockets",
    "handle @legacy_upgrade", "header Upgrade *",
    "header_up X-Forwarded-Proto https",
    "reverse_proxy 127.0.0.1:9444",
])
def test_missing_safety_line_is_hard_refusal(to_remove):
    source = CANDIDATE.read_text(encoding="utf-8")
    modified = source.replace(to_remove, "DELETED")
    with pytest.raises(RuntimeError):
        testapp.loopback_config(modified, 19080, 18080)


def test_no_aws_binds_or_device_commands_in_test_script():
    source = Path(testapp.__file__).read_text(encoding="utf-8")
    ast.parse(source)
    assert 'HOST = "127.0.0.1"' in source
    assert 'KEY_PORT = 9444' in source
    assert 'ws_challenge(edge)' in source
    assert '"--proxy-headers", "--forwarded-allow-ips", HOST' in source
    assert "PUBLIC_VIRTUAL_ADMISSION_ENABLED" in source
    assert '"DEVICE_LAB_ENABLED": "false"' in source
    assert "terminate()" in source
    assert "cleanup_state(temp)" in source
    assert "https://yori7v7.github.io" in source
    assert "gpio.write" not in source.lower()


def test_run_is_blocked_outside_windows(tmp_path, capsys):
    response = testapp.main([
        "--repo", str(tmp_path),
        "--python", str(tmp_path / "py.exe"),
        "--caddy-exe", str(tmp_path / "caddy.exe"),
        "--candidate", str(CANDIDATE),
        "--active", str(tmp_path / "Caddyfile"),
        "--key-path", str(tmp_path / "key.bin"),
    ])
    assert response == 2
    assert "NO-GO" in capsys.readouterr().out
