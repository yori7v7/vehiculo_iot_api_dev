# K-X: PREVUELO SOLO LECTURA de Windows Server y contrato de despliegue.
# NO ejecutar start/restart/install, NO encender EC2/RDS, NO abrir firewall.
# -Mode Repository: valida exclusivamente archivos del repositorio (CI offline).
# -Mode Server: además examina tareas, Caddyfile persistente y listeners locales,
#               pero JAMAS cambia el sistema. No lee .env ni secretos.
[CmdletBinding()]
param(
    [ValidateSet('Repository','Server')][string]$Mode = 'Repository',
    [string]$StateDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).ProviderPath
$legacy = Join-Path $root 'deploy\windows\Caddyfile'
$candidate = Join-Path $PSScriptRoot 'Caddyfile.candidate_NOT_DEPLOY'
$virtualApp = Join-Path $root 'app\public_control\kv_virtual_staging.py'
$kWCI = Join-Path $root 'deploy\staging\kw\Caddyfile.ci'
$script:findings = New-Object 'System.Collections.Generic.List[string]'
$script:errors = New-Object 'System.Collections.Generic.List[string]'

function Assert-KX([bool]$Condition, [string]$Label) {
    if ($Condition) {
        $script:findings.Add('OK: ' + $Label)
    }
    else {
        $script:errors.Add('NO-GO: ' + $Label)
    }
}
function Read-KX([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Falta un archivo de contrato K-X.'
    }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8)
}
function Matches-KX([string]$Content, [string]$ExactText) {
    return $Content.Contains($ExactText)
}

try {
    $original = Read-KX $legacy
    $proposed = Read-KX $candidate
    $testOnly = Read-KX $kWCI
    $virtual = Read-KX $virtualApp

    # Comparar la topología, no datos secretos ni la IP real del usuario.
    $normalOriginal = ($original -replace "`r`n?", "`n").Trim()
    Assert-KX ($normalOriginal -eq "100-30-4-62.nip.io {`n    reverse_proxy 127.0.0.1:8000`n}") 'Caddyfile del repositorio es el original: solo legacy 8000'
    Assert-KX (Matches-KX $proposed 'reverse_proxy 127.0.0.1:8000') 'Candidato preserva el backend legacy 8000'
    Assert-KX (Matches-KX $proposed 'reverse_proxy 127.0.0.1:9444') 'Candidato separa admision 9444'
    Assert-KX (Matches-KX $proposed 'header_up X-Admission-Client-IP {remote_host}') 'Identidad depende del cliente real, no del test'
    Assert-KX (-not (Matches-KX $proposed '8.8.8.8')) 'IP ficticia de CI no figura en candidato'
    Assert-KX (Matches-KX $testOnly 'header_up X-Admission-Client-IP 8.8.8.8') 'La identidad de prueba solo vive en CI'
    Assert-KX (Matches-KX $virtual 'ADMISSION_VIRTUAL_ONLY') 'Backend K-V exige modo virtual explicito'
    Assert-KX (Matches-KX $virtual '"canDrive": False') 'Contrato de admision nunca habilita motores'
    Assert-KX (-not (Matches-KX $original '9444')) 'Caddyfile original sin rutas experimentales'
    Assert-KX (Matches-KX $proposed 'KW_PROXY_TOKEN') 'Proxy candidato exige secreto externo, NO está configurado para produccion'

    if ($Mode -eq 'Server') {
        if ($env:OS -ne 'Windows_NT') {
            throw 'Modo Server requiere Windows Server con PowerShell nativo.'
        }
        if ([string]::IsNullOrWhiteSpace($StateDirectory)) {
            $StateDirectory = Join-Path $env:ProgramData 'VehiculoIoT'
        }
        $state = [IO.Path]::GetFullPath($StateDirectory)
        $programData = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
        Assert-KX ($state.StartsWith($programData + '\',
            [StringComparison]::OrdinalIgnoreCase)) 'Estado en subcarpeta exclusiva ProgramData'
        if (-not (Test-Path -LiteralPath $state -PathType Container)) {
            $script:errors.Add('NO-GO: no hay estado Windows desplegado; no iniciar tareas')
        }
        else {
            $live = Join-Path $state 'Caddyfile'
            if (Test-Path -LiteralPath $live -PathType Leaf) {
                $installed = Read-KX $live
                Assert-KX ((Matches-KX $installed 'reverse_proxy 127.0.0.1:8000') -and
                    (-not (Matches-KX $installed '9444'))) 'Caddy vigente sin servicio K-V (estado previo a integracion)'
                $script:findings.Add('INFO: Caddy instalado revisado SOLO en memoria; ningun cambio aplicado')
            }
            else {
                $script:errors.Add('NO-GO: falta Caddyfile persistente; no tocar los servicios')
            }
            foreach ($name in @('VehiculoIoT-Caddy', 'VehiculoIoT-FastAPI')) {
                $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
                if ($null -eq $task) {
                    $script:errors.Add('NO-GO: tarea esperada no instalada: ' + $name)
                }
                else {
                    $script:findings.Add('INFO: tarea existente: ' + $name + ' (' + $task.State + ')')
                }
            }
            foreach ($port in @(8000, 9444)) {
                $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
                foreach ($listener in $listeners) {
                    Assert-KX ($listener.LocalAddress -in @('127.0.0.1','::1')) ('Puerto ' + $port + ' limitado a loopback')
                }
                if ($listeners.Count -eq 0) {
                    $script:findings.Add('INFO: puerto ' + $port + ' sin listener (puede ser correcto con AWS apagado)')
                }
            }
            # La ruta legacy y la propuesta NO se sustituyen automáticamente.
            # Prohibido leer .env, imprimir API keys o modificar Caddy.
        }
    }
}
catch {
    $script:errors.Add('NO-GO: no fue posible completar el preflight sin alterar el servidor')
}
foreach ($message in $script:findings) { Write-Output ('[K-X] ' + $message) }
foreach ($message in $script:errors) { Write-Output ('[K-X] ' + $message) }
if ($script:errors.Count -gt 0) { exit 2 }
Write-Output '[K-X] Revision solo lectura finalizada. NO implica autorizacion para desplegar.'
exit 0
