# K-Z: ensayo REAL de una tarea Windows independiente, SOLO GitHub Actions.
# Crea una tarea SIN TRIGGERS, DESHABILITADA y de nombre aleatorio.
# Nunca lanza el sidecar, nunca registra las tareas API/Caddy, nunca EC2.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT' -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'K-Z: prueba de Task Scheduler permitida solo en Windows GitHub Actions'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$plan = Join-Path $root 'deploy\staging\kw\kz_installation_plan_readonly.ps1'
$taskName = 'KZ-Virtual-CI-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$folder = Join-Path $env:RUNNER_TEMP ('kz-private-' + [guid]::NewGuid().ToString('N'))
$createdTask = $false
$baseline = @{}
$script:checks = 0

function Check-KZ([bool]$ok,[string]$label) {
    if (-not $ok) { throw ('[K-Z] FAILURE: ' + $label) }
    $script:checks++
    Write-Output ('[K-Z] OK: ' + $label)
}
function Hash-KZ([string]$path) {
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
function Snapshot-Legacy {
    foreach ($path in @(
        'deploy\windows\Caddyfile',
        'deploy\windows\install.ps1',
        'deploy\windows\run_api.ps1',
        'deploy\windows\run_caddy.ps1',
        'app\main.py'
    )) { $script:baseline[$path] = Hash-KZ (Join-Path $root $path) }
}
function Assert-LegacyNotModified {
    foreach ($path in @($script:baseline.Keys)) {
        Check-KZ ((Hash-KZ (Join-Path $root $path)) -eq $script:baseline[$path]) ('legacy intacto: ' + $path)
    }
}
function Get-KZTask {
    return Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
}
Snapshot-Legacy

try {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        $plan, [ref]$tokens, [ref]$errors
    )
    Check-KZ ($errors.Count -eq 0) 'PowerShell 5.1: sintaxis del plan correcta'
    & $powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $plan -Mode VerifyRepository
    Check-KZ ($LASTEXITCODE -eq 0) 'plan de tercera tarea validado sin cambios'
    Check-KZ ($null -eq (Get-KZTask)) 'nombre de prueba no existía'

    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @(
        'S-1-5-18',      # SYSTEM
        'S-1-5-19',      # LOCAL SERVICE: identidad de menor privilegio
        'S-1-5-32-544', # Administradores
        ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    ) | Select-Object -Unique) {
        $sid = New-Object Security.Principal.SecurityIdentifier($sidValue)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $folder -AclObject $acl
    $rules = @( (Get-Acl -LiteralPath $folder).GetAccessRules(
        $true, $true, [Security.Principal.SecurityIdentifier]
    ))
    $writeMask = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions
    foreach ($ordinary in @('S-1-1-0','S-1-5-11','S-1-5-32-545')) {
        $unsafe = @($rules | Where-Object {
            $_.IdentityReference.Value -eq $ordinary -and
            $_.AccessControlType -eq 'Allow' -and
            ($_.FileSystemRights -band $writeMask) -ne 0
        })
        Check-KZ ($unsafe.Count -eq 0) ('ACL sin escritura usuario comun: ' + $ordinary)
    }
    Check-KZ (@($rules | Where-Object {
        $_.IdentityReference.Value -eq 'S-1-5-19' -and
        $_.AccessControlType -eq 'Allow'
    }).Count -eq 1) 'ACL concede servicio LocalService'
    Check-KZ ((Get-Acl -LiteralPath $folder).AreAccessRulesProtected) 'ACL sin herencia'

    # Manifest: SOLO hashes del archivo original y plantilla, NO secretos.
    $manifest = [ordered]@{
        schema = 1
        environment = 'github-actions-test-only'
        task_name = $taskName
        original_caddy_hash = $baseline['deploy\windows\Caddyfile']
        candidate_hash = Hash-KZ (Join-Path $root 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY')
        virtual_only = $true
    }
    $manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $folder 'manifest.json') -Encoding UTF8

    # Registramos SOLO una tarea ficticia, SIN trigger y SIN arrancarla.
    # La accion es inofensiva: plan de solo lectura, NO la API ni el sidecar.
    # Prototipo de principal aislado que luego requerira revision en EC2.
    $action = New-ScheduledTaskAction -Execute $powershell -WorkingDirectory $root -Argument (
        '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        $plan + '" -Mode VerifyRepository'
    )
    $principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCAL SERVICE' -LogonType ServiceAccount -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Principal $principal -Settings $settings -Description 'K-Z CI: task dummy, nunca se ejecuta' | Out-Null
    $createdTask = $true
    Disable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
    $registered = Get-KZTask
    Check-KZ ($null -ne $registered) 'Task Scheduler registra tarea independiente'
    Check-KZ ($registered.State -eq 'Disabled') 'tarea de CI queda deshabilitada'
    Check-KZ (@($registered.Triggers).Count -eq 0) 'tarea de CI no tiene triggers'
    Check-KZ ($registered.Actions.Count -eq 1) 'acción única validada'
    Check-KZ ($registered.Actions[0].Execute -eq $powershell) 'acción no llama al backend legacy'
    $user = $registered.Principal.UserId
    Check-KZ ($user -in @('NT AUTHORITY\LOCAL SERVICE','S-1-5-19','LOCAL SERVICE')) 'principal LocalService, no SYSTEM'
    Check-KZ ((Get-Content -LiteralPath (Join-Path $folder 'manifest.json') -Raw | ConvertFrom-Json).virtual_only -eq $true) 'manifest virtual, no desplegado'
    Assert-LegacyNotModified

    Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
    $createdTask = $false
    Check-KZ ($null -eq (Get-KZTask)) 'reversion retira solamente tarea ficticia'
    Assert-LegacyNotModified
    Write-Output ('[K-Z] RESULTADO: ' + $script:checks + ' verificaciones; LocalService/ACL/tarea/reversion CI')
}
finally {
    if ($createdTask) {
        try { Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false }
        catch { }
    }
    if (Test-Path -LiteralPath $folder) {
        Remove-Item -LiteralPath $folder -Recurse -Force
    }
}
exit 0
