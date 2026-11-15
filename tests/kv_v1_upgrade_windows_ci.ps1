# Pruebas del adaptador de Windows con CIM, tareas, listeners y HTTP ficticios.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSVersion.Major -ne 5 -or
    $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Se requiere Windows PowerShell 5.1.' }
. (Join-Path $PSScriptRoot '..\scripts\kv_v1_upgrade_windows.ps1')
Add-Type -AssemblyName System.Net.Http -ErrorAction Stop

$ctx = [pscustomobject]@{
    TaskName = 'Fixture-Virtual'
    Python = 'C:\Fixture\Runtime K-V\venv\Scripts\python.exe'
    BasePython = 'C:\Fixture\Runtime K-V\python-base\python.exe'
    Launcher = 'C:\Fixture\launcher.py'
    DedicatedSid = 'S-1-5-21-1-2-3-400'
    CapturedKv = @()
}
$script:fixture = $null
$script:tests = 0

function Assert-Fixture([bool]$Condition, [string]$Label) {
    if (-not $Condition) { throw ('Fixture: ' + $Label) }
}

function Test-Fixture([string]$Label, [scriptblock]$Action, [string]$ErrorCode = '') {
    $outcome = ''
    try { & $Action }
    catch { $outcome = $_.Exception.Message }
    Assert-Fixture ($outcome -ceq $ErrorCode) ($Label + ' [' + $outcome + ']')
    $script:tests++
    Write-Output ('[K-V Windows CI] OK: ' + $Label)
}

# ACL observada en EC2: LOCAL SERVICE es RX en code/runtime y NUNCA
# en carpetas de estado, credenciales, staging de candidato o Caddy.
$rx = [Security.AccessControl.FileSystemRights]::ReadAndExecute -bor
      [Security.AccessControl.FileSystemRights]::Synchronize
$trustedReader = 'S-1-5-21-1874011428-618372525-1786715310-1003'
$base = 'C:\ProgramData\VehiculoIoT-KX-Staging'
foreach ($path in @(
    ($base + '\code'),
    ($base + '\code\app\public_control\kv_virtual_staging.py'),
    ($base + '\runtime'),
    ($base + '\runtime\venv\Scripts\python.exe')
)) {
    Test-Fixture ('LOCAL SERVICE RX limitado al arbol ' + $path) {
        Assert-Fixture (Test-KVUpgradeStagingLocalServiceRead $path $trustedReader 'S-1-5-19' $rx) 'read-only expected'
    }
}
foreach ($path in @(
    ($base + '\code-other\settings.txt'),
    ($base + '\code\..\state\secret.txt'),
    ($base + '\runtime-backup\python.exe'),
    ($base + '\code\..\..\VehiculoIoT-KX-State\service\config.json'),
    'C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE\candidate.json',
    'C:\ProgramData\VehiculoIoT\Caddyfile'
)) {
    Test-Fixture ('LOCAL SERVICE RX rechazado fuera del arbol ' + $path) {
        Assert-Fixture (-not (Test-KVUpgradeStagingLocalServiceRead $path $trustedReader 'S-1-5-19' $rx)) 'must reject scope'
    }
}
foreach ($rights in @(
    [Security.AccessControl.FileSystemRights]::Modify,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.FileSystemRights]::ReadData,
    ([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Write)
)) {
    Test-Fixture ('LOCAL SERVICE rechaza privilegios o derechos divergentes ' + $rights) {
        Assert-Fixture (-not (Test-KVUpgradeStagingLocalServiceRead ($base + '\code') $trustedReader 'S-1-5-19' $rights)) 'unexpected rights blocked'
    }
}
Test-Fixture 'LOCAL SERVICE rechaza lector no dedicado' {
    Assert-Fixture (-not (Test-KVUpgradeStagingLocalServiceRead ($base + '\code') 'S-1-5-20' 'S-1-5-19' $rx)) 'reader SID'
}
Test-Fixture 'LOCAL SERVICE rechaza otra identidad' {
    Assert-Fixture (-not (Test-KVUpgradeStagingLocalServiceRead ($base + '\code') $trustedReader 'S-1-5-20' $rx)) 'foreign SID'
}

function Reset-Fixture {
    $date = [datetime]::UtcNow.AddMinutes(-1)
    $command = '"' + $ctx.Python + '" -B -I "' + $ctx.Launcher + '" '
    $script:fixture = [ordered]@{
        Rows = @(
            [pscustomobject]@{ExecutablePath=$ctx.Python; CreationDate=$date; ProcessId=4100; ParentProcessId=4000; CommandLine=$command; Sid=$ctx.DedicatedSid},
            [pscustomobject]@{ExecutablePath=$ctx.BasePython; CreationDate=$date.AddSeconds(1); ProcessId=4200; ParentProcessId=4100; CommandLine=$command; Sid=$ctx.DedicatedSid}
        )
        Listeners = @([pscustomobject]@{LocalPort=9444;LocalAddress='127.0.0.1';OwningProcess=4200})
        State = 'Running'
        Operations = @()
        Countdown = 0
        InvalidPair = $false
        Verified = ''
    }
    $ctx.CapturedKv = @()
}

