"""5.5 K-Y — regresión estática del sidecar Windows.

No ejecutar procesos en CI Linux ni añadir servicio real a app.main.
La única prueba de arranque/parada real se realiza en Windows GitHub Actions.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ky_launcher_is_explicitly_ci_only():
    launcher = (ROOT / "app/public_control/ky_windows_sidecar.py").read_text("utf-8")
    assert 'os.name != "nt"' in launcher
    assert 'os.getenv("GITHUB_ACTIONS") != "true"' in launcher
    assert 'os.getenv("KY_WINDOWS_CI_ONLY") != "isolated-sidecar"' in launcher
    assert '"bind_host"] != "127.0.0.1"' in launcher
    assert '"bind_port"] != 9444' in launcher
    assert 'not db.is_relative_to(runner)' in launcher
    assert 'workers=1' in launcher
    assert 'proxy_headers=False' in launcher
    assert 'access_log=False' in launcher
    assert 'app.public_control.kv_virtual_staging' in launcher
    assert 'app.main' not in launcher.replace('app.main,', 'legacy API')


def test_ky_original_windows_runtime_not_touched():
    for path in (
        "app/main.py",
        "deploy/windows/install.ps1",
        "deploy/windows/run_api.ps1",
        "deploy/windows/run_caddy.ps1",
        "deploy/windows/Caddyfile",
    ):
        source = (ROOT / path).read_text("utf-8")
        assert "ky_windows_sidecar" not in source
        assert "KY_WINDOWS_CI_ONLY" not in source
    legacy = (ROOT / "deploy/windows/Caddyfile").read_text("utf-8")
    assert "127.0.0.1:8000" in legacy
    assert "9444" not in legacy


def test_ky_windows_test_never_creates_task_or_modifies_legacy():
    contents = (ROOT / "tests/ky_windows_sidecar_ci.ps1").read_text("utf-8")
    for command in (
        "Register-ScheduledTask", "Unregister-ScheduledTask",
        "Install-Service", "Set-NetFirewallRule", "New-NetFirewallRule",
        "deploy\\windows\\install.ps1", "deploy\\windows\\restart.ps1",
    ):
        assert command not in contents
    assert "Stop-Process -Id $sidecar.Id -Force" in contents
    assert "Stop-Process -Id $legacy.Id -Force" in contents
    assert "Get-HttpStatus 8000" in contents
    assert "Get-HttpStatus 9444" in contents
