# K-Z: PLAN DE INSTALACION VIRTUAL, SOLO LECTURA, PowerShell 5.1.
#
# No registra tareas ni copia claves. Esta lista de comprobaciones es
# deliberadamente NO DESPLEGABLE: el tercero se registra primero en un
# Windows runner aislado; la instalación EC2 requerirá otro GO explícito.
[CmdletBinding()]
param(
    [ValidateSet('Plan','VerifyRepository')][string]$Mode = 'Plan',
    [string]$StateDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).ProviderPath
$caddyOriginal = Join-Path $root 'deploy\windows\Caddyfile'
$caddyCandidate = Join-Path $PSScriptRoot 'Caddyfile.candidate_NOT_DEPLOY'
$legacyInstall = Join-Path $root 'deploy\windows\install.ps1'
$virtualBackend = Join-Path $root 'app\public_control\kv_virtual_staging.py'
$taskName = 'VehiculoIoT-Admission-Virtual'

function Require-KZ([bool]$Condition,[string]$Reason) {
    if (-not $Condition) { throw ('[K-Z] NO-GO: ' + $Reason) }
}
function Get-KZ([string]$Path) {
    Require-KZ (Test-Path -LiteralPath $Path -PathType Leaf) 'Falta el archivo de contrato.'
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

try {
    $orig = Get-KZ $caddyOriginal
    $cand = Get-KZ $caddyCandidate
    $installer = Get-KZ $legacyInstall
    $virtual = Get-KZ $virtualBackend
    $canonicalOriginal = ($orig -replace "`r`n?", "`n").Trim()
    Require-KZ ($canonicalOriginal -eq "100-30-4-62.nip.io {`n    reverse_proxy 127.0.0.1:8000`n}") 'Caddy original inesperado'
    Require-KZ ($cand.Contains('reverse_proxy 127.0.0.1:8000')) 'Candidato no preserva legado'
    Require-KZ ($cand.Contains('reverse_proxy 127.0.0.1:9444')) 'Candidato no separa admision'
    Require-KZ ($cand.Contains('header_up X-Admission-Client-IP {remote_host}')) 'Identidad IP no atestada'
    Require-KZ (-not $cand.Contains('8.8.8.8')) 'IP sintetica CI no debe entrar en AWS'
    Require-KZ ($virtual.Contains('"canDrive": False')) 'Sidecar no certificado virtual-only'
    Require-KZ ($installer.Contains('Get-VehicleTaskNames')) 'Instalador legacy debe usar sus tareas originales'
    Require-KZ (-not $installer.Contains('VehiculoIoT-Admission-Virtual')) 'Instalador legacy no debe registrar tercera tarea'
    # Se valida la estructura, NO se asume que el servidor EC2 la cumple.
    if ($Mode -eq 'Plan') {
        if ([string]::IsNullOrWhiteSpace($StateDirectory)) {
            $StateDirectory = Join-Path $env:ProgramData 'VehiculoIoT'
        }
        $state = [IO.Path]::GetFullPath($StateDirectory).TrimEnd('\')
        $base = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
        Require-KZ ($state.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) 'Directorio fuera de ProgramData'
        Write-Output '[K-Z] PROPUESTA: tercera tarea VehiculoIoT-Admission-Virtual, LocalService, sin privilegios admin.'
        Write-Output '[K-Z] PROPUESTA: datos y credenciales privadas separados, con ACL Administrators/SYSTEM/LocalService.'
        Write-Output '[K-Z] PROPUESTA: sidecar 127.0.0.1:9444, un proceso, sin RDS ni rutas de movimiento.'
        Write-Output '[K-Z] PROPUESTA: Caddy 8000 intacto, admision opcional 9444 tras validacion.'
        Write-Output '[K-Z] NO-GO: no hay tarea EC2, secretos instalados, proxy auditado ni rollback real ensayado.'
    }
    else {
        Write-Output '[K-Z] Contratos de repositorio validados, solo lectura.'
    }
    Write-Output '[K-Z] No se instaló nada. EC2, RDS y motores fuera de pruebas.'
    exit 0
}
catch {
    Write-Output '[K-Z] NO-GO: preflight falló; sin cambios al host.'
    exit 2
}
