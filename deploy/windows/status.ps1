param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
Assert-VehicleTaskOwnership $StateDirectory
$names = Get-VehicleTaskNames
for ($index = 0; $index -lt $names.Count; $index++) {
    $task = Get-ScheduledTask -TaskName $names[$index] -TaskPath '\' -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        [pscustomobject]@{ Task = $names[$index]; State = 'NotInstalled'; Process = $null; LastResult = $null }
        continue
    }
    $info = $task | Get-ScheduledTaskInfo
    $component = @('api', 'caddy')[$index]
    $recordPath = Get-VehicleProcessRecordPath $StateDirectory $component
    $processId = $null
    if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ($null -ne $record.child -and $null -ne (Get-VehicleMatchingProcess $record.child)) {
            $processId = $record.child.process_id
        }
    }
    [pscustomobject]@{
        Task = $names[$index]
        State = $task.State
        Process = $processId
        LastResult = ('0x{0:X8}' -f [uint32]$info.LastTaskResult)
        LastRun = $info.LastRunTime
    }
}
Write-Output ('Logs y Caddyfile persistente: {0}' -f $StateDirectory)
Write-Output 'Running indica proceso/tarea; confirma salud local y HTTPS por separado.'
