# Shared helpers. Windows PowerShell 5.1 compatible; never reads .env.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-VehicleAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Ejecuta este script en PowerShell como Administrador.'
    }
}

function Get-VehicleProjectRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).ProviderPath
}

function Get-VehicleStateDirectory {
    param([string]$StateDirectory)
    if ([string]::IsNullOrWhiteSpace($StateDirectory)) {
        $StateDirectory = Join-Path $env:ProgramData 'VehiculoIoT'
    }
    $full = [IO.Path]::GetFullPath($StateDirectory).TrimEnd('\')
    $programData = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
    if (-not $full.StartsWith($programData + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'StateDirectory debe ser una subcarpeta dedicada de ProgramData.'
    }
    if ($full.IndexOfAny([char[]]@('"', "`r", "`n")) -ge 0) {
        throw 'StateDirectory contiene caracteres no admitidos.'
    }
    return $full
}

function Get-VehiclePowerShell {
    return Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
}

function Get-VehicleTaskArguments {
    param([string]$Component, [string]$StateDirectory)
    $script = Join-Path (Get-VehicleProjectRoot) ('deploy\windows\run_' + $Component + '.ps1')
    return '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -StateDirectory "{1}"' -f $script, $StateDirectory
}

function Get-VehicleTaskNames {
    return @('VehiculoIoT-FastAPI', 'VehiculoIoT-Caddy')
}

function Assert-VehicleTaskOwnership {
    param([string]$StateDirectory)
    $names = Get-VehicleTaskNames
    for ($index = 0; $index -lt $names.Count; $index++) {
        $task = Get-ScheduledTask -TaskName $names[$index] -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -eq $task) { continue }
        $component = @('api', 'caddy')[$index]
        $actions = @($task.Actions)
        if ($actions.Count -ne 1 -or
            $actions[0].Execute -ne (Get-VehiclePowerShell) -or
            $actions[0].Arguments -ne (Get-VehicleTaskArguments $component $StateDirectory)) {
            throw ('La tarea {0} pertenece a otra instalacion. No se modifica.' -f $names[$index])
        }
    }
}

function Get-VehicleConfiguration {
    param([string]$StateDirectory)
    $path = Join-Path $StateDirectory 'deployment.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'No existe deployment.json. Ejecuta install.ps1 en el servidor primero.'
    }
    $configuration = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    $root = Get-VehicleProjectRoot
    if ($configuration.schema_version -ne 1 -or
        $configuration.project_root -ne $root -or
        $configuration.state_directory -ne $StateDirectory -or
        $configuration.python_path -ne (Join-Path $root '.venv\Scripts\python.exe') -or
        $configuration.caddy_path -ne (Join-Path $StateDirectory 'bin\caddy.exe') -or
        $configuration.caddyfile_path -ne (Join-Path $StateDirectory 'Caddyfile')) {
        throw 'La configuracion persistente no corresponde a este proyecto y directorio.'
    }
    return $configuration
}

function Protect-VehicleStateDirectory {
    param([string]$StateDirectory)
    # Protect TLS private keys, runtime metadata and the staged executable.
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @('S-1-5-18', 'S-1-5-32-544')) {
        $sid = New-Object Security.Principal.SecurityIdentifier($sidValue)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $StateDirectory -AclObject $acl
}

function Get-VehicleWriteRightsMask {
    return [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
}

function Write-VehicleProcessRecord {
    param([string]$Path, $Record)
    $temporary = $Path + '.' + $PID + '.tmp'
    $Record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        [IO.File]::Replace($temporary, $Path, [NullString]::Value)
    }
    else { [IO.File]::Move($temporary, $Path) }
}

function Set-VehicleCaddyEnvironment {
    param([string]$StateDirectory)
    # Caddy appends /caddy to both XDG directories, also on Windows.
    $env:XDG_DATA_HOME = Join-Path $StateDirectory 'caddy-data'
    $env:XDG_CONFIG_HOME = Join-Path $StateDirectory 'caddy-config'
}

function Test-VehicleCaddyConfiguration {
    param([string]$Executable, [string]$ConfigurationPath)
    & $Executable validate --config $ConfigurationPath --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'Caddyfile no valido; no se reemplazaron las tareas existentes.' }
}

function Get-VehicleProcessRecordPath {
    param([string]$StateDirectory, [string]$Component)
    return Join-Path $StateDirectory ('run\' + $Component + '.json')
}

function Get-VehicleMatchingProcess {
    param($Record)
    # PID alone is unsafe after a restart: also compare creation time and image.
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f [int]$Record.process_id)
    if ($null -eq $process) { return $null }
    $created = $process.CreationDate.ToUniversalTime().Ticks.ToString()
    if ($created -ne [string]$Record.creation_ticks -or
        $process.ExecutablePath -ne [string]$Record.executable_path) {
        return $null
    }
    return $process
}

function Stop-VehicleProcessTree {
    param($Record)
    $process = Get-VehicleMatchingProcess $Record
    if ($null -eq $process) { return }
    & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $process.ProcessId /T /F 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and $null -ne (Get-VehicleMatchingProcess $Record)) {
        throw 'No se pudo detener el arbol de procesos registrado.'
    }
}

