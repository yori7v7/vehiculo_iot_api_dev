"""K-Z: contrato estático de instalación/rollback, sin conexión a EC2.

La tarea creada por tests/kz_windows_task_lifecycle_ci.ps1 es un
marcador sin triggers en el runner Windows y nunca opera el vehículo.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_kz_plan_is_readonly_and_explicitly_not_an_installer():
    plan = (ROOT / "deploy/staging/kw/kz_installation_plan_readonly.ps1").read_text("utf-8")
    assert "ValidateSet('Plan','VerifyRepository')" in plan
    assert "NO-GO" in plan
    assert "LocalService" in plan
    assert "9444" in plan
    assert "reverse_proxy 127.0.0.1:8000" in plan
    assert "StateDirectory" in plan
    assert "Get-Content" in plan
    assert "exit 2" in plan
    for forbidden in (
        "Register-ScheduledTask", "Unregister-ScheduledTask", "Start-ScheduledTask",
        "Stop-ScheduledTask", "Enable-ScheduledTask", "Disable-ScheduledTask",
        "Set-Acl", "Copy-Item", "Move-Item", "Set-NetFirewallRule", "Start-Process",
    ):
        assert forbidden not in plan


def test_kz_ci_task_is_disabled_no_trigger_and_cleans_up():
    script = (ROOT / "tests/kz_windows_task_lifecycle_ci.ps1").read_text("utf-8")
    assert "$env:GITHUB_ACTIONS -ne 'true'" in script
    assert "$env:RUNNER_TEMP" in script
    assert "'NT AUTHORITY\\LOCAL SERVICE'" in script
    assert "'S-1-5-19'" in script
    assert "Register-ScheduledTask" in script
    assert "Disable-ScheduledTask" in script
    assert "Unregister-ScheduledTask" in script
    assert "New-ScheduledTaskTrigger" not in script
    assert "Start-ScheduledTask" not in script
    assert "Set-NetFirewallRule" not in script
    assert "New-NetFirewallRule" not in script
    assert "Stop-Process" not in script
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "original_caddy_hash" in script
    assert "Assert-LegacyNotModified" in script


def test_kz_no_change_legacy_or_pages():
    for path in (
        "deploy/windows/install.ps1",
        "deploy/windows/start.ps1",
        "deploy/windows/stop.ps1",
        "deploy/windows/run_api.ps1",
        "deploy/windows/run_caddy.ps1",
        "app/main.py",
    ):
        text = (ROOT / path).read_text("utf-8")
        assert "KZ-Virtual-CI" not in text
        assert "kz_installation_plan_readonly" not in text
    original = (ROOT / "deploy/windows/Caddyfile").read_text("utf-8")
    assert "127.0.0.1:8000" in original
    assert "9444" not in original
