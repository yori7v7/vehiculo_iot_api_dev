"""K-X: garantías estáticas de preflight Windows, NO interactúa con EC2."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "deploy/staging/kw/kx_readonly_preflight.ps1"
WINDOWS_CADDY = ROOT / "deploy/windows/Caddyfile"
CANDIDATE = ROOT / "deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY"
WINDOWS_API = ROOT / "deploy/windows/run_api.ps1"
WINDOWS_CADDY_RUN = ROOT / "deploy/windows/run_caddy.ps1"


def test_kx_audit_offline_has_no_host_mutations():
    source = AUDIT.read_text(encoding="utf-8")
    assert "ValidateSet('Repository','Server')" in source
    assert "Get-ScheduledTask" in source
    assert "Get-NetTCPConnection" in source
    assert "NO-GO" in source
    assert "exit 2" in source
    assert "StateDirectory" in source
    assert "Get-Content" in source
    # El preflight solo lee y reporta, no aplica cambios, arranca o conecta.
    prohibited = (
        "Set-Content", "Add-Content", "Copy-Item", "Move-Item", "Remove-Item",
        "New-ScheduledTask", "Register-ScheduledTask", "Start-ScheduledTask",
        "Stop-ScheduledTask", "Enable-ScheduledTask", "Disable-ScheduledTask",
        "Start-Process", "Invoke-RestMethod", "Invoke-WebRequest",
        "Set-NetFirewallRule", "New-NetFirewallRule", "Remove-NetFirewallRule",
    )
    for command in prohibited:
        assert not re.search(rf"(?m)^\s*(?:&\s*)?{re.escape(command)}\b", source), command
    for name in ("API_KEY", "DB_PASSWORD", "AWS_SECRET_ACCESS_KEY"):
        assert name not in source


def test_kx_legacy_configuration_unchanged():
    assert WINDOWS_CADDY.read_text("utf-8").strip() == (
        "100-30-4-62.nip.io {\n"
        "    reverse_proxy 127.0.0.1:8000\n}"
    )
    server = WINDOWS_API.read_text("utf-8")
    assert "'127.0.0.1', '--port', '8000'" in server
    assert "--workers', '1'" in server
    assert "app.main:app" in server
    caddy = WINDOWS_CADDY_RUN.read_text("utf-8")
    assert "$configuration.caddyfile_path" in caddy
    assert "kw/" not in caddy.lower()
    assert "kv_virtual_staging" not in server


def test_kx_candidate_is_out_of_deploy_path():
    assert CANDIDATE.name == "Caddyfile.candidate_NOT_DEPLOY"
    proposal = CANDIDATE.read_text("utf-8")
    assert "reverse_proxy 127.0.0.1:8000" in proposal
    assert "reverse_proxy 127.0.0.1:9444" in proposal
    assert "header_up X-Admission-Client-IP {remote_host}" in proposal
    assert "8.8.8.8" not in proposal
    assert "header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}" in proposal
    assert "NO INSTALAR" in proposal
