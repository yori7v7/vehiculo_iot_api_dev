param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
$null = Get-VehicleConfiguration $StateDirectory
Stop-VehicleDeployment $StateDirectory
Start-VehicleDeployment $StateDirectory
Write-Output 'Se solicito reiniciar ambas tareas. Los clientes WebSocket deben reconectarse.'