function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [string]$Filter)
    Assert-Fixture ($ClassName -ceq 'Win32_Process') 'CIM strictly mocked'
    if ($Filter) {
        Assert-Fixture ($Filter -cmatch '^ProcessId = ([0-9]+)$') 'process filter'
        $processIdValue = [int]$Matches[1]
        return $script:fixture.Rows | Where-Object ProcessId -eq $processIdValue
    }
    return $script:fixture.Rows
}

function Invoke-CimMethod {
    [CmdletBinding()]
    param($InputObject, [string]$MethodName)
    Assert-Fixture ($MethodName -ceq 'GetOwnerSid') 'owner CIM'
    return [pscustomobject]@{ReturnValue=0;Sid=$InputObject.Sid}
}

function Get-KVUpgradeListeners { return $script:fixture.Listeners }
function Get-KVUpgradeTask { return [pscustomobject]@{State=$script:fixture.State} }

Reset-Fixture
Test-Fixture '9444 es del interprete base subordinado al lanzador' {
    Assert-KVUpgradeListenerOwner $ctx
}
Reset-Fixture
$script:fixture.Rows = @($script:fixture.Rows[0])
$script:fixture.Listeners[0].OwningProcess = 4100
Test-Fixture '9444 admite solamente la imagen del lanzador en modo directo' { Assert-KVUpgradeListenerOwner $ctx }
Reset-Fixture
$script:fixture.Listeners[0].LocalAddress = '0.0.0.0'
Test-Fixture '9444 publico se rechaza' { Assert-KVUpgradeListenerOwner $ctx } 'KV_KV_LISTENER'
Reset-Fixture
$script:fixture.Rows[1].CommandLine = $script:fixture.Rows[1].CommandLine.Replace('-B','-b')
Test-Fixture 'los flags exactos de Python importan' { Assert-KVUpgradeListenerOwner $ctx } 'KV_KV_COMMAND'
Reset-Fixture
$script:fixture.Rows[1].Sid = 'S-1-5-18'
Test-Fixture '9444 con proceso bajo otro propietario se rechaza' { Assert-KVUpgradeListenerOwner $ctx } 'KV_PROCESS_OWNER'
Reset-Fixture
$script:fixture.Rows[1].ParentProcessId = 4121
Test-Fixture 'no se admite un proceso Python ajeno a la cadena' { Assert-KVUpgradeListenerOwner $ctx } 'KV_KV_PROCESS_CHAIN'
Reset-Fixture
$script:fixture.Listeners += $script:fixture.Listeners[0]
Test-Fixture 'dos listeners en 9444 se rechazan' { Assert-KVUpgradeListenerOwner $ctx } 'KV_KV_LISTENER'

function Disable-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath,[string]$TaskName)
    Assert-Fixture ($TaskPath -ceq '\' -and $TaskName -ceq $ctx.TaskName) 'mock task target'
    $script:fixture.Operations += 'Disabled'
    $script:fixture.State = 'Disabled'
}
function Stop-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath,[string]$TaskName)
    Assert-Fixture ($TaskPath -ceq '\' -and $TaskName -ceq $ctx.TaskName) 'mock task target'
    Assert-Fixture ($script:fixture.State -ceq 'Disabled') 'disable before stop'
    $script:fixture.Operations += 'Stop'
}
function Enable-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath,[string]$TaskName)
    Assert-Fixture ($TaskPath -ceq '\' -and $TaskName -ceq $ctx.TaskName) 'mock task target'
    $script:fixture.Operations += 'Enabled'
    $script:fixture.State = 'Ready'
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath,[string]$TaskName)
    Assert-Fixture ($TaskPath -ceq '\' -and $TaskName -ceq $ctx.TaskName) 'mock task target'
    $script:fixture.Operations += 'Start'
    $script:fixture.State = 'Running'
}
function Start-Sleep {
    param([int]$Milliseconds)
    if ($script:fixture.Countdown -le 0) { return }
    $script:fixture.Countdown--
    if ($script:fixture.Countdown -eq 0) {
        $script:fixture.Rows = @()
        $script:fixture.Listeners = @()
    }
}
Reset-Fixture
$script:fixture.Countdown = 2
Test-Fixture 'espera salida real tras detener y deshabilitar' {
    Stop-KVUpgradeService $ctx
    Assert-Fixture (($script:fixture.Operations -join ',') -ceq 'Disabled,Stop' -and $ctx.CapturedKv.Count -eq 2) 'task and PID evidence'
    Assert-KVUpgradeStopped $ctx
}
Reset-Fixture
$script:fixture.Listeners = @()
Test-Fixture 'puerto libre con Python vivo no acredita detencion' { Stop-KVUpgradeService $ctx } 'KV_STOP_NOT_VERIFIED'
Reset-Fixture
$script:fixture.Rows = @()
Test-Fixture 'Python ausente con 9444 ocupado no acredita detencion' { Stop-KVUpgradeService $ctx } 'KV_STOP_NOT_VERIFIED'

