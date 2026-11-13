"""K-AA: contrato estático del ensayo TaskScheduler + LocalService.

Este módulo prueba que K-AA está separado de EC2 y del backend principal;
la prueba Windows CI ejecuta el sidecar real y verifica el comportamiento.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_kaa_task_runner_can_only_target_ci_virtual_sidecar():
    source = (ROOT / "deploy/staging/kw/kaa_ci_task_runner.ps1").read_text("utf-8")
    assert "KAA_CI_ONLY.marker" in source
    assert "KY_WINDOWS_CI_ONLY" in source
    assert "GITHUB_ACTIONS" in source
    assert "ADMISSION_VIRTUAL_ONLY" in source
    assert "app.public_control.ky_windows_sidecar" in source
    assert "app.main:app" not in source
    assert "0.0.0.0" not in source
    assert "Start-ScheduledTask" not in source
    assert "Register-ScheduledTask" not in source


def test_kaa_ci_harness_is_ephemeral_localservice_no_autostart():
    source = (ROOT / "tests/kaa_task_localservice_real_ci.ps1").read_text("utf-8")
    assert "GITHUB_ACTIONS" in source
    assert "RUNNER_TEMP" in source
    assert "NT AUTHORITY\\LOCAL SERVICE" in source
    assert "New-ScheduledTaskPrincipal" in source
    assert "New-ScheduledTaskTrigger" not in source
    assert "Start-ScheduledTask" in source
    assert "Stop-ScheduledTask" in source
    assert "Disable-ScheduledTask" in source
    assert "Unregister-ScheduledTask" in source
    assert "KAA-CI-" in source
    assert "VehiculoIoT-Admission-Virtual" not in source
    assert "VehiculoIoT-FastAPI" not in source
    assert "VehiculoIoT-Caddy" not in source
    assert "Set-NetFirewallRule" not in source
    assert "aws " not in source
    assert "'127.0.0.1'" in source
    assert "Get-Status 8000" in source
    assert "Get-Status 9444" in source


def test_kaa_still_does_not_deploy_anything_public():
    for path in (
        "app/main.py", "deploy/windows/install.ps1",
        "deploy/windows/run_api.ps1", "deploy/windows/run_caddy.ps1",
        "deploy/windows/Caddyfile",
    ):
        contents = (ROOT / path).read_text("utf-8")
        assert "kaa_ci_task_runner" not in contents
        assert "KAA-CI" not in contents
    assert "127.0.0.1:8000" in (
        ROOT / "deploy/windows/Caddyfile").read_text("utf-8")
