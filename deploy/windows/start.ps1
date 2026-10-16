param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
Start-VehicleDeployment $StateDirectory
Write-Output 'Se habilitaron y se solicito iniciar ambas tareas. Comprueba status.ps1.'
