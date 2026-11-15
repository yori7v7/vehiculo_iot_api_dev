# Windows PowerShell 5.1. Audit is read-only and requires no maintenance flag.
[CmdletBinding()]
param([ValidateSet('Audit','Apply')][string]$Mode = 'Audit', [switch]$ConfirmMaintenance)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$lock = $null
. (Join-Path $PSScriptRoot 'kv_v1_upgrade_transaction.ps1')
try {
    . (Join-Path $PSScriptRoot 'kv_v1_upgrade_windows.ps1')
    if ($Mode -eq 'Apply' -and -not $ConfirmMaintenance) {
        Write-Host 'NO-GO: Apply requiere una ventana confirmada con -ConfirmMaintenance.'
        exit 2
    }
    $context = Get-KVUpgradeContext
    if ($Mode -eq 'Audit') {
        Assert-KVUpgradeCandidate $context
        Assert-KVUpgradeRuntime $context
        Assert-KVUpgradeRunning $context 'Original' -SkipAuthenticated
        Write-Host 'GO: candidato, servicio original y perimetro verificados. La cola se verifica en Apply.'
        exit 0
    }
    $lock = Enter-KVTransaction $context -Create
    Assert-KVUpgradeRuntime $context
    exit (Invoke-KVUpgrade $context)
}
catch {
    Write-Host ('NO-GO: evidencia, permisos o estado inicial sin verificar. ' + (Format-KVFailure $_))
    exit 2
}
finally { if ($null -ne $lock) { $lock.Dispose() } }
