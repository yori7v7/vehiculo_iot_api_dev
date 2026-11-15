"""K-X offline staging safety contract (static analysis, no EC2 writes)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kx_prepare_staging_offline.ps1"


def test_staging_separate_and_requires_private_acl_before_code_copy():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "'VehiculoIoT-KX-Staging'" in text
    assert "'VehiculoIoT'" in text
    assert "'S-1-5-18'" in text
    assert "'S-1-5-32-544'" in text
    assert "/inheritance:r" in text
    assert "Assert-StagingAcl $destination" in text
    assert text.index("Assert-StagingAcl $destination") < text.index(
        "Copy-Item -LiteralPath $file.FullName"
    )


def test_staging_is_offline_and_has_immutable_source_validation():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "'offline_staging_only'" in text
    assert "$files.Count -eq 99" in text
    assert "'app\\main.py'" in text
    assert "'app\\public_control\\kx_inline_admission.py'" in text
    assert "'app\\public_control\\kx_signed_wss.py'" in text
    assert "Get-GitBlob" in text
    assert "Copy-Item -LiteralPath $activeCaddy" in text
    assert "initialCaddySHA256" in text
    assert "created_utc" in text
    assert "persistent_task_created = $false" in text
    assert "caddy_deployed = $false" in text
    assert "physical_control_enabled = $false" in text


def test_staging_copies_no_credentials_or_executables_and_never_starts_task():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "-Filter '*.py'" in text
    assert ".env" in text
    assert "'Caddyfile.before-KX'" in text
    assert "REGISTR" not in text.upper() or "NO INSTALADO" in text
    forbidden = (
        "Register-ScheduledTask ", "Start-ScheduledTask ", "Stop-ScheduledTask ",
        "Set-ScheduledTask ", "Start-Process ", "New-Service ",
        "Set-Service ", "Stop-Service ", "Set-NetFirewallRule ",
        "New-NetFirewallRule ", "Copy-Item -LiteralPath $hmacPath",
    )
    for name in forbidden:
        assert name not in text


def test_preconditions_before_first_write():
    text = SCRIPT.read_text(encoding="utf-8")
    first_write = text.index("New-Item -ItemType Directory -Path $destination")
    for requirement in (
        "Ya existe staging: no sobrescribir",
        "checkout K-X", "Identidad HMAC",
        "Arbol Python distinto del candidato",
        "Puerto 9444 ocupado",
        "Caddy activo no es el legacy original",
    ):
        assert requirement.lower() in text[:first_write].lower()
