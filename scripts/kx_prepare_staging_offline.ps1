# K-X: staging OFFLINE protegido. Compatible con Windows PowerShell 5.1.
# NO crea usuarios/tareas, NO inicia procesos, NO modifica Caddy/legacy/firewall.
# Copia solamente codigo .py del checkout validado + candidatos/rollback.
# No copia HMAC, .env, certificados, base de datos ni ejecutables.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [Parameter(Mandatory=$true)][string]$ProposedCaddyfile
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$state = Join-Path $env:ProgramData 'VehiculoIoT'
$activeCaddy = Join-Path $state 'Caddyfile'
$destination = Join-Path $env:ProgramData 'VehiculoIoT-KX-Staging'
$hmacPath = Join-Path $env:ProgramData 'VehiculoIoT-KX-Device\kx-device-1-key.bin'
$verifiedIdentity = 'AABB6EFF0F31B6171DA1795FE69C6DA62015A3B0AD61452494AD57F917A7D839'
$expectedFiles = @{
    'app\main.py' = 'a1a3ac1c86c66c166c08e5ac1011c35ba722b61a'
    'app\public_control\kx_inline_admission.py' = '0271e568ac1f3bd1cce6e62b9ff59c6ac68648a2'
    'app\public_control\kx_signed_wss.py' = '51af46c4eef796c06b394fa2bd4bedd94eec5edc'
}
$proposalBlob = 'b14e796da8bcfb0ea8377fc79bfa64186c8206ca'

function Assert-KX([bool]$Condition, [string]$Reason) {
    if (-not $Condition) { throw ('[K-X] NO-GO: ' + $Reason) }
}
function Get-GitBlob([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    $head = [Text.Encoding]::ASCII.GetBytes(('blob ' + $bytes.Length + [char]0))
    $data = New-Object byte[] ($head.Length + $bytes.Length)
    [Array]::Copy($head, 0, $data, 0, $head.Length)
    [Array]::Copy($bytes, 0, $data, $head.Length, $bytes.Length)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        return ([BitConverter]::ToString($sha1.ComputeHash($data)).Replace('-', '').ToLowerInvariant())
    }
    finally { $sha1.Dispose() }
}
function Assert-NoReparse([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    Assert-KX (-not (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) 'Ruta redirigida no permitida'
}
function Get-OriginalText([string]$Path) {
    return ((Get-Content -LiteralPath $Path -Encoding UTF8 -Raw) -replace "`r`n?", "`n").Trim()
}
function Assert-StagingAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    Assert-KX ($acl.AreAccessRulesProtected) 'ACL de staging hereda permisos generales'
    $trusted = @('S-1-5-18', 'S-1-5-32-544')
    foreach($rule in $rules) {
        if($rule.AccessControlType -eq 'Allow') {
            Assert-KX ($rule.IdentityReference.Value -in $trusted) 'Staging permite acceso a identidad no aprobada'
        }
    }
    foreach($sid in $trusted) {
        Assert-KX ((@($rules | Where-Object {
            $_.IdentityReference.Value -eq $sid -and $_.AccessControlType -eq 'Allow'
        })).Count -gt 0) 'Falta identidad protectora en ACL'
    }
}

Write-Host "`n=== K-X: PREPARACION DE STAGING PRIVADO ===" -ForegroundColor Cyan
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
Assert-KX ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'PowerShell requiere elevacion'
Assert-KX ($env:OS -eq 'Windows_NT') 'Este script es exclusivo de Windows'
Assert-KX (-not (Test-Path -LiteralPath $destination)) 'Ya existe staging: no sobrescribir'

$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot -ErrorAction Stop).ProviderPath
$ProposedCaddyfile = (Resolve-Path -LiteralPath $ProposedCaddyfile -ErrorAction Stop).ProviderPath
$appSource = Join-Path $SourceRoot 'app'
$sourcePython = Join-Path $SourceRoot '.venv\Scripts\python.exe'
Assert-KX ((Test-Path -LiteralPath $appSource -PathType Container) -and
           (Test-Path -LiteralPath $sourcePython -PathType Leaf)) 'Checkout experimental incompleto'
Assert-KX (-not (Test-Path -LiteralPath (Join-Path $SourceRoot '.env'))) 'Checkout tiene .env'
Assert-KX (Test-Path -LiteralPath $activeCaddy -PathType Leaf) 'Caddyfile activo ausente'
Assert-KX (Test-Path -LiteralPath $hmacPath -PathType Leaf) 'HMAC privada ausente'
Assert-NoReparse $SourceRoot
Assert-NoReparse $appSource
Assert-NoReparse $activeCaddy
Assert-NoReparse $ProposedCaddyfile
Assert-NoReparse $hmacPath

$expectedCaddy = "100-30-4-62.nip.io {`n    reverse_proxy 127.0.0.1:8000`n}"
Assert-KX ((Get-OriginalText $activeCaddy) -ceq $expectedCaddy) 'Caddy activo no es el legacy original'
Assert-KX ((Get-GitBlob $ProposedCaddyfile) -eq $proposalBlob) 'Caddy candidato alterado'
foreach($item in $expectedFiles.Keys) {
    $src = Join-Path $SourceRoot $item
    Assert-KX (Test-Path -LiteralPath $src -PathType Leaf) 'Archivo K-X requerido ausente'
    Assert-NoReparse $src
    Assert-KX ((Get-GitBlob $src) -eq $expectedFiles[$item]) 'Checkout K-X no coincide con codigo ensayado'
}
Assert-KX ((Get-Item -LiteralPath $hmacPath).Length -eq 32) 'Longitud HMAC invalida'
Assert-KX ((Get-FileHash -LiteralPath $hmacPath -Algorithm SHA256).Hash -eq $verifiedIdentity) 'Identidad HMAC distinta de la validada'

foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI')) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue
    Assert-KX ($null -ne $task -and [string]$task.State -eq 'Running') 'Tarea legacy no se encuentra ejecutando'
}
foreach($name in @('VehiculoIoT-Admission-Virtual','VehiculoIoT-Admission-Staging','VehiculoIoT-KX')) {
    Assert-KX ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue)) 'Ya existe tarea experimental'
}
$kxListener = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
Assert-KX ($kxListener.Count -eq 0) 'Puerto 9444 ocupado'
# Verificar el arbol COMPLETO antes de crear un directorio, para impedir
# carpetas a medio preparar si el checkout difiere del snapshot conocido.
$files = @(Get-ChildItem -LiteralPath $appSource -Filter '*.py' -Recurse -File -ErrorAction Stop)
Assert-KX ($files.Count -eq 99) 'Arbol Python distinto del candidato a1288d3'
foreach($file in $files) { Assert-NoReparse $file.FullName }
$initialCaddySHA256 = (Get-FileHash -LiteralPath $activeCaddy -Algorithm SHA256).Hash
Write-Host 'FUENTES ORIGINALES Y ESTADO: VERIFICADOS' -ForegroundColor Green

# El directorio hereda permisos durante SOLO esta instruccion. ACL cerrada
# ANTES de copiar codigo, configuracion o datos.
New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null
& icacls.exe $destination /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
Assert-KX ($LASTEXITCODE -eq 0) 'No se pudo proteger staging'
Assert-StagingAcl $destination
Write-Host 'CARPETA STAGING: ACL SOLO SYSTEM Y ADMINISTRADORES' -ForegroundColor Green

$codeRoot = Join-Path $destination 'code'
$configRoot = Join-Path $destination 'candidate'
$rollbackRoot = Join-Path $destination 'rollback'
$futureStateRoot = Join-Path $destination 'state_NOT_ENABLED'
foreach($dir in @($codeRoot,$configRoot,$rollbackRoot,$futureStateRoot)) {
    New-Item -ItemType Directory -Path $dir -ErrorAction Stop | Out-Null
}

# El checkout anterior contiene exactamente 99 archivos de Python en app.
# No copiar .env, archivos .pyc, .pem, claves, .git ni ejecutables.
$destinationApp = Join-Path $codeRoot 'app'
New-Item -ItemType Directory -Path $destinationApp | Out-Null
foreach($file in $files) {
    Assert-NoReparse $file.FullName
    $relative = $file.FullName.Substring($appSource.Length + 1)
    $target = Join-Path $destinationApp $relative
    $parent = Split-Path -Path $target -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $file.FullName -Destination $target -ErrorAction Stop
}
foreach($item in $expectedFiles.Keys) {
    $copied = Join-Path $codeRoot $item
    Assert-KX ((Get-GitBlob $copied) -eq $expectedFiles[$item]) 'Copia de codigo K-X difiere del origen'
}
Copy-Item -LiteralPath $ProposedCaddyfile -Destination (Join-Path $configRoot 'Caddyfile.kx_diagnostic_NOT_DEPLOY') -ErrorAction Stop
Copy-Item -LiteralPath $activeCaddy -Destination (Join-Path $rollbackRoot 'Caddyfile.before-KX') -ErrorAction Stop
Assert-KX ((Get-FileHash -LiteralPath (Join-Path $rollbackRoot 'Caddyfile.before-KX') -Algorithm SHA256).Hash -eq $initialCaddySHA256) 'Respaldo Caddy no coincide'

$manifest = [ordered]@{
    schema_version = 1
    mode = 'offline_staging_only'
    anchor_checkout = 'a1288d3'
    source_python_files = $files.Count
    live_caddy_sha256_before = $initialCaddySHA256
    live_caddy_sha256_after = ''
    planned_loopback_port = 9444
    persistent_task_created = $false
    caddy_deployed = $false
    real_device_authenticated = $false
    physical_control_enabled = $false
    created_utc = (Get-Date).ToUniversalTime().ToString('o')
}
$manifestPath = Join-Path $destination 'stage.json'
$manifest.live_caddy_sha256_after = (Get-FileHash -LiteralPath $activeCaddy -Algorithm SHA256).Hash
Assert-KX ($manifest.live_caddy_sha256_after -eq $initialCaddySHA256) 'Caddy activo cambio durante staging'
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -ErrorAction Stop
Assert-StagingAcl $destination
Assert-KX ((Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).mode -eq 'offline_staging_only') 'Manifiesto staging incompleto'
Assert-KX ((@(
    Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue
)).Count -eq 0) 'Puerto 9444 ocupado tras staging'

Write-Host 'CODIGO K-X: 99 ARCHIVOS .PY COPIADOS Y VERIFICADOS' -ForegroundColor Green
Write-Host 'CADDY CANDIDATO: COPIADO, NO DESPLEGADO'
Write-Host 'CADDY LEGACY: RESPALDADO, SIN CAMBIOS'
Write-Host 'CLAVE HMAC: NO COPIADA NI MOSTRADA'
Write-Host 'SERVICIO/TAREA K-X: NO INSTALADO'
Write-Host 'PUERTO 9444: LIBRE'
Write-Host 'RDS, ESP, MOTORES: SIN OPERACIONES'
Write-Host '=== STAGING OFFLINE PREPARADO CORRECTAMENTE ===' -ForegroundColor Green
