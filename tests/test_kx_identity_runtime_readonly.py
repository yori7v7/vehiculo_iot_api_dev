"""Prevent K-X account/runtime preflight from making installation changes."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "scripts/kx_identity_runtime_readonly.ps1"


def test_inspects_staging_runtime_and_windows_identity_without_showing_secrets():
    c = CODE.read_text(encoding="utf-8")
    for marker in (
        "offline_staging_only",
        "source_python_files -eq 99",
        "ACL raiz reservada a SYSTEM/Administradores",
        "PYTHON BASE EN PERFIL ADMINISTRADOR",
        "PYTHON BASE FUERA DEL PERFIL ADMINISTRADOR",
        "Get-LocalUser -Name $ProposedAccount",
        "Get-ScheduledTask -TaskPath",
        "Get-NetTCPConnection -LocalPort 9444",
        "Get-FileHash -LiteralPath $original",
        "NO SE CREARON USUARIOS, TAREAS NI PROCESOS",
    ):
        assert marker in c


def test_does_not_mutate_accounts_processes_firewall_or_caddy():
    c = CODE.read_text(encoding="utf-8")
    for forbidden in (
        "New-LocalUser", "Set-LocalUser", "Disable-LocalUser",
        "Register-ScheduledTask", "Start-ScheduledTask",
        "Set-ScheduledTask", "Stop-ScheduledTask",
        "Unregister-ScheduledTask", "Set-Service",
        "Start-Service", "Stop-Service", "New-NetFirewallRule",
        "Copy-Item", "Remove-Item", "Set-Content", "Out-File",
        "icacls.exe", "Set-Acl", "Add-Content",
    ):
        # Get-Command New-LocalUser is a read-only capability check,
        # not a call to create a user.
        assert re.search(r"(?m)^\\s*(?:&\\s*)?" + re.escape(forbidden) + r"\\b", c) is None