function Assert-KVUpgradeStablePair {
    param($Context, [string]$Version)
    if ($script:fixture.InvalidPair) { throw 'KV_SOURCE_PAIR' }
}
function Assert-KVUpgradeLegacy {}
function Assert-KVUpgradeRunning {
    param($Context,[string]$Version)
    $script:fixture.Verified = $Version
}
Reset-Fixture
$script:fixture.State = 'Disabled'
$script:fixture.Rows = @()
$script:fixture.Listeners = @()
$script:fixture.InvalidPair = $true
Test-Fixture 'una mezcla de archivos nunca habilita la tarea' {
    try { Start-KVUpgradeService $ctx 'Candidate' }
    finally { Assert-Fixture ($script:fixture.Operations.Count -eq 0) 'no task changes' }
} 'KV_SOURCE_PAIR'
Reset-Fixture
$script:fixture.State = 'Disabled'
$script:fixture.Rows = @()
$script:fixture.Listeners = @()
Test-Fixture 'tarea Running sin listener no acredita arranque' {
    Start-KVUpgradeService $ctx 'Candidate'
} 'KV_START_NOT_VERIFIED'

function New-FixtureHttpClient([string]$Json) {
    $client = [pscustomobject]@{Json=$Json}
    $client | Add-Member ScriptMethod SendAsync {
        param($request)
        Assert-Fixture ($request.Method.Method -ceq 'GET' -and $request.RequestUri.Host -ceq 'fixture.invalid') 'Mock HTTP, GET only'
        $response = [Net.Http.HttpResponseMessage]::new([Net.HttpStatusCode]::OK)
        $response.Content = [Net.Http.StringContent]::new($this.Json)
        $response.Headers.CacheControl = [Net.Http.Headers.CacheControlHeaderValue]::new()
        $response.Headers.CacheControl.NoStore = $true
        return [Threading.Tasks.Task[Net.Http.HttpResponseMessage]]::FromResult($response)
    }
    return $client
}
$candidateJson = '{"simulado":true,"control_fisico":false,"canDrive":false,"turno_activo":false,"solicitudes":[],"duraciones_segundos":[120,300,600,1200],"modo_supervisado":true}'
$originalJson = '{"simulado":true,"control_fisico":false,"canDrive":false,"turno_activo":false,"solicitudes":[]}'
$probe = 'https://fixture.invalid/admin'
Test-Fixture 'contrato candidato HTTPS exige los cuatro plazos y modo supervisado' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient $candidateJson) $probe 200 -Contract Candidate -RequireIdle
}
Test-Fixture 'contrato original HTTPS sin capacidades V1' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient $originalJson) $probe 200 -Contract Original -RequireIdle
}
Test-Fixture 'duraciones incorrectas no son evidencia de upgrade' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient ($candidateJson.Replace('600','601'))) $probe 200 -Contract Candidate
} 'KV_HTTP_CAPABILITIES'
Test-Fixture 'turno activo bloquea el preflight de upgrade' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient ($originalJson.Replace('"turno_activo":false','"turno_activo":true'))) $probe 200 -Contract Original -RequireIdle
} 'KV_HTTP_VIRTUAL'
Test-Fixture 'una solicitud pendiente bloquea una ventana no vacia' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient ($originalJson.Replace('[]','[{}]'))) $probe 200 -Contract Original -RequireIdle
} 'KV_HTTP_QUEUE'
Test-Fixture 'ningun contrato permite conducir' {
    Invoke-KVUpgradeHttpGet (New-FixtureHttpClient ($candidateJson.Replace('"canDrive":false','"canDrive":true'))) $probe 200 -Contract Candidate
} 'KV_HTTP_VIRTUAL'

Write-Output ('[K-V Windows CI] {0}/{0} casos sin acceso a tareas, sockets o AWS.' -f $script:tests)
