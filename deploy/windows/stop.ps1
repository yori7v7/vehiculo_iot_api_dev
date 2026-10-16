param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
$null = Get-VehicleConfiguration $StateDirectory
Stop-VehicleDeployment $StateDirectory
Write-Output 'Tareas detenidas y deshabilitadas hasta ejecutar start.ps1; se conservaron datos y certificados.'
