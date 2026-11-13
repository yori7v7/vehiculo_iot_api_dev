"""K-AC: contratos de no despliegue y reversión virtual.

No conecta a EC2 ni arranca servidores. El ciclo de red se valida por CI.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_kac_readonly_script_never_mutates_host():
    script = (ROOT / "deploy/staging/kw/kac_ec2_preflight_READONLY.ps1").read_text("utf-8")
    assert "ValidateSet('Repository','Server')" in script
    assert "Get-ScheduledTask" in script
    assert "Get-NetTCPConnection" in script
    assert "Get-Acl" in script
    assert "deployment.json" in script
    assert "Caddyfile" in script
    assert "Read-KAC" in script
    assert "NO-GO" in script
    for command in (
        "Register-ScheduledTask", "Unregister-ScheduledTask",
        "Start-ScheduledTask", "Stop-ScheduledTask",
        "Enable-ScheduledTask", "Disable-ScheduledTask",
        "Set-ScheduledTask", "New-ScheduledTask",
        "Set-Acl", "Set-Content", "Copy-Item", "Move-Item",
        "Remove-Item", "Start-Process", "Stop-Process",
        "Invoke-WebRequest", "Invoke-RestMethod",
        "Set-NetFirewallRule", "New-NetFirewallRule",
    ):
        assert not re.search(rf"(?m)^\s*{re.escape(command)}\b", script), command
    assert "DB_PASSWORD" not in script
    assert "API_KEY" not in script
    assert "Get-Content -LiteralPath $Name" in script


def test_kac_candidate_proxy_and_original_are_not_deployed():
    original = (ROOT / "deploy/windows/Caddyfile").read_text("utf-8").strip()
    candidate = (
        ROOT / "deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY"
    ).read_text("utf-8")
    assert original == (
        "100-30-4-62.nip.io {\n"
        "    reverse_proxy 127.0.0.1:8000\n}"
    )
    assert "127.0.0.1:9444" not in original
    assert "reverse_proxy 127.0.0.1:8000" in candidate
    assert "reverse_proxy 127.0.0.1:9444" in candidate
    assert "header_up X-Admission-Client-IP {remote_host}" in candidate
    assert "header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}" in candidate
    assert "8.8.8.8" not in candidate


def test_kac_caddy_ci_does_not_edit_real_windows_files():
    builder = (ROOT / "scripts/kac_ci_prepare_caddy.py").read_text("utf-8")
    assert "Caddyfile.candidate_NOT_DEPLOY" in builder
    assert '"candidate.caddy"' in builder
    assert '"rollback.caddy"' in builder
    assert "127.0.0.1" in builder
    checks = (ROOT / "scripts/kac_ci_verify_roundtrip.py").read_text("utf-8")
    assert 'choices=["candidate", "sidecar_off", "rollback"]' in checks
    assert "check_legacy()" in checks
    assert "status == 502" in checks
    assert "status == 403" in checks
    assert "ca" in checks.lower()
    workflow = (ROOT / ".github/workflows/kac-caddy-coexistence-ci.yml").read_text("utf-8")
    assert "caddy:2.10.2" in workflow
    assert "--network host" in workflow
    assert "kac-ci-proxy" in workflow
    assert "scripts.kac_ci_legacy_stub" in workflow
    assert "scripts.servidor_55kw_ci" in workflow
    assert "KAC_ROOT_CA" in workflow
    assert "RUNNER_TEMP/kac" in workflow
    assert "aws ec2" not in workflow


def test_kac_integration_never_touches_legacy_runtime_files():
    for path in (
        "app/main.py",
        "deploy/windows/install.ps1",
        "deploy/windows/start.ps1",
        "deploy/windows/stop.ps1",
        "deploy/windows/run_api.ps1",
        "deploy/windows/run_caddy.ps1",
        "deploy/windows/Caddyfile",
    ):
        content = (ROOT / path).read_text("utf-8")
        assert "kac_ec2_preflight" not in content
        assert "kac_ci_prepare_caddy" not in content
        assert "kac_ci_verify_roundtrip" not in content
