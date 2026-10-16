# Native Windows checks with a fake Task Scheduler. No task is registered and
# no .env is read. All generated files and compiler temporary files stay here.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$deployment = Join-Path $root 'deploy\windows'
. (Join-Path $deployment 'common.ps1')
$temporary = Join-Path $root ('.windows-deployment-checks-' + [guid]::NewGuid().ToString('N') + '.tmp')
New-Item -ItemType Directory -Path $temporary | Out-Null
$savedEnvironment = @{ TEMP = $env:TEMP; TMP = $env:TMP; ProgramData = $env:ProgramData }
$env:TEMP = $temporary
$env:TMP = $temporary
$env:ProgramData = $temporary
$script:checks = 0
$supervisor = $null

function Assert-Check {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('FAILED: ' + $Message) }
    $script:checks++
}

try {
    foreach ($file in (Get-ChildItem -LiteralPath $deployment -Filter '*.ps1')) {
        $tokens = $null
        $parseErrors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
        Assert-Check ($parseErrors.Count -eq 0) ('PowerShell syntax: ' + $file.Name)
    }
    $mask = Get-VehicleWriteRightsMask
    Assert-Check (([Security.AccessControl.FileSystemRights]::ReadAndExecute -band $mask) -eq 0) 'Users read/execute is permitted'
    Assert-Check (([Security.AccessControl.FileSystemRights]::Modify -band $mask) -ne 0) 'Users modify is rejected'
    Assert-Check (([Security.AccessControl.FileSystemRights]::ChangePermissions -band $mask) -ne 0) 'Users changing ACL is rejected'
    $badDirectoryRejected = $false
    try { $null = Get-VehicleStateDirectory $root } catch { $badDirectoryRejected = $true }
    Assert-Check $badDirectoryRejected 'State ACL cannot be applied outside a dedicated ProgramData child'

    # Actual child-process tests exercise quoting, exit propagation and the
    # native job when a supervisor is killed before it can execute finally.
    $state = Join-Path $temporary 'process state with spaces'
    New-Item -ItemType Directory -Path (Join-Path $state 'logs'), (Join-Path $state 'run') -Force | Out-Null
    $wrapper = Join-Path $temporary 'supervisor.ps1'
    @'
param([string]$Common, [string]$State, [string]$Payload)
. $Common
exit (Invoke-VehicleProcess $State 'probe' (Get-VehiclePowerShell) @('-NoProfile', '-NonInteractive', '-File', $Payload))
'@ | Set-Content -LiteralPath $wrapper -Encoding UTF8
    $payload = Join-Path $temporary 'payload with spaces.ps1'
    $powershell = Get-VehiclePowerShell
    $common = Join-Path $deployment 'common.ps1'
    foreach ($expected in @(1, 7)) {
        $requested = $expected
        if ($expected -eq 1) { $requested = 0 }
        ('exit ' + $requested) | Set-Content -LiteralPath $payload -Encoding UTF8
        & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $wrapper -Common $common -State $state -Payload $payload
        Assert-Check ($LASTEXITCODE -eq $expected) ('Server exit propagated, including zero-to-failure: ' + $expected)
    }
    'Start-Sleep -Seconds 120' | Set-Content -LiteralPath $payload -Encoding UTF8
    $wrapperArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $wrapper,
        '-Common', $common, '-State', $state, '-Payload', $payload)
    $nativeArguments = ($wrapperArguments | ForEach-Object { ConvertTo-VehicleNativeArgument $_ }) -join ' '
    $supervisor = Start-Process -FilePath $powershell -ArgumentList $nativeArguments -WindowStyle Hidden -PassThru
    $recordPath = Get-VehicleProcessRecordPath $state 'probe'
    $record = $null
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        if (Test-Path -LiteralPath $recordPath) {
            $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
            if ($null -ne $record.child) { break }
        }
        Start-Sleep -Milliseconds 100
    }
    Assert-Check ($null -ne $record -and $null -ne $record.child) 'Child registered for abrupt-supervisor test'
    Stop-Process -Id $supervisor.Id -Force
    $supervisor.WaitForExit()
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($null -eq (Get-VehicleMatchingProcess $record.child)) { break }
        Start-Sleep -Milliseconds 100
    }
    Assert-Check ($null -eq (Get-VehicleMatchingProcess $record.child)) 'Job kills child after abrupt supervisor termination'
    $supervisor.Dispose()

    # Fake only OS boundaries; installer and lifecycle logic run unchanged.
    $script:tasks = @{}
    $script:events = New-Object 'System.Collections.Generic.List[string]'
    $script:registrations = 0
    function Assert-VehicleAdministrator { }
    function Protect-VehicleStateDirectory { param($StateDirectory) }
    function Test-VehicleCaddyConfiguration { param($Executable, $ConfigurationPath) }
    function Test-Path {
        [CmdletBinding()]param($LiteralPath, $PathType)
        if ($LiteralPath -eq (Join-Path $root '.env') -or
            $LiteralPath -eq (Join-Path $root '.certs\rds-global-bundle.pem')) { return $true }
        return Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
    }
    function Get-Acl {
        param($LiteralPath)
        $acl = [pscustomobject]@{}
        $acl | Add-Member ScriptMethod GetAccessRules {
            param($Explicit, $Inherited, $IdentityType)
            return [pscustomobject]@{
                AccessControlType = 'Allow'
                IdentityReference = [pscustomobject]@{ Value = 'S-1-5-32-545' }
                FileSystemRights = [Security.AccessControl.FileSystemRights]::ReadAndExecute
            }
        }
        return $acl
    }
    function Get-ScheduledTask {
        [CmdletBinding()]param($TaskName, $TaskPath)
        if ($script:tasks.ContainsKey($TaskName)) { return $script:tasks[$TaskName] }
    }
    function Disable-ScheduledTask {
        param([Parameter(ValueFromPipeline = $true)]$InputObject)
        process { $script:events.Add('disable:' + $InputObject.TaskName); $InputObject.State = 'Disabled'; $InputObject }
    }
    function Stop-ScheduledTask {
        param([Parameter(ValueFromPipeline = $true)]$InputObject)
        process { $script:events.Add('stop:' + $InputObject.TaskName) }
    }
    function Enable-ScheduledTask {
        param([Parameter(ValueFromPipeline = $true)]$InputObject)
        process { $script:events.Add('enable:' + $InputObject.TaskName); if ($InputObject.State -ne 'Running') { $InputObject.State = 'Ready' }; $InputObject }
    }
    function Start-ScheduledTask {
        param($TaskName, $TaskPath)
        $script:events.Add('start:' + $TaskName)
        $script:tasks[$TaskName].State = 'Running'
    }
    function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) return [pscustomobject]$PSBoundParameters }
    function New-ScheduledTaskTrigger { param([switch]$AtStartup) return [pscustomobject]@{ Delay = ''; AtStartup = $AtStartup.IsPresent } }
    function New-ScheduledTaskSettingsSet {
        param($ExecutionTimeLimit, $RestartCount, $RestartInterval, $MultipleInstances,
            [switch]$StartWhenAvailable, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries)
        return [pscustomobject]$PSBoundParameters
    }
    function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) return [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
    function Register-ScheduledTask {
        param($TaskName, $TaskPath, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force)
        $script:registrations++
        $script:tasks[$TaskName] = [pscustomobject]@{
            TaskName = $TaskName; Actions = @($Action); State = 'Ready'; Trigger = $Trigger; Principal = $Principal; Settings = $Settings
        }
    }

    # Bootstrap is excluded only to retain OS mocks when common.ps1 is sourced.
    # The actual installer AST, including validations, copying and task settings,
    # is executed twice against this repository-contained mock ProgramData.
    $tokens = $null
    $parseErrors = $null
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $deployment 'install.ps1'), [ref]$tokens, [ref]$parseErrors)
    $body = $installerAst.EndBlock.Statements | Select-Object -Skip 1
    $bodyText = ($body | ForEach-Object { $_.Extent.Text }) -join "`n"
    $installer = [ScriptBlock]::Create($bodyText.Replace('$PSScriptRoot', '$deployment'))
    $CaddyPath = Join-Path $temporary 'caddy.exe'
    'fake public executable for copy checks' | Set-Content -LiteralPath $CaddyPath -Encoding ASCII
    $StateDirectory = Join-Path $temporary 'VehiculoIoT'
    # Preserve the template path when executing a file AST as a script block.
    & { . $installer } | Out-Null
    Assert-Check ($script:tasks.Count -eq 2) 'First install registers exactly two tasks'
    $deployedCaddyfile = Join-Path $StateDirectory 'Caddyfile'
    Add-Content -LiteralPath $deployedCaddyfile -Value '# operator customization retained'
    $preservedCaddyfile = Get-Content -LiteralPath $deployedCaddyfile -Raw
    $marker = Join-Path $StateDirectory 'caddy-data\retained-certificate-marker'
    'retain' | Set-Content -LiteralPath $marker
    & { . $installer } | Out-Null
    Assert-Check ($script:tasks.Count -eq 2 -and $script:registrations -eq 4) 'Reinstall updates the same task names without duplicates'
    Assert-Check ((Get-Content -LiteralPath $deployedCaddyfile -Raw) -eq $preservedCaddyfile) 'Reinstall preserves operator Caddyfile'
    Assert-Check (Test-Path -LiteralPath $marker) 'Reinstall preserves TLS state'
    foreach ($task in $script:tasks.Values) {
        Assert-Check ($task.Principal.UserId -eq 'SYSTEM' -and $task.Principal.LogonType -eq 'ServiceAccount') 'Task runs without an interactive login'
        Assert-Check ($task.Settings.ExecutionTimeLimit -eq [TimeSpan]::Zero -and $task.Settings.RestartCount -eq 999) 'Task has no time limit and retries failures'
        Assert-Check ($task.Settings.MultipleInstances -eq 'IgnoreNew' -and $task.Trigger.AtStartup) 'Task starts at boot and cannot duplicate itself'
    }
    $script:events.Clear()
    Stop-VehicleDeployment $StateDirectory
    Assert-Check (@($script:tasks.Values | Where-Object { $_.State -ne 'Disabled' }).Count -eq 0) 'Stop leaves both tasks disabled'
    Assert-Check ($script:events[0].StartsWith('disable:') -and $script:events[1].StartsWith('disable:')) 'Stop prevents pending restarts before termination'
    Start-VehicleDeployment $StateDirectory
    Start-VehicleDeployment $StateDirectory
    Assert-Check (@($script:events | Where-Object { $_.StartsWith('start:') }).Count -eq 2) 'Repeated start keeps a single running task per component'
    $script:tasks['VehiculoIoT-Caddy'].Actions[0].Arguments = 'unrelated task'
    $before = $script:events.Count
    $foreignRejected = $false
    try { Stop-VehicleDeployment $StateDirectory } catch { $foreignRejected = $true }
    Assert-Check ($foreignRejected -and $script:events.Count -eq $before) 'Foreign task is rejected before mutation'
    Write-Output ('Windows deployment checks passed: {0}; no real scheduled tasks or external state created.' -f $script:checks)
}
finally {
    if ($null -ne $supervisor) {
        try {
            if (-not $supervisor.HasExited) { $supervisor.Kill(); $supervisor.WaitForExit() }
            $supervisor.Dispose()
        }
        catch { }
    }
    $env:TEMP = $savedEnvironment.TEMP
    $env:TMP = $savedEnvironment.TMP
    $env:ProgramData = $savedEnvironment.ProgramData
    $resolved = [IO.Path]::GetFullPath($temporary)
    if ($resolved.StartsWith($root + '\.windows-deployment-checks-', [StringComparison]::OrdinalIgnoreCase) -and
        $resolved.EndsWith('.tmp')) {
        for ($cleanupAttempt = 0; $cleanupAttempt -lt 10; $cleanupAttempt++) {
            try { Remove-Item -LiteralPath $resolved -Recurse -Force; break }
            catch {
                if ($cleanupAttempt -eq 9) { Write-Warning ('Test temporary files could not yet be removed: ' + $resolved) }
                else { Start-Sleep -Milliseconds 100 }
            }
        }
    }
}