function Stop-VehicleDeployment {
    param([string]$StateDirectory)
    Assert-VehicleTaskOwnership $StateDirectory
    # Remain disabled until start.ps1, including across reboot / pending retries.
    foreach ($name in (Get-VehicleTaskNames)) {
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -ne $task) { $task | Disable-ScheduledTask | Out-Null }
    }
    # Kill each recorded supervisor tree before asking Task Scheduler to stop it.
    # The supervisor identity is recorded BEFORE creating any child process.
    foreach ($component in @('caddy', 'api')) {
        $recordPath = Get-VehicleProcessRecordPath $StateDirectory $component
        if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { continue }
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        Stop-VehicleProcessTree $record.supervisor
    }
    foreach ($name in @('VehiculoIoT-Caddy', 'VehiculoIoT-FastAPI')) {
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -ne $task) { $task | Stop-ScheduledTask }
    }
    foreach ($component in @('caddy', 'api')) {
        $recordPath = Get-VehicleProcessRecordPath $StateDirectory $component
        if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { continue }
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ($null -ne $record.child) { Stop-VehicleProcessTree $record.child }
        if ($null -ne $record.child -and $null -ne (Get-VehicleMatchingProcess $record.child)) {
            throw ('El proceso {0} sigue activo; no se inicia otra instancia.' -f $component)
        }
        Remove-Item -LiteralPath $recordPath
    }
}

function Start-VehicleDeployment {
    param([string]$StateDirectory)
    $null = Get-VehicleConfiguration $StateDirectory
    Assert-VehicleTaskOwnership $StateDirectory
    foreach ($name in (Get-VehicleTaskNames)) {
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
        $task | Enable-ScheduledTask | Out-Null
        if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName $name -TaskPath '\' }
    }
}

function ConvertTo-VehicleNativeArgument {
    param([string]$Value)
    # Windows CommandLineToArgvW quoting, including backslashes before a quote.
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-VehicleProcess {
    param([string]$StateDirectory, [string]$Component, [string]$Executable, [string[]]$Arguments)
    $root = Get-VehicleProjectRoot
    if (-not ('VehicleProcessLifetime' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'ProcessLifetime.cs')
    }
    [VehicleProcessLifetime]::Enable()
    $recordPath = Get-VehicleProcessRecordPath $StateDirectory $Component
    if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
        $previous = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ($null -ne (Get-VehicleMatchingProcess $previous.supervisor) -or
            ($null -ne $previous.child -and $null -ne (Get-VehicleMatchingProcess $previous.child))) {
            throw 'Ya existe un proceso registrado; detenerlo antes de iniciar otro.'
        }
        Remove-Item -LiteralPath $recordPath
    }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    $stdout = Join-Path $StateDirectory ('logs\' + $Component + '-' + $stamp + '.stdout.log')
    $stderr = Join-Path $StateDirectory ('logs\' + $Component + '-' + $stamp + '.stderr.log')
    $argumentString = ($Arguments | ForEach-Object { ConvertTo-VehicleNativeArgument $_ }) -join ' '
    $child = $null
    $lifecycle = Join-Path $StateDirectory ('logs\' + $Component + '-lifecycle.log')
    ('{0} supervisor_start pid={1}' -f [DateTime]::UtcNow.ToString('o'), $PID) |
        Add-Content -LiteralPath $lifecycle -Encoding UTF8
    $supervisor = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $PID)
    $record = [ordered]@{
        supervisor = [ordered]@{
            process_id = $PID
            creation_ticks = $supervisor.CreationDate.ToUniversalTime().Ticks.ToString()
            executable_path = $supervisor.ExecutablePath
        }
        child = $null
    }
    Write-VehicleProcessRecord $recordPath $record
    try {
        $child = Start-Process -FilePath $Executable -ArgumentList $argumentString -WorkingDirectory $root `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        # Windows PowerShell 5.1 otherwise can lose ExitCode after WaitForExit.
        $null = $child.Handle
        ('{0} child_start pid={1}' -f [DateTime]::UtcNow.ToString('o'), $child.Id) |
            Add-Content -LiteralPath $lifecycle -Encoding UTF8
        if (-not $child.HasExited) {
            $cimProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $child.Id)
            if ($null -ne $cimProcess) {
                $record.child = [ordered]@{
                    process_id = $child.Id
                    creation_ticks = $cimProcess.CreationDate.ToUniversalTime().Ticks.ToString()
                    executable_path = $cimProcess.ExecutablePath
                }
                Write-VehicleProcessRecord $recordPath $record
            }
        }
        $child.WaitForExit()
        $exitCode = $child.ExitCode
        ('{0} child_exit code={1}' -f [DateTime]::UtcNow.ToString('o'), $exitCode) |
            Add-Content -LiteralPath $lifecycle -Encoding UTF8
        # A server exiting normally is still unexpected: Task Scheduler must retry.
        if ($null -eq $exitCode -or $exitCode -eq 0) { $exitCode = 1 }
        return [int]$exitCode
    }
    finally {
        if ($null -ne $record.child) { Stop-VehicleProcessTree $record.child }
        if ($null -ne $child -and -not $child.HasExited) { $child.Kill(); $child.WaitForExit() }
        if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
            Remove-Item -LiteralPath $recordPath
        }
        if ($null -ne $child) { $child.Dispose() }
    }
}

function Write-VehicleFailureLog {
    param([string]$StateDirectory, [string]$Component)
    # Generic messages only: exception text could contain settings or input.
    try {
        $path = Join-Path $StateDirectory ('logs\' + $Component + '-lifecycle.log')
        ('{0} supervisor_failure; verify prerequisites, configuration and server stderr log' -f [DateTime]::UtcNow.ToString('o')) |
            Add-Content -LiteralPath $path -Encoding UTF8
    }
    catch { } # Task Scheduler still receives a failure exit code if logging fails.
}
