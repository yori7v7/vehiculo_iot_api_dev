"""K-AD: source contracts of the read-only Windows preflight.

This test does not contact AWS or Windows. Actual PowerShell behavior is
exercised with synthetic data by kad_process_policy_ci.ps1 in Windows Actions.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "deploy/staging/kw/kac_ec2_preflight_READONLY.ps1"
POLICY = ROOT / "deploy/staging/kw/kad_process_policy.ps1"
WORKFLOW = ROOT / ".github/workflows/kac-windows-readonly-ci.yml"
WIN_TEST = ROOT / "tests/kad_process_policy_ci.ps1"
SERVER_TEST = ROOT / "tests/kac_server_preflight_ci.ps1"


def test_kad_process_ownership_is_bound_to_windows_process_and_socket():
    text = POLICY.read_text(encoding="utf-8")
    assert "function Test-KADProcessOwnership" in text
    for requirement in (
        "Record.creation_ticks",
        "Process.CreationDate.ToUniversalTime().Ticks",
        "Record.executable_path",
        "Process.ExecutablePath",
        "OwningProcess",
        "IdentityMatches",
        "AllListenersOwned",
        "HasListeners",
        "AllowPythonVenvRedirector",
        "UsesVenvRedirector",
        "SupervisorRecord",
        "ParentProcessId",
        "CommandLine",
        "VenvConfigLines",
    ):
        assert requirement in text
    assert "OrdinalIgnoreCase" in text
    assert "IsSafe" in text
    assert "Get-CimInstance" not in text  # Pure policy: zero OS queries


def test_kad_server_checks_legacy_and_https_owners_before_staging():
    code = PREFLIGHT.read_text(encoding="utf-8")
    for requirement in (
        "Test-KADPortPolicy",
        "kad_process_policy.ps1",
        "Test-KADProcessOwnership",
        "Get-CimInstance Win32_Process",
        "Get-NetTCPConnection -State Listen -ErrorAction Stop",
        "LegacyProjectRoot",
        "$ownershipArgs.AllowPythonVenvRedirector = $true",
        "$ownershipArgs.ExpectedSupervisorArguments = $apiTaskArguments",
        "pyvenv.cfg",
        "Get-KADVenvMetadata",
        "Read-KAC $processRecordPath",
        "('run\\' + $component + '.json')",
        "$ownership.IsSafe",
        "Test-KAC ([string]$task.State -eq 'Running')",
        "HasUnsafeWrite-KAC $installed",
        "$cfg.caddy_path -eq $expectedCaddy",
    ):
        assert requirement in code, requirement
    assert "if (-not $stateInsideProgramData)" in code
    assert not re.search(r"(?m)Get-NetTCPConnection[^\r\n]*SilentlyContinue", code)
    assert not re.search(r"(?m)Get-CimInstance[^\r\n]*SilentlyContinue", code)
    # No dispatch, service mutation, file mutation, AWS, or actuator activity.
    for command in (
        "Start-ScheduledTask", "Stop-ScheduledTask", "Register-ScheduledTask",
        "Unregister-ScheduledTask", "Set-ScheduledTask", "Start-Process",
        "Stop-Process", "Set-Content", "Set-Acl", "Copy-Item", "Move-Item",
        "Remove-Item", "New-NetFirewallRule", "Invoke-RestMethod",
    ):
        assert not re.search(rf"(?m)^\s*{re.escape(command)}\b", code), command


def test_kad_identity_matrix_is_executed_by_windows_ci_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    test_code = WIN_TEST.read_text(encoding="utf-8")
    assert "shell: powershell" in workflow
    assert "kad_process_policy_ci.ps1" in workflow
    assert "K-AD verificación de propiedad de procesos" in workflow
    assert "GITHUB_ACTIONS" in test_code and "Windows_NT" in test_code
    assert "PID recirculado" in test_code
    assert "un listener propio y otro intruso" in test_code
    assert "sin proceso real" in test_code
    assert "kac_server_preflight_ci.ps1" in workflow
    case_scenarios = SERVER_TEST.read_text(encoding="utf-8")
    for scenario in (
        "redirector", "wrong-project", "extra-listener", "socket-changed",
        "cim-changed", "linked-config", "untrusted-venv-user-inherited",
        "untrusted-parent-user-explicit", "untrusted-base-user-inherited",
        "null-dacl", "missing-dacl", "user-read-only", "user-denied-only",
    ):
        assert f"Name='{scenario}'" in case_scenarios

    # Fail closed even when a nullable ACL would otherwise report no unsafe ACEs.
    code = PREFLIGHT.read_text(encoding="utf-8")
    assert "KAC_ACL_DACL_AUSENTE" in code
    assert "GetSecurityDescriptorBinaryForm" in code
    assert "Categoria segura" in code

