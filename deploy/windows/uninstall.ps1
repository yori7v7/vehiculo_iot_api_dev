param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
$null = Get-VehicleConfiguration $StateDirectory
Stop-VehicleDeployment $StateDirectory
foreach ($name in (Get-VehicleTaskNames)) {
    $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
    if ($null -ne $task) { $task | Unregister-ScheduledTask -Confirm:$false }
}
Write-Output 'Se eliminaron solo las dos tareas; se conservan repositorio, .env, CA, logs, configuracion y TLS.'
