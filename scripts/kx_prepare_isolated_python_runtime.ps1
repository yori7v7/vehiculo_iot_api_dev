# K-X: runtime independiente en ProgramData, Windows PowerShell 5.1.
# No crea usuario/tarea, no abre puertos, no toca Caddy/legacy/HMAC/RDS.
# Copia SOLO stdlib Python 3.14.8 + DLLs, sin paquetes globales del admin.
# Recrea venv e instala dependencias declaradas desde PyPI con TLS.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [string]$StageRoot = "$env:ProgramData\VehiculoIoT-KX-Staging"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$expectedReqBlob = '8b8b6927de5614b9a6aa79e6ebc23e0934382546'
$runtime = Join-Path $StageRoot 'runtime'
$newBase = Join-Path $runtime 'python-base'
$newVenv = Join-Path $runtime 'venv'
$venvPython = Join-Path $newVenv 'Scripts\python.exe'
$caddyOriginal = "$env:ProgramData\VehiculoIoT\Caddyfile"

function Require-KX([bool]$Ok, [string]$Reason) {
    if (-not $Ok) { throw ('[K-X] NO-GO: ' + $Reason) }
}
function Get-KXGitBlob([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    $prefix = [Text.Encoding]::ASCII.GetBytes(('blob ' + $bytes.Length + [char]0))
    $all = New-Object byte[] ($prefix.Length + $bytes.Length)
    [Array]::Copy($prefix, 0, $all, 0, $prefix.Length)
    [Array]::Copy($bytes, 0, $all, $prefix.Length, $bytes.Length)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try { return ([BitConverter]::ToString($sha1.ComputeHash($all))).Replace('-', '').ToLowerInvariant() }
    finally { $sha1.Dispose() }
}
function Assert-NoReparse([string]$Path) {
    $entry = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    Require-KX (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Origen es reparse/link'
}
function Invoke-KXRobocopy([string[]]$Arguments) {
    & robocopy.exe @Arguments | Out-Null
    Require-KX ($LASTEXITCODE -lt 8) 'Fallo copia de librerias Python'
}

Write-Host ('{0}=== K-X: CREACION DE RUNTIME INDEPENDIENTE ===' -f [Environment]::NewLine) -ForegroundColor Cyan
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
Require-KX ($env:OS -eq 'Windows_NT') 'Requiere Windows'
Require-KX ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Consola no elevada'
Require-KX (Test-Path -LiteralPath $StageRoot -PathType Container) 'Staging no disponible'
Require-KX (-not (Test-Path -LiteralPath $runtime)) 'Runtime ya existe, no sobrescribir'
$manifestFile = Join-Path $StageRoot 'stage.json'
Require-KX (Test-Path -LiteralPath $manifestFile -PathType Leaf) 'Manifiesto staging ausente'
$manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
Require-KX ($manifest.mode -ceq 'offline_staging_only' -and
    $manifest.persistent_task_created -eq $false -and
    $manifest.caddy_deployed -eq $false -and
    $manifest.physical_control_enabled -eq $false) 'Staging ya activado'
Require-KX (Test-Path -LiteralPath (Join-Path $StageRoot 'code\app\main.py') -PathType Leaf) 'Codigo K-X ausente'
Require-KX (Test-Path -LiteralPath $caddyOriginal -PathType Leaf) 'Caddy original no encontrado'
$hashBefore = (Get-FileHash -LiteralPath $caddyOriginal -Algorithm SHA256).Hash
Require-KX ($hashBefore -eq $manifest.live_caddy_sha256_before) 'Caddy original difiere del staging'
$srcPython = Join-Path $SourceRoot '.venv\Scripts\python.exe'
$srcRequirements = Join-Path $SourceRoot 'requirements.txt'
Require-KX (Test-Path -LiteralPath $srcPython -PathType Leaf) 'Python candidato ausente'
Require-KX (Test-Path -LiteralPath $srcRequirements -PathType Leaf) 'Requirements ausentes'
Require-KX ((Get-KXGitBlob $srcRequirements) -eq $expectedReqBlob) 'Requirements diferentes a la version probada'
Require-KX (-not (Test-Path -LiteralPath (Join-Path $SourceRoot '.env'))) 'Checkout contiene .env'
Assert-NoReparse $srcPython

$detail = & $srcPython -I -c "import json,sys;print(json.dumps({'home':sys.base_prefix,'exe':getattr(sys,'_base_executable',sys.executable),'version':list(sys.version_info[:3])}))"
Require-KX ($LASTEXITCODE -eq 0) 'No se puede inspeccionar Python'
$meta = [string]$detail | ConvertFrom-Json
Require-KX (($meta.version -join '.') -ceq '3.14.8') 'Python debe ser 3.14.8'
$sourceBase = [IO.Path]::GetFullPath([string]$meta.home).TrimEnd('\')
$sourceExe = [IO.Path]::GetFullPath([string]$meta.exe)
Require-KX ($sourceExe.StartsWith($sourceBase + '\', [StringComparison]::OrdinalIgnoreCase)) 'Ejecutable Python base fuera de instalacion'
Assert-NoReparse $sourceBase
foreach($relative in @('python.exe','python314.dll','Lib','Lib\venv\__init__.py',
    'Lib\ensurepip\__init__.py','DLLs')) {
    Require-KX (Test-Path -LiteralPath (Join-Path $sourceBase $relative)) 'Layout de Python base no compatible'
}
Require-KX (-not (Test-Path -LiteralPath (Join-Path $sourceBase 'pyvenv.cfg'))) 'Python base es un venv'
Require-KX ((@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)).Count -eq 0) 'Puerto 9444 ocupado'

$rootAcl = Get-Acl -LiteralPath $StageRoot
Require-KX ($rootAcl.AreAccessRulesProtected) 'Staging hereda ACL general'
foreach($rule in @($rootAcl.GetAccessRules(
    $true, $true, [Security.Principal.SecurityIdentifier]
))) {
    if($rule.AccessControlType -eq 'Allow') {
        Require-KX ($rule.IdentityReference.Value -in @('S-1-5-18','S-1-5-32-544')) 'Staging accesible por identidad no autorizada'
    }
}
$driveLetter = [IO.Path]::GetPathRoot($StageRoot).Substring(0,1)
Require-KX ((Get-PSDrive -Name $driveLetter).Free -gt 1500MB) 'Espacio insuficiente en disco'
Write-Host 'PRECONDICIONES / CODIGO / PYTHON 3.14.8 / ACL: OK' -ForegroundColor Green

# Crear solo directorios bajo staging protegido.
New-Item -ItemType Directory -Path $runtime | Out-Null
New-Item -ItemType Directory -Path $newBase | Out-Null

# Copia con fuentes limitadas: nunca site-packages global, .env o perfil completo.
$rootFiles = @('python.exe','pythonw.exe','python3.dll','python314.dll',
    'python314.zip','vcruntime*.dll')
Invoke-KXRobocopy (@($sourceBase,$newBase) + $rootFiles +
    @('/R:0','/W:0','/XJ','/NP','/NFL','/NDL','/NJH','/NJS'))
Invoke-KXRobocopy @((Join-Path $sourceBase 'Lib'),(Join-Path $newBase 'Lib'),
    '/E','/XJ','/R:0','/W:0','/NP','/NFL','/NDL','/NJH','/NJS',
    '/XD',(Join-Path $sourceBase 'Lib\site-packages'))
Invoke-KXRobocopy @((Join-Path $sourceBase 'DLLs'),(Join-Path $newBase 'DLLs'),
    '/E','/XJ','/R:0','/W:0','/NP','/NFL','/NDL','/NJH','/NJS')
Require-KX (-not (Test-Path -LiteralPath (Join-Path $newBase 'Lib\site-packages'))) 'Se copiaron paquetes globales del admin'
$copiedReparse = @(Get-ChildItem -LiteralPath $newBase -Recurse -Force -ErrorAction Stop |
    Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
Require-KX ($copiedReparse.Count -eq 0) 'Python copiado contiene reparse/link'

$newPython = Join-Path $newBase 'python.exe'
Require-KX (Test-Path -LiteralPath $newPython -PathType Leaf) 'Python independiente ausente'
$relocated = & $newPython -I -c "import json,sys,ssl,sqlite3,venv;print(json.dumps({'home':sys.base_prefix,'version':list(sys.version_info[:3])}))"
Require-KX ($LASTEXITCODE -eq 0) 'Python independiente no puede ejecutar stdlib'
$rel = [string]$relocated | ConvertFrom-Json
Require-KX (([IO.Path]::GetFullPath([string]$rel.home).TrimEnd('\')) -ieq $newBase) 'Python nuevo aun depende del perfil Administrador'
Require-KX (($rel.version -join '.') -eq '3.14.8') 'Python nuevo es de otra version'
Write-Host 'PYTHON BASE SEPARADO DEL PERFIL: OK' -ForegroundColor Green

# venv NO es portable; crearlo desde la base ya trasladada.
& $newPython -I -m venv --copies $newVenv
Require-KX ($LASTEXITCODE -eq 0) 'No se creo venv independiente'
Require-KX (Test-Path -LiteralPath $venvPython -PathType Leaf) 'Venv creado incompleto'
$cfg = Get-Content -LiteralPath (Join-Path $newVenv 'pyvenv.cfg') -Raw -Encoding UTF8
Require-KX (($cfg -match [regex]::Escape($newBase)) -and
    ($cfg -notmatch [regex]::Escape($sourceBase))) 'Venv referencia perfil Administrador'
Copy-Item -LiteralPath $srcRequirements -Destination (Join-Path $runtime 'requirements.txt')
Require-KX ((Get-KXGitBlob (Join-Path $runtime 'requirements.txt')) -eq $expectedReqBlob) 'Requirements copiados difieren'
Write-Host 'VENV NUEVO / ARCHIVOS DE REQUISITOS: OK' -ForegroundColor Green

Write-Host 'INSTALANDO DEPENDENCIAS SOLO EN RUNTIME PRIVADO (PYPI TLS)' -ForegroundColor Cyan
$pipArgs = @('-I','-m','pip','--isolated','install','--no-input',
    '--no-cache-dir','--disable-pip-version-check','--retries','1',
    '--timeout','20','--index-url','https://pypi.org/simple',
    '-r',(Join-Path $runtime 'requirements.txt'))
& $venvPython @pipArgs
Require-KX ($LASTEXITCODE -eq 0) 'Pip no pudo instalar dependencias'
& $venvPython -I -m pip --isolated check
Require-KX ($LASTEXITCODE -eq 0) 'Conflictos de paquetes'
& $venvPython -I -c "import json,sys,fastapi,uvicorn,pydantic,pydantic_settings,pymysql,ssl,sqlite3;print(json.dumps({'home':sys.base_prefix,'venv':sys.prefix}))"
Require-KX ($LASTEXITCODE -eq 0) 'Importaciones de FastAPI/Uvicorn/MySQL fallaron'
$newEnv = [string]$LASTEXITCODE
# Confirmar base y venv sin depender de directorios del Administrador.
$pyState = & $venvPython -I -c "import json,sys;print(json.dumps({'home':sys.base_prefix,'venv':sys.prefix}))"
Require-KX ($LASTEXITCODE -eq 0) 'Venv no responde'
$pyLocations = [string]$pyState | ConvertFrom-Json
Require-KX ([IO.Path]::GetFullPath([string]$pyLocations.home).TrimEnd('\') -ieq $newBase) 'Venv depende de Python antiguo'
Require-KX ([IO.Path]::GetFullPath([string]$pyLocations.venv).TrimEnd('\') -ieq $newVenv) 'Venv no reside en staging'
Require-KX ((Get-FileHash -LiteralPath $caddyOriginal -Algorithm SHA256).Hash -eq $hashBefore) 'Caddy original cambio'
Require-KX ((@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)).Count -eq 0) 'Puerto 9444 ocupado'

$info = [ordered]@{
    schema_version = 1
    mode = 'runtime_ready_but_disabled'
    python_version = '3.14.8'
    independent_base = $true
    requirements_blob = $expectedReqBlob
    task_installed = $false
    caddy_changed = $false
    physical_control_enabled = $false
}
$info | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'runtime.json') -Encoding UTF8
Write-Host 'DEPENDENCIAS / VENV INDEPENDIENTE: VERIFICADOS' -ForegroundColor Green
Write-Host 'CADDY ORIGINAL: INTACTO'
Write-Host 'PUERTO 9444: LIBRE'
Write-Host 'CUENTA Y TAREA K-X: NO CREADAS'
Write-Host 'RDS / ESP / MOTORES: SIN OPERACIONES'
Write-Host '=== RUNTIME K-X AISLADO PREPARADO ===' -ForegroundColor Green
