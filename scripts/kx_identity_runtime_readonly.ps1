# K-X: preflight para identidad dedicada y Python, PowerShell 5.1.
# SOLO LECTURA. No revela credenciales ni paths privados, no crea usuario/tarea.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [string]$StageRoot = "$env:ProgramData\VehiculoIoT-KX-Staging",
    [string]$ProposedAccount = "VehIoT_KXSvc"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:errors = [System.Collections.Generic.List[string]]::new()
$script:notes = [System.Collections.Generic.List[string]]::new()

function Check([bool]$Condition, [string]$Label) {
    if ($Condition) {
        Write-Output ('OK: ' + $Label)
    } else {
        Write-Output ('NO-GO: ' + $Label)
        $script:errors.Add($Label)
    }
}

function Get-ACL-Rules([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $rules = @($acl.GetAccessRules(
        $true, $true, [Security.Principal.SecurityIdentifier]
    ))
    return ,@($rules)
}

function Has-Public-Write([string]$Path) {
    $ordinary = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
    $mask = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach($rule in @(Get-ACL-Rules $Path)) {
        if ($rule.AccessControlType -eq 'Allow' -and
            $rule.IdentityReference.Value -in $ordinary -and
            (($rule.FileSystemRights -band $mask) -ne 0)) {
            return $true
        }
    }
    return $false
}

function Check-Stage-Private([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $trusted = @('S-1-5-18','S-1-5-32-544')
    $rules = @(Get-ACL-Rules $Path)
    if (-not $acl.AreAccessRulesProtected) { return $false }
    foreach ($rule in $rules) {
        if ($rule.AccessControlType -eq 'Allow' -and
            $rule.IdentityReference.Value -notin $trusted) { return $false }
    }
    return $true
}

Write-Output '=== K-X IDENTIDAD / RUNTIME: SOLO LECTURA ==='
try {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    Check ($principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) 'Consola elevada'
    Check ($env:OS -eq 'Windows_NT') 'Windows nativo'
    Check (Test-Path -LiteralPath $StageRoot -PathType Container) 'Staging offline presente'
    $stage = Join-Path $StageRoot 'stage.json'
    Check (Test-Path -LiteralPath $stage -PathType Leaf) 'Manifiesto staging presente'
    $data = Get-Content -LiteralPath $stage -Raw -Encoding UTF8 |
        ConvertFrom-Json
    Check ($data.schema_version -eq 1 -and
           $data.mode -ceq 'offline_staging_only' -and
           $data.persistent_task_created -eq $false -and
           $data.caddy_deployed -eq $false -and
           $data.physical_control_enabled -eq $false) 'Staging sigue sin activar'
    Check ($data.source_python_files -eq 99) 'Staging con 99 archivos de origen'
    Check (Check-Stage-Private $StageRoot) 'ACL raiz reservada a SYSTEM/Administradores'
    foreach($sub in @('code','candidate','rollback','state_NOT_ENABLED')) {
        $p = Join-Path $StageRoot $sub
        Check (Test-Path -LiteralPath $p -PathType Container) ('Componente: ' + $sub)
        if (Test-Path -LiteralPath $p -PathType Container) {
            Check (-not (Has-Public-Write $p)) ('Sin escritura general: ' + $sub)
        }
    }
    $stageFiles = @(
        Get-ChildItem -LiteralPath (Join-Path $StageRoot 'code\app') -Recurse -File -Filter '*.py'
    )
    Check ($stageFiles.Count -eq 99) 'Codigo de staging completo'
    $python = Join-Path $SourceRoot '.venv\Scripts\python.exe'
    Check (Test-Path -LiteralPath $python -PathType Leaf) 'Runtime del candidato existente'
    $base = (& $python -c "import sys;print(getattr(sys, '_base_executable', sys.executable))" |
        Select-Object -Last 1)
    Check ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($base)) 'Python puede describir su base'
    $base = [string]$base
    Check (Test-Path -LiteralPath $base -PathType Leaf) 'Python base existente'

    $userProfilePrefix = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\') + '\'
    $baseInAdminProfile = [IO.Path]::GetFullPath($base).StartsWith(
        $userProfilePrefix, [StringComparison]::OrdinalIgnoreCase
    )
    if ($baseInAdminProfile) {
        Write-Output 'INFO: PYTHON BASE EN PERFIL ADMINISTRADOR'
        Write-Output 'INFO: Servicio dedicado requerira runtime independiente, no acceso a perfil'
    } else {
        Write-Output 'INFO: PYTHON BASE FUERA DEL PERFIL ADMINISTRADOR'
        Write-Output 'INFO: Aun hay que validar ACL del runtime antes de otorgar permisos'
    }
    Check (-not (Has-Public-Write $base)) 'Binario Python base no editable por usuarios generales'
    $version = (& $python -c "import sys;print('.'.join(str(i) for i in sys.version_info[:3]))" |
        Select-Object -Last 1)
    Check ($LASTEXITCODE -eq 0) 'Version Python consultada'
    Write-Output ('INFO: PYTHON VERSION: ' + [string]$version)

    Check ($null -ne (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) 'New-LocalUser disponible'
    Check ($null -ne (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) 'ScheduledTasks disponible'
    Check ($null -eq (Get-LocalUser -Name $ProposedAccount -ErrorAction SilentlyContinue)) 'Nombre dedicado disponible'
    foreach($taskName in @('VehiculoIoT-KX','VehiculoIoT-Admission-Virtual',
                          'VehiculoIoT-Admission-Staging')) {
        Check ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)) ('Sin tarea: ' + $taskName)
    }
    $listener = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    Check ($listener.Count -eq 0) 'Puerto 9444 libre'
    $original = 'C:\ProgramData\VehiculoIoT\Caddyfile'
    Check ((Get-Content -LiteralPath $original -Raw -Encoding UTF8) -match
        'reverse_proxy 127\.0\.0\.1:8000') 'Caddy original conservado'
    $sha = (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash
    Check ($data.live_caddy_sha256_before -eq $sha -and
           $data.live_caddy_sha256_after -eq $sha) 'Caddy original coincide con respaldo staging'
} catch {
    $script:errors.Add('Error de auditoria sin cambios al servidor')
    Write-Output ('NO-GO: AUDITORIA_INCOMPLETA ' + $_.Exception.GetType().Name)
}
if ($script:errors.Count -gt 0) {
    Write-Output ('RESULTADO: NO-GO (' + $script:errors.Count + ' observaciones)')
    Write-Output 'NO CREAR USUARIO NI TAREA'
    exit 2
}
Write-Output 'RESULTADO: PREVUELO DE IDENTIDAD COMPLETADO'
Write-Output 'NO SE CREARON USUARIOS, TAREAS NI PROCESOS'
exit 0
