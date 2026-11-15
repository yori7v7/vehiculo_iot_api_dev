# K-V V1: preparar SOLO un candidato aislado para las nuevas duraciones.
# Windows PowerShell 5.1. NO detiene tareas, NO cambia codigo vivo, SQLite,
# Caddy, firewall, credenciales, RDS ni actuadores. No hace cutover.
# El commit y los blobs fuente son inmutables.
[CmdletBinding()]
param([switch]$ProbeOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$expectedCommit = '6a6e4bdf42f51f5592ded4b8186cd430920d1631'
$expected = @(
    @{
        Name='kv_virtual_staging.py'
        Blob='dc42f5992b6a14bc17adb27f36a032491d884d56'
        OriginalSHA256='083DA2C3D359DB5631852A56126CD1522AC1B94C733AC74801362971095B307A'
    },
    @{
        Name='kr_ticket_ledger.py'
        Blob='e8f1b143faea73851abdebfd6c874efa2b72f96e'
        OriginalSHA256='1D7B301EEB4EF818A726010F686C325D44CF4E53CBCC6F63DC280EE09D7548D6'
    }
)
$live = 'C:\ProgramData\VehiculoIoT-KX-Staging\code\app\public_control'
$state = 'C:\ProgramData\VehiculoIoT-KX-State\service'
$v4 = 'C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v4_RELEASE_READY'
$stage = 'C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE'
$taskName = 'VehiculoIoT-Admission-Virtual'

function Require([bool]$Condition,[string]$Label) {
    if(-not $Condition) { throw ('NO-GO: ' + $Label) }
    Write-Host ('OK: ' + $Label) -ForegroundColor Green
}
function Assert-NoLink([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    Require (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ('Sin reparse: ' + $item.Name)
}
function GitBlobSha1([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    $prefix = [Text.Encoding]::ASCII.GetBytes(('blob ' + $bytes.Length + [char]0))
    $full = New-Object byte[] ($prefix.Length + $bytes.Length)
    [Array]::Copy($prefix,0,$full,0,$prefix.Length)
    [Array]::Copy($bytes,0,$full,$prefix.Length,$bytes.Length)
    $hash = [Security.Cryptography.SHA1]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($full))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
}
function Assert-Private([string]$Path,[string[]]$ExtraSids=@()) {
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    Require ($acl.AreAccessRulesProtected) ('Herencia cerrada: ' + [IO.Path]::GetFileName($Path))
    $allowed=@('S-1-5-18','S-1-5-32-544') + @($ExtraSids)
    foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if($rule.AccessControlType -eq 'Allow') {
            Require ($allowed -ccontains [string]$rule.IdentityReference.Value) 'Solo SID de servicio y cuentas del sistema'
        }
    }
}
function Assert-Baseline {
    Require ($PSVersionTable.PSVersion.Major -eq 5) 'PowerShell 5.x'
    $identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    Require ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Consola elevada'
    foreach($folder in @($live,$state,$v4)) {
        Require (Test-Path -LiteralPath $folder -PathType Container) ('Carpeta presente: ' + [IO.Path]::GetFileName($folder))
        Assert-NoLink $folder
    }
    Assert-Private 'C:\ProgramData\VehiculoIoT-KX-Staging'
    $install = Get-Content -LiteralPath (Join-Path $state 'install.json') -Raw -ErrorAction Stop | ConvertFrom-Json
    Require ($install.mode -ceq 'loopback_only_not_public' -and
             $install.physical_control_enabled -eq $false -and
             $install.task_name -ceq $taskName -and
             $install.dedicated_user -ceq 'VehIoT_KXSvc' -and
             [string]$install.dedicated_sid -match '^S-1-5-21-(?:[0-9]+-){3}[0-9]+
    $transaction = Get-Content -LiteralPath (Join-Path $v4 'transaction.json') -Raw -ErrorAction Stop | ConvertFrom-Json
    Require ($transaction.phase -ceq 'COMMITTED_VERIFIED') 'Caddy V4 ya COMMITTED_VERIFIED'
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    Require ($task.State -eq 'Running' -and @($task.Actions).Count -eq 1) 'Tarea dedicada Running'
    Require (@($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) 'K-V sin disparadores'
    foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI')) {
        Require ((Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop).State -eq 'Running') ($name + ' Running')
    }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 9444 -ErrorAction SilentlyContinue)
    Require ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -ceq '127.0.0.1') 'K-V solo 127.0.0.1:9444'
    foreach($item in $expected) {
        $path=Join-Path $live $item.Name
        Require (Test-Path -LiteralPath $path -PathType Leaf) ('Archivo original: ' + $item.Name)
        Assert-NoLink $path
        $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash
        Require ($hash -ceq $item.OriginalSHA256) ('SHA256 original: ' + $item.Name)
    }
    Require (Test-Path -LiteralPath (Join-Path $state 'data\admission.sqlite') -PathType Leaf) 'SQLite original presente'
    Require (-not(Test-Path -LiteralPath $stage)) 'Destino exclusivo libre: no sobreescrituras'
}

Write-Host ''
Write-Host '=== K-V V1: STAGING AISLADO, NUNCA CUTOVER ===' -ForegroundColor Cyan
try {
    Assert-Baseline
    if($ProbeOnly) {
        Write-Host 'GO: PREFLIGHT SOLO LECTURA. NINGUN ARCHIVO MODIFICADO.' -ForegroundColor Green
    } else {
        # Staging nuevo sin herencia: el servicio K-V existente NO necesita
        # acceso a estos ficheros ni puede leerlos o alterarlos.
        New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
        & icacls.exe $stage /inheritance:r | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Cerrar herencia de staging'
        & icacls.exe $stage /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Conceder SOLO SYSTEM y Administradores'
        & icacls.exe $stage /setowner '*S-1-5-32-544' | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Propietario Administradores'
        Assert-Private $stage

        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $manifestFiles = @()
        foreach($item in $expected) {
            $name = [string]$item.Name
            $target = Join-Path $stage $name
            $url = 'https://raw.githubusercontent.com/yori7v7/vehiculo_iot_api_dev/' + $expectedCommit + '/app/public_control/' + $name
            Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $target -MaximumRedirection 2 -ErrorAction Stop
            Require (Test-Path -LiteralPath $target -PathType Leaf) ('Descarga: ' + $name)
            Assert-NoLink $target
            $bytes=(Get-Item -LiteralPath $target -ErrorAction Stop).Length
            Require ($bytes -gt 1000 -and $bytes -lt 100000) ('Tamano fuente: ' + $name)
            Require ((GitBlobSha1 $target) -ceq $item.Blob) ('Blob Git inmutable: ' + $name)
            $sha=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
            $manifestFiles += [ordered]@{
                name=$name
                git_blob=$item.Blob
                sha256=$sha
                length=$bytes
            }
        }
        $manifest=[ordered]@{
            schema_version=1
            mode='candidate_staged_offline_not_installed'
            candidate_commit=$expectedCommit
            active_task_untouched=$true
            legacy_untouched=$true
            caddy_untouched=$true
            sqlite_untouched=$true
            physical_control_enabled=$false
            files=$manifestFiles
        }
        $manifestPath=Join-Path $stage 'candidate.json'
        $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -ErrorAction Stop
        Assert-NoLink $manifestPath
        Assert-Private $stage
        Write-Host 'GO: CANDIDATO AISLADO, FIRMAS VERIFICADAS; PRODUCCION SIN CAMBIOS.' -ForegroundColor Green
    }
}
catch {
    # Sin borrar evidencia ni tocar produccion. Staging incompleto queda
    # aislado y NO debe instalarse.
    Write-Host ('NO-GO: ' + $_.Exception.Message) -ForegroundColor Red
    throw
}
) 'Contrato de instalacion original'
    $dedicated = Get-LocalUser -Name $install.dedicated_user -ErrorAction Stop
    Require ($dedicated.SID.Value -ceq [string]$install.dedicated_sid) 'SID de servicio coincide con manifiesto'
    # K-X asignó a la cuenta dedicada permisos en la raíz de estado.
    # Un SID ajeno sigue siendo NO-GO; jamás cambiar ACL para superar esta puerta.
    Assert-Private 'C:\ProgramData\VehiculoIoT-KX-State' @([string]$install.dedicated_sid)
    Assert-Private $state @([string]$install.dedicated_sid)
    $transaction = Get-Content -LiteralPath (Join-Path $v4 'transaction.json') -Raw -ErrorAction Stop | ConvertFrom-Json
    Require ($transaction.phase -ceq 'COMMITTED_VERIFIED') 'Caddy V4 ya COMMITTED_VERIFIED'
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    Require ($task.State -eq 'Running' -and @($task.Actions).Count -eq 1) 'Tarea dedicada Running'
    Require (@($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) 'K-V sin disparadores'
    foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI')) {
        Require ((Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop).State -eq 'Running') ($name + ' Running')
    }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 9444 -ErrorAction SilentlyContinue)
    Require ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -ceq '127.0.0.1') 'K-V solo 127.0.0.1:9444'
    foreach($item in $expected) {
        $path=Join-Path $live $item.Name
        Require (Test-Path -LiteralPath $path -PathType Leaf) ('Archivo original: ' + $item.Name)
        Assert-NoLink $path
        $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash
        Require ($hash -ceq $item.OriginalSHA256) ('SHA256 original: ' + $item.Name)
    }
    Require (Test-Path -LiteralPath (Join-Path $state 'data\admission.sqlite') -PathType Leaf) 'SQLite original presente'
    Require (-not(Test-Path -LiteralPath $stage)) 'Destino exclusivo libre: no sobreescrituras'
}

