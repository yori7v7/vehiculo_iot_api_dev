# K-AB: Staging launcher real en Task Scheduler, SOLO runner Windows CI.
# Todo en RUNNER_TEMP; secretos sintéticos; no toca EC2/Caddy/legacy.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT') {
    throw 'K-AB: Windows GitHub Actions solamente.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$python = (Get-Command python.exe -ErrorAction Stop).Source
$parent = Join-Path $env:RUNNER_TEMP ('kab-run-' + [guid]::NewGuid().ToString('N'))
$private = Join-Path $parent 'kab-private'
$task = 'KAB-CI-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$legacy = $null
$registered = $false
$script:checks = 0
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Check-KAB([bool]$yes, [string]$label) {
    if (-not $yes) { throw ('[K-AB] FAIL: ' + $label) }
    $script:checks++
    Write-Output ('[K-AB] OK: ' + $label)
}
function Task-KAB {
    return Get-ScheduledTask -TaskName $task -TaskPath '\' -ErrorAction SilentlyContinue
}
function Secure-KAB([string]$path, [bool]$directory) {
    if($directory) { $acl=New-Object Security.AccessControl.DirectorySecurity }
    else { $acl=New-Object Security.AccessControl.FileSecurity }
    $acl.SetAccessRuleProtection($true,$false)
    $admin=New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $acl.SetOwner($admin)
    foreach($sid in @('S-1-5-18','S-1-5-19','S-1-5-32-544')) {
        $identity=New-Object Security.Principal.SecurityIdentifier($sid)
        $inherit=if($directory){'ContainerInherit,ObjectInherit'}else{'None'}
        $rule=New-Object Security.AccessControl.FileSystemAccessRule(
            $identity,'FullControl',$inherit,'None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl
}
function Write-PrivateKAB([string]$path, [string]$value) {
    [IO.File]::WriteAllText($path,$value,$utf8)
    Secure-KAB $path $false
}
function Token-KAB {
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes=New-Object byte[] 48
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_').TrimEnd('=')
    }
    finally { $rng.Dispose() }
}
function Listening-KAB([int]$port) {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
}
function Http-KAB([int]$port, [string]$route, [hashtable]$headers=@{}) {
    $request=[Net.HttpWebRequest][Net.WebRequest]::Create(
        ('http://127.0.0.1:{0}{1}' -f $port,$route))
    $request.Method='GET'
    $request.Proxy=$null
    $request.Timeout=1600
    $request.ReadWriteTimeout=1600
    foreach($key in $headers.Keys) {
        if($key -eq 'Host') { $request.Host=$headers[$key] }
        else { $request.Headers[$key]=$headers[$key] }
    }
    $response=$null
    try { $response=$request.GetResponse() }
    catch [Net.WebException] {
        $response=$_.Exception.Response
        if($null -eq $response){ throw }
    }
    try { return [int]$response.StatusCode }
    finally { $response.Close() }
}
function Action-KAB([string]$mode) {
    $argument = '-m scripts.kab_ci_direct --runner "' + $env:RUNNER_TEMP +
        '" --state "' + $private + '" --mode ' + $mode
    return New-ScheduledTaskAction -Execute $python -WorkingDirectory $root -Argument $argument
}
function Wait-KABExit([int]$expect) {
    for($i=0;$i -lt 80;$i++) {
        $status=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $task
        $state=(Task-KAB).State
        if($state -eq 'Ready' -and $status.LastTaskResult -eq $expect) { return $true }
        if($state -eq 'Ready' -and $status.LastTaskResult -notin @(267009,267011,$expect)) { return $false }
        Start-Sleep -Milliseconds 200
    }
    return $false
}
try {
    Check-KAB (-not (Listening-KAB 9444)) '9444 libre antes de iniciar'
    Check-KAB (-not (Listening-KAB 8000)) '8000 libre para dummy'
    New-Item -ItemType Directory -Path $private -Force | Out-Null
    Secure-KAB $private $true
    New-Item -ItemType Directory -Path (Join-Path $private 'secrets') | Out-Null
    Secure-KAB (Join-Path $private 'secrets') $true

    $admin=Token-KAB
    $proxy=Token-KAB
    $manifest=[ordered]@{
        schema_version=1
        mode='virtual_staging'
        service_sid='S-1-5-19'
        bind_host='127.0.0.1'
        bind_port=9444
        database_name='tickets.sqlite3'
        enabled=$false
    }
    $manifestPath=Join-Path $private 'staging.json'
    Write-PrivateKAB $manifestPath ($manifest | ConvertTo-Json)
    Write-PrivateKAB (Join-Path $private 'KAB_CI_ONLY.marker') ("KAB-CI-ISOLATED" + "`n")
    Write-PrivateKAB (Join-Path $private 'secrets\admin.proof') $admin
    Write-PrivateKAB (Join-Path $private 'secrets\proxy.proof') $proxy

    $acl=Get-Acl -LiteralPath $private
    Check-KAB $acl.AreAccessRulesProtected 'sin herencia de ACL'
    Check-KAB ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-544') 'dueño Administradores'
    $allowed=@('S-1-5-18','S-1-5-19','S-1-5-32-544')
    $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    Check-KAB (@($rules | Where-Object { $_.AccessControlType -eq 'Allow' -and
        $_.IdentityReference.Value -notin $allowed }).Count -eq 0) 'sin ACE de usuario general'

    $legacy=Start-Process -FilePath $python -WorkingDirectory $root -PassThru `
        -ArgumentList '-m http.server 8000 --bind 127.0.0.1' `
        -RedirectStandardOutput (Join-Path $parent 'legacy.out') `
        -RedirectStandardError (Join-Path $parent 'legacy.err')
    $live=$false
    for($i=0;$i -lt 50;$i++) {
        try { if((Http-KAB 8000 '/') -eq 200){ $live=$true;break } } catch {}
        Start-Sleep -Milliseconds 200
    }
    Check-KAB $live 'dummy legacy 8000 operativo'

    $principal=New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCAL SERVICE' `
        -LogonType ServiceAccount -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskPath '\' -TaskName $task -Action (Action-KAB 'preflight') `
        -Principal $principal -Settings $settings -Description 'K-AB: staging virtual exclusivamente CI' | Out-Null
    $registered=$true
    $entry=Task-KAB
    Check-KAB ($entry.Principal.UserId -in @('S-1-5-19','NT AUTHORITY\LOCAL SERVICE','LOCAL SERVICE')) 'principal LocalService real'
    Check-KAB (@($entry.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) 'sin activadores'

    Start-ScheduledTask -TaskPath '\' -TaskName $task
    Check-KAB (Wait-KABExit 0) 'preflight de archivos/identidad bajo LocalService'
    Check-KAB (-not (Listening-KAB 9444)) 'preflight no inicia FastAPI'

    $null=Set-ScheduledTask -TaskPath '\' -TaskName $task -Action (Action-KAB 'serve')
    Start-ScheduledTask -TaskPath '\' -TaskName $task
    Check-KAB (Wait-KABExit 2) 'enabled=false bloquea el arranque'
    Check-KAB (-not (Listening-KAB 9444)) 'sin listener tras NO-GO'

    # Simular autorización del administrador dentro del fixture efímero.
    $manifest.enabled=$true
    Write-PrivateKAB $manifestPath ($manifest | ConvertTo-Json)
    Start-ScheduledTask -TaskPath '\' -TaskName $task
    $ready=$false
    for($i=0;$i -lt 90;$i++) {
        try { if((Http-KAB 9444 '/') -eq 404){ $ready=$true;break } } catch {}
        Start-Sleep -Milliseconds 250
    }
    if(-not $ready) {
        $status=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $task -ErrorAction SilentlyContinue
        $exitCode=if($null -eq $status){'unknown'}else{[string]$status.LastTaskResult}
        Write-Output ('[K-AB] NO-GO: sidecar no inició. Código task=' + $exitCode)
    }
    Check-KAB $ready 'FastAPI virtual real bajo LocalService'
    Check-KAB ((Http-KAB 9444 '/docs') -eq 404) 'sin Swagger'
    Check-KAB ((Http-KAB 9444 '/vehiculos/1/movimientos') -eq 404) 'sin motores'
    Check-KAB ((Http-KAB 9444 '/admin/vehiculos/1/control-publico/solicitudes') -eq 403) 'sin proxy autenticado devuelve 403'
    $headers=@{
        'Host'='100-30-4-62.nip.io'
        'Origin'='https://yori7v7.github.io'
        'X-Admission-Proxy-Token'=$proxy
        'X-Admission-Client-IP'='8.8.8.8'
        'X-Admission-Scheme'='https'
        'X-API-Key'=$admin
    }
    Check-KAB ((Http-KAB 9444 '/admin/vehiculos/1/control-publico/solicitudes' $headers) -eq 200) 'admin virtual autorizado'
    Check-KAB ((Http-KAB 8000 '/') -eq 200) 'legacy dummy sin interrupción'

    Stop-ScheduledTask -TaskPath '\' -TaskName $task
    $down=$false
    for($i=0;$i -lt 60;$i++) {
        if(-not (Listening-KAB 9444)){ $down=$true;break }
        Start-Sleep -Milliseconds 200
    }
    Check-KAB $down 'parar tarea mata Python directo'
    Check-KAB ((Http-KAB 8000 '/') -eq 200) 'legacy intacto tras STOP'
    Disable-ScheduledTask -TaskPath '\' -TaskName $task | Out-Null
    Check-KAB ((Task-KAB).State -eq 'Disabled') 'tarea deshabilitada'
    Unregister-ScheduledTask -TaskPath '\' -TaskName $task -Confirm:$false
    $registered=$false
    Check-KAB ($null -eq (Task-KAB)) 'rollback solo tarea K-AB'
    Check-KAB ((Http-KAB 8000 '/') -eq 200) 'legacy intacto tras rollback'
    Write-Output ('[K-AB] RESULTADO: ' + $script:checks +
        ' comprobaciones; seguro solo CI, SIN EC2.')
}
finally {
    if($registered) {
        try { Stop-ScheduledTask -TaskPath '\' -TaskName $task -ErrorAction SilentlyContinue } catch {}
        try { Unregister-ScheduledTask -TaskPath '\' -TaskName $task -Confirm:$false } catch {}
    }
    if($null -ne $legacy) {
        try { if(-not $legacy.HasExited){ Stop-Process -Id $legacy.Id -Force;$legacy.WaitForExit() } } catch {}
        $legacy.Dispose()
    }
    if(Test-Path -LiteralPath $parent) {
        try { Remove-Item -LiteralPath $parent -Recurse -Force } catch {}
    }
}
exit 0
