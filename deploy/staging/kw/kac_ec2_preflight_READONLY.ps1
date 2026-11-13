# K-AC — PREVUELO DE DESPLIEGUE, EXCLUSIVAMENTE LECTURA (PowerShell 5.1).
# Nunca instala/modifica Task Scheduler, Caddy, Firewall, EC2 ni credenciales.
# Modo Repository funciona desconectado. Modo Server requiere Windows/EC2
# previamente encendido por el operador en una ventana AUTORIZADA; no lo hace.
[CmdletBinding()]
param(
    [ValidateSet('Repository','Server')][string]$Mode = 'Repository',
    [string]$LegacyStateDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).ProviderPath
$script:failures = New-Object 'System.Collections.Generic.List[string]'
$script:passed = New-Object 'System.Collections.Generic.List[string]'

function Test-KAC([bool]$Ok, [string]$Message) {
    if ($Ok) { $script:passed.Add($Message) }
    else { $script:failures.Add($Message) }
}
function Read-KAC([string]$Name) {
    if (-not (Test-Path -LiteralPath $Name -PathType Leaf)) {
        throw 'Falta uno de los archivos estructurales.'
    }
    return [string](Get-Content -LiteralPath $Name -Raw -Encoding UTF8)
}
function Normalize-KAC([string]$Value) { return (($Value -replace "`r`n?", "`n").Trim()) }
function HasUnsafeWrite-KAC([string]$Path) {
    $mask = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    $everyone = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
    $acl = Get-Acl -LiteralPath $Path
    $rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    foreach ($r in $rules) {
        if ($r.AccessControlType -eq 'Allow' -and
            $r.IdentityReference.Value -in $everyone -and
            (($r.FileSystemRights -band $mask) -ne 0)) { return $true }
    }
    return $false
}

