"""K-AB: barreas de seguridad sin AWS ni dependencia de Windows real."""
from pathlib import Path
import os

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_kab_launcher_ci_and_production_gates(monkeypatch):
    from app.public_control.kab_windows_staging import (
        StagingRefused, _state_root, load_staging
    )
    # Nunca permitir un arranque accidental desde Linux o un contenedor.
    if os.name != "nt":
        with pytest.raises(StagingRefused):
            _state_root(None)
        with pytest.raises(StagingRefused):
            load_staging(str(ROOT), serve=True)
    monkeypatch.delenv("KAB_WINDOWS_CI_ONLY", raising=False)
    launcher = (ROOT / "app/public_control/kab_windows_staging.py").read_text("utf-8")
    for guard in (
        'GITHUB_ACTIONS', 'KAB_WINDOWS_CI_ONLY', 'ProgramData',
        'Path(configured).resolve(strict=True)', 'bind_host', '127.0.0.1',
        'service_sid', 'enabled', 'is not True',
        'admin.proof', 'proxy.proof', 'check_private',
        'S-1-5-19', 'virtual_staging', 'canDrive',
    ):
        if guard == "canDrive":
            assert 'create_kv_virtual_app' in launcher
        else:
            assert guard in launcher


def test_kab_safety_routing_and_no_secret_leaks():
    launcher = (ROOT / "app/public_control/kab_windows_staging.py").read_text("utf-8")
    assert "uvicorn.run" in launcher
    assert 'host="127.0.0.1", port=9444, workers=1' in launcher
    assert "reload=False" in launcher
    assert "proxy_headers=False" in launcher
    assert "access_log=False" in launcher
    assert 'app.public_control.kv_virtual_staging' in launcher
    assert "app.main:app" not in launcher
    assert "controller.dispatch" not in launcher
    assert "RDS" not in launcher.upper().replace("RDS O", "")
    assert "print(admin)" not in launcher
    assert "print(proxy)" not in launcher


def test_kab_ci_task_has_no_legacy_or_public_network_dependencies():
    source = (ROOT / "tests/kab_windows_staging_ci.ps1").read_text("utf-8")
    assert "GITHUB_ACTIONS" in source
    assert "NT AUTHORITY\\LOCAL SERVICE" in source
    assert "New-ScheduledTaskPrincipal" in source
    assert "Start-ScheduledTask" in source
    assert "Stop-ScheduledTask" in source
    assert "Unregister-ScheduledTask" in source
    assert "New-ScheduledTaskTrigger" not in source
    assert "New-NetFirewallRule" not in source
    assert "Set-NetFirewallRule" not in source
    assert "aws ec2" not in source
    assert "s3://" not in source
    assert "KAB_CI_ONLY.marker" in source
    assert "enabled=$false" in source
    assert "enabled=$true" in source
    assert "Get-Status 8000" not in source
    assert "Http-KAB 8000" in source
    assert "Http-KAB 9444" in source
    assert "VehiculoIoT-Caddy" not in source
    assert "VehiculoIoT-FastAPI" not in source


def test_kab_legacy_main_and_caddy_still_unchanged():
    for path in (
        "deploy/windows/Caddyfile",
        "deploy/windows/install.ps1", "deploy/windows/start.ps1",
        "deploy/windows/stop.ps1", "deploy/windows/run_api.ps1",
        "deploy/windows/run_caddy.ps1", "app/main.py",
    ):
        content = (ROOT / path).read_text("utf-8")
        assert "kab_windows_staging" not in content
        assert "kab_ci_direct" not in content
    caddy = (ROOT / "deploy/windows/Caddyfile").read_text("utf-8")
    assert "reverse_proxy 127.0.0.1:8000" in caddy
    assert "9444" not in caddy
