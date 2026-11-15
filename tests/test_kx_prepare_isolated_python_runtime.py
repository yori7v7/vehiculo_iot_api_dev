"""Stage Python base and fresh venv without replacing the Windows legacy app."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kx_prepare_isolated_python_runtime.ps1"


def test_runtime_requires_offline_stage_and_protects_original_services():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "runtime = Join-Path $StageRoot 'runtime'" in code or "$runtime = Join-Path $StageRoot 'runtime'" in code
    for required in (
        "offline_staging_only",
        "persistent_task_created -eq $false",
        "caddy_deployed -eq $false",
        "physical_control_enabled -eq $false",
        "live_caddy_sha256_before",
        "$hashBefore",
        "Get-NetTCPConnection -LocalPort 9444",
        "Staging accesible por identidad no autorizada",
        "Runtime ya existe, no sobrescribir",
    ):
        assert required in code


def test_new_python_isolated_from_admin_venv_and_site_packages():
    code = SCRIPT.read_text(encoding="utf-8")
    for required in (
        "'python314.dll'",
        "'Lib\\ensurepip\\__init__.py'",
        "'Lib\\venv\\__init__.py'",
        "'DLLs'",
        "Lib\\site-packages",
        "'/XJ'",
        "'--no-cache-dir'",
        "'--index-url'",
        "'https://pypi.org/simple'",
        "venv --copies",
        "sys.base_prefix",
        "Get-KXGitBlob",
        "requirements.txt",
        "venv no utiliza",
    ):
        if required == "venv no utiliza":
            assert "Venv depende de Python antiguo" in code
        else:
            assert required in code
    assert "Copy-Item -LiteralPath $srcPython" not in code
    assert "Copy-Item -LiteralPath $SourceRoot" not in code
    assert "Copy-Item -LiteralPath $sourceBase" not in code
    assert "site-packages globales copiados" not in code


def test_never_registers_a_task_or_changes_caddy_firewall_device_secrets():
    code = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "Register-ScheduledTask", "Start-ScheduledTask",
        "Unregister-ScheduledTask", "Stop-ScheduledTask",
        "New-LocalUser", "Set-LocalUser", "New-NetFirewallRule",
        "Set-NetFirewallRule", "Restart-Service", "Set-Service",
        "Stop-Service", "Start-Service",
        "Copy-Item -LiteralPath $caddyOriginal",
        "Copy-Item -LiteralPath $hmacPath",
        "Set-Content -LiteralPath $caddyOriginal",
    ):
        assert re.search(r"(?m)^\s*(?:&\s*)?" + re.escape(forbidden) + r"\b", code) is None
    assert "hardware_enabled" not in code or "physical_control_enabled = $false" in code