try {
    $originalPath = Join-Path $root 'deploy\windows\Caddyfile'
    $candidatePath = Join-Path $root 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY'
    $legacyInstallPath = Join-Path $root 'deploy\windows\install.ps1'
    $kabPath = Join-Path $root 'app\public_control\kab_windows_staging.py'
    $original = Normalize-KAC (Read-KAC $originalPath)
    $candidate = Read-KAC $candidatePath
    $installer = Read-KAC $legacyInstallPath
    $kab = Read-KAC $kabPath

    Test-KAC ($original -eq "100-30-4-62.nip.io {`n    reverse_proxy 127.0.0.1:8000`n}") 'Caddyfile plantilla conserva SOLO el puerto 8000'
    Test-KAC ($candidate.Contains('reverse_proxy 127.0.0.1:8000') -and
        $candidate.Contains('reverse_proxy 127.0.0.1:9444')) 'Candidato mantiene rutas legacy separadas de virtual'
    Test-KAC ($candidate.Contains('header_up X-Admission-Client-IP {remote_host}') -and
        (-not $candidate.Contains('8.8.8.8'))) 'Candidato no fija IP de prueba'
    Test-KAC ($candidate.Contains('header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}')) 'Caddy candidato requiere secreto ajeno al repositorio'
    Test-KAC ($kab.Contains('enabled') -and $kab.Contains('service_sid') -and
        $kab.Contains('127.0.0.1') -and $kab.Contains('9444') -and
        $kab.Contains('S-1-5-19')) 'Lanzador staging exige SID dedicada y activación explícita'
    Test-KAC (-not $installer.Contains('VehiculoIoT-Admission-Staging')) 'Instalador legacy no registra tareas experimentales'

    if ($Mode -eq 'Server') {
        if ($env:OS -ne 'Windows_NT') { throw 'Server solamente se revisa en Windows.' }
        $programData = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
        if ([string]::IsNullOrWhiteSpace($LegacyStateDirectory)) {
            $LegacyStateDirectory = Join-Path $programData 'VehiculoIoT'
        }
        $installed = [IO.Path]::GetFullPath($LegacyStateDirectory).TrimEnd('\')
        Test-KAC ($installed.StartsWith(($programData + '\'),
            [StringComparison]::OrdinalIgnoreCase)) 'Estado legacy dentro de ProgramData'
        if (-not (Test-Path -LiteralPath $installed -PathType Container)) {
            throw 'No existe el estado original de Windows.'
        }

        $configurationPath = Join-Path $installed 'deployment.json'
        $currentCaddyPath = Join-Path $installed 'Caddyfile'
        $cfg = (Read-KAC $configurationPath) | ConvertFrom-Json
        $persistent = Normalize-KAC (Read-KAC $currentCaddyPath)
        # El Caddyfile REAL puede diferir de la plantilla; no reemplazarlo.
        Test-KAC (($cfg.schema_version -eq 1) -and
            ($cfg.state_directory -eq $installed) -and
            ($cfg.project_root -eq $root) -and
            ($cfg.caddyfile_path -eq $currentCaddyPath)) 'deployment.json corresponde al checkout y estado real'
        Test-KAC ($persistent.Contains('reverse_proxy 127.0.0.1:8000') -and
            (-not $persistent.Contains('127.0.0.1:9444'))) 'Caddy persistente conserva la ruta anterior antes de cambios'
        Test-KAC (-not (HasUnsafeWrite-KAC $currentCaddyPath)) 'Caddy persistente no editable por usuarios comunes'
        foreach ($path in @($root, (Join-Path $root 'app'), $cfg.python_path)) {
            Test-KAC ((Test-Path -LiteralPath $path) -and (-not (HasUnsafeWrite-KAC $path))) 'Codigo/Python no modificable por usuarios comunes'
        }
        # No confundir plantilla y Caddy activo. La revisión verifica
        # autoridad y acciones EXACTAS, sin arrancar servicios.
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $scriptNames = @('api','caddy')
        $taskNames = @('VehiculoIoT-FastAPI','VehiculoIoT-Caddy')
        for($i=0;$i -lt 2;$i++) {
            $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskNames[$i] -ErrorAction SilentlyContinue
            if($null -eq $task) {
                $script:failures.Add('No se encontró tarea legacy esperada')
                continue
            }
            $runScript = Join-Path $root ('deploy\windows\run_' + $scriptNames[$i] + '.ps1')
            $arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -StateDirectory "{1}"' -f $runScript, $installed
            Test-KAC (@($task.Actions).Count -eq 1 -and
                $task.Actions[0].Execute -eq $powershell -and
                $task.Actions[0].Arguments -eq $arguments) 'Acción de tarea legacy coincide sin modificaciones'
            Test-KAC ($task.Principal.UserId -in @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')) 'Principal de tarea legacy original'
        }
        foreach ($port in @(8000,9444)) {
            $connections = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
            foreach ($c in $connections) {
                Test-KAC ($c.LocalAddress -in @('127.0.0.1','::1')) 'Puerto reservado solo a loopback'
            }
        }
        $staging = Join-Path $programData 'VehiculoIoT-Admission-Staging'
        # Un paquete preinstalado NO es una autorización de arranque.
        if (Test-Path -LiteralPath $staging -PathType Container) {
            Test-KAC (-not (HasUnsafeWrite-KAC $staging)) 'Carpeta de staging no editable por usuarios generales'
            $manifest = Join-Path $staging 'staging.json'
            if(Test-Path -LiteralPath $manifest -PathType Leaf) {
                # NO mostrar ni exportar manifiesto, SID ni secretos.
                $data = (Read-KAC $manifest) | ConvertFrom-Json
                Test-KAC ($data.enabled -eq $false) 'Staging sigue deshabilitado'
            }
        }
        else { $script:passed.Add('Staging aun no creado; estado esperado antes de instalacion') }
        $script:passed.Add('Solo consulta de tareas, ACL, puertos y metadata; ninguna escritura')
    }
}
catch {
    $script:failures.Add('Preflight incompleto; no iniciar ni modificar servicios')
}
foreach ($line in $script:passed) { Write-Output ('[K-AC] OK: ' + $line) }
foreach ($line in $script:failures) { Write-Output ('[K-AC] NO-GO: ' + $line) }
if ($script:failures.Count -gt 0) { exit 2 }
Write-Output '[K-AC] Lectura finalizada. No autoriza instalación, reinicio ni apertura de puertos.'
exit 0
