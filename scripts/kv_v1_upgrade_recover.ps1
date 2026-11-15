# Independent operator entry point. Recover code only, preserving live SQLite.
[CmdletBinding()]
param([switch]$ConfirmMaintenance)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$lock = $null
. (Join-Path $PSScriptRoot 'kv_v1_upgrade_transaction.ps1')
try {
    if (-not $ConfirmMaintenance) {
        Write-Host 'NO-GO: recuperacion requiere -ConfirmMaintenance.'
        exit 2
    }
    . (Join-Path $PSScriptRoot 'kv_v1_upgrade_windows.ps1')
    $context = Get-KVUpgradeContext
    $lock = Enter-KVTransaction $context
    Invoke-KVRecovery $context
    Write-Host 'GO: version anterior verificada. SQLite actual conservada.'
    exit 0
}
catch {
    Write-Host ('NO-GO: recuperacion sin verificar. ' + (Format-KVFailure $_))
    Write-Host 'Conserva la evidencia. No arranques la tarea ni restaures SQLite manualmente.'
    exit 2
}
finally { if ($null -ne $lock) { $lock.Dispose() } }
