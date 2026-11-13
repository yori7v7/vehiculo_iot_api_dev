# K-AA: Task Scheduler EJECUTA FastAPI K-Y bajo LOCAL SERVICE en CI.
# EC2/AWS/RDS y motores NO involucrados. Los datos son falsos y temporales.
# Nunca instalar en ProgramData o modificar tareas VehiculoIoT originales.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT' -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'K-AA: solo GitHub Actions Windows.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$python = (Get-Command python.exe -ErrorAction Stop).Source
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runner = Join-Path $root 'deploy\staging\kw\kaa_ci_task_runner.ps1'
$task = 'KAA-CI-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$fixture = Join-Path $env:RUNNER_TEMP ('kaa-ci-' + [guid]::NewGuid().ToString('N'))
$dummy = $null
$taskRegistered = $false
$checks = 0

function Check-KAA([bool]$ok,[string]$label) {
    if (-not $ok) { throw ('[K-AA] FAIL: ' + $label) }
    $script:checks++
    Write-Output ('[K-AA] OK: ' + $label)
}
function Get-KAATask {
    return Get-ScheduledTask -TaskPath '\' -TaskName $task -ErrorAction SilentlyContinue
}
function Get-Status([int]$port,[string]$path,[hashtable]$headers = @{}) {
    $q = [Net.HttpWebRequest][Net.WebRequest]::Create(('http://127.0.0.1:{0}{1}' -f $port,$path))
    $q.Method = 'GET'
    $q.Proxy = $null
    $q.Timeout = 1300
    $q.ReadWriteTimeout = 1300
    foreach($name in $headers.Keys) {
        if($name -eq 'Host') { $q.Host = $headers[$name] }
        else { $q.Headers[$name] = $headers[$name] }
    }
    $result = $null
    try { $result = $q.GetResponse() }
    catch [Net.WebException] {
        $result = $_.Exception.Response
        if($null -eq $result) { throw }
    }
    try { return [int]$result.StatusCode }
    finally { $result.Close() }
}
function Is-Listening([int]$port) {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
}
function RandomSecret {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes)
}
function Set-KAAPrivateAcl([string]$path) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach($sid in @(
        'S-1-5-18','S-1-5-19','S-1-5-32-544',
        ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    ) | Select-Object -Unique) {
        $principal = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl
}
function Stop-KAATask {
    if($taskRegistered) {
        $t=Get-KAATask
        if($null -ne $t) {
            try { Stop-ScheduledTask -TaskPath '\' -TaskName $task -ErrorAction SilentlyContinue } catch { }
        }
    }
}
try {
    Check-KAA (-not (Is-Listening 9444)) 'no hay sidecar previo en 9444'
    Check-KAA (-not (Is-Listening 8000)) 'no hay legacy previo en 8000'
    New-Item -ItemType Directory -Path $fixture -Force | Out-Null
    Set-KAAPrivateAcl $fixture
    $admin=RandomSecret
    $proxy=RandomSecret
    $settings=[ordered]@{
        schema_version=1; mode='virtual_ci'; bind_host='127.0.0.1';
        bind_port=9444; database_path=(Join-Path $fixture 'tickets.sqlite3');
        admin_proof=$admin; proxy_proof=$proxy
    }
    $settings | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $fixture 'private.json') -Encoding UTF8
    'CI_MARKER_ONLY' | Set-Content -LiteralPath (Join-Path $fixture 'KAA_CI_ONLY.marker')
    $acl=Get-Acl -LiteralPath $fixture
    Check-KAA $acl.AreAccessRulesProtected 'directorio privado sin ACL heredadas'
    foreach($sid in @('S-1-1-0','S-1-5-11','S-1-5-32-545')) {
        $writes=@($acl.Access | Where-Object {
            $_.IdentityReference.Value -eq $sid -and
            $_.AccessControlType -eq 'Allow' -and
            ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Write) -ne 0
        })
        Check-KAA ($writes.Count -eq 0) ('usuarios comunes sin escritura: ' + $sid)
    }
    # Legacy es un proceso dummy, no la API original. Nunca mandar POST.
    $dummy = Start-Process -FilePath $python -WorkingDirectory $root -PassThru `
        -ArgumentList '-m http.server 8000 --bind 127.0.0.1' `
        -RedirectStandardOutput (Join-Path $fixture 'legacy.stdout.log') `
        -RedirectStandardError (Join-Path $fixture 'legacy.stderr.log')
    $ready=$false
    for($i=0;$i -lt 40;$i++) {
        try { if((Get-Status 8000 '/') -eq 200) { $ready=$true; break } } catch { }
        Start-Sleep -Milliseconds 300
    }
    Check-KAA $ready 'legacy dummy en 8000 disponible'

    # Solo un task y un proceso sidecar real; sin triggers automáticos.
    $argument = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        $runner + '" -Workspace "' + $root + '" -Fixture "' + $fixture +
        '" -PythonPath "' + $python + '"'
    $action=New-ScheduledTaskAction -Execute $powershell -WorkingDirectory $root -Argument $argument
    $principal=New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCAL SERVICE' -LogonType ServiceAccount -RunLevel Limited
    $options=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskPath '\' -TaskName $task -Action $action -Principal $principal -Settings $options -Description 'K-AA CI: sidecar virtual LocalService, no trigger' | Out-Null
    $taskRegistered=$true
    $registered=Get-KAATask
    Check-KAA ($null -ne $registered) 'tarea de LocalService registrada'
    $actualTriggers=@($registered.Triggers | Where-Object { $null -ne $_ })
    Check-KAA ($actualTriggers.Count -eq 0) 'sin activación automática'
    Check-KAA ($registered.Principal.UserId -in @('S-1-5-19','NT AUTHORITY\LOCAL SERVICE','LOCAL SERVICE')) 'identidad LocalService comprobada'
    Check-KAA ($registered.State -ne 'Running') 'la tarea no se inicia al registrarla'

    Start-ScheduledTask -TaskPath '\' -TaskName $task
    $up=$false
    for($i=0;$i -lt 80;$i++) {
        try { if((Get-Status 9444 '/') -eq 404) { $up=$true; break } } catch { }
        Start-Sleep -Milliseconds 350
    }
    if(-not $up) {
        $taskInfo=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $task -ErrorAction SilentlyContinue
        $taskLive=Get-KAATask
        $taskState=if($null -eq $taskLive){'missing'}else{[string]$taskLive.State}
        $exitCode=if($null -eq $taskInfo){'unknown'}else{[string]$taskInfo.LastTaskResult}
        Write-Output ('[K-AA DIAG] state=' + $taskState + ', result=' + $exitCode)
        $file=Join-Path $fixture 'kaa-state.txt'
        if(Test-Path -LiteralPath $file) {
            foreach($phase in @(Get-Content -LiteralPath $file)) {
                if($phase -match '^(wrapper-started|python-start|python-exit-[0-9]+|wrapper-failed)$') {
                    Write-Output ('[K-AA DIAG] phase=' + $phase)
                }
            }
        }
        else { Write-Output '[K-AA DIAG] wrapper-not-reached' }
        $errFile=Join-Path $fixture 'kaa.stderr.log'
        if(Test-Path -LiteralPath $errFile) {
            $errorText=Get-Content -LiteralPath $errFile -Raw
            foreach($pattern in @('ModuleNotFoundError','PermissionError','Access is denied','No module named',
                                   'NO-GO','unable to open database file','WinError 5')) {
                if($errorText.Contains($pattern)) {
                    Write-Output ('[K-AA DIAG] classification=' + $pattern)
                }
            }
        }
    }
    Check-KAA $up 'FastAPI virtual real arranca bajo tarea LocalService en 9444'
    Check-KAA ((Get-Status 8000 '/') -eq 200) 'legacy dummy 8000 intacto tras Task Scheduler'
    Check-KAA ((Get-Status 9444 '/docs') -eq 404) 'sidecar no expone Swagger'
    Check-KAA ((Get-Status 9444 '/vehiculos/1/movimientos') -eq 404) 'sidecar no expone motores'
    Check-KAA ((Get-Status 9444 '/admin/vehiculos/1/control-publico/solicitudes') -eq 403) 'sin atestación proxy => cerrado'

    $trusted=@{
        'Host'='100-30-4-62.nip.io';
        'Origin'='https://yori7v7.github.io';
        'X-Admission-Client-IP'='8.8.8.8';
        'X-Admission-Scheme'='https';
        'X-Admission-Proxy-Token'=$proxy;
        'X-API-Key'=$admin;
    }
    Check-KAA ((Get-Status 9444 '/admin/vehiculos/1/control-publico/solicitudes' $trusted) -eq 200) 'administración virtual solo con pruebas correctas'

    Stop-KAATask
    $down=$false
    for($i=0;$i -lt 40;$i++) {
        if(-not (Is-Listening 9444)) { $down=$true; break }
        Start-Sleep -Milliseconds 250
    }
    Check-KAA $down 'detener tarea detiene sidecar sin PID huérfano'
    Check-KAA ((Get-Status 8000 '/') -eq 200) 'legacy intacto tras detener task'
    Disable-ScheduledTask -TaskPath '\' -TaskName $task | Out-Null
    Check-KAA ((Get-KAATask).State -eq 'Disabled') 'tarea deshabilitada antes de rollback'
    Unregister-ScheduledTask -TaskPath '\' -TaskName $task -Confirm:$false
    $taskRegistered=$false
    Check-KAA ($null -eq (Get-KAATask)) 'rollback retira exclusivamente la tercera tarea'
    Check-KAA ((Get-Status 8000 '/') -eq 200) 'legacy intacto después del rollback'
    Write-Output ('[K-AA] RESULTADO: ' + $checks + ' comprobaciones con tarea LocalService y sidecar real, SIN EC2.')
}
finally {
    Stop-KAATask
    if($taskRegistered) {
        try { Unregister-ScheduledTask -TaskPath '\' -TaskName $task -Confirm:$false } catch { }
    }
    if($null -ne $dummy) {
        try { if(-not $dummy.HasExited) { Stop-Process -Id $dummy.Id -Force; $dummy.WaitForExit() } } catch { }
        $dummy.Dispose()
    }
    # Eliminar el fixture y todas las credenciales sintéticas, sin logs.
    if(Test-Path -LiteralPath $fixture) {
        try { Remove-Item -LiteralPath $fixture -Recurse -Force } catch { }
    }
}
exit 0