Write-Host ''
Write-Host '=== K-V V1: STAGING AISLADO, NUNCA CUTOVER ===' -ForegroundColor Cyan
try {
    Assert-Baseline
    if($ProbeOnly) {
        Write-Host 'GO: PREFLIGHT SOLO LECTURA. NINGUN ARCHIVO MODIFICADO.' -ForegroundColor Green
    } else {
        # Staging nuevo sin herencia: el servicio K-V existente NO necesita
        # acceso a estos ficheros ni puede leerlos o alterarlos.
        New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
        & icacls.exe $stage /inheritance:r | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Cerrar herencia de staging'
        & icacls.exe $stage /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Conceder SOLO SYSTEM y Administradores'
        & icacls.exe $stage /setowner '*S-1-5-32-544' | Out-Null
        Require ($LASTEXITCODE -eq 0) 'Propietario Administradores'
        Assert-Private $stage

        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $manifestFiles = @()
        foreach($item in $expected) {
            $name = [string]$item.Name
            $target = Join-Path $stage $name
            $url = 'https://raw.githubusercontent.com/yori7v7/vehiculo_iot_api_dev/' + $expectedCommit + '/app/public_control/' + $name
            Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $target -MaximumRedirection 2 -ErrorAction Stop
            Require (Test-Path -LiteralPath $target -PathType Leaf) ('Descarga: ' + $name)
            Assert-NoLink $target
            $bytes=(Get-Item -LiteralPath $target -ErrorAction Stop).Length
            Require ($bytes -gt 1000 -and $bytes -lt 100000) ('Tamano fuente: ' + $name)
            Require ((GitBlobSha1 $target) -ceq $item.Blob) ('Blob Git inmutable: ' + $name)
            $sha=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
            $manifestFiles += [ordered]@{
                name=$name
                git_blob=$item.Blob
                sha256=$sha
                length=$bytes
            }
        }
        $manifest=[ordered]@{
            schema_version=1
            mode='candidate_staged_offline_not_installed'
            candidate_commit=$expectedCommit
            active_task_untouched=$true
            legacy_untouched=$true
            caddy_untouched=$true
            sqlite_untouched=$true
            physical_control_enabled=$false
            files=$manifestFiles
        }
        $manifestPath=Join-Path $stage 'candidate.json'
        $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -ErrorAction Stop
        Assert-NoLink $manifestPath
        Assert-Private $stage
        Write-Host 'GO: CANDIDATO AISLADO, FIRMAS VERIFICADAS; PRODUCCION SIN CAMBIOS.' -ForegroundColor Green
    }
}
catch {
    # Sin borrar evidencia ni tocar produccion. Staging incompleto queda
    # aislado y NO debe instalarse.
    Write-Host ('NO-GO: ' + $_.Exception.Message) -ForegroundColor Red
    throw
}
