# K-X: read-only audit of exact production Caddy supervisor, task retry and child ownership.
# Windows PowerShell 5.1. Does not read config.json secrets or change any services/files.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\VehiculoIoT'
$install = 'C:\ProgramData\VehiculoIoT-KX-Installer'
$manifestPath = 'C:\ProgramData\VehiculoIoT-KX-State\service\install.json'
$taskName = 'VehiculoIoT-Caddy'
$recordPath = Join-Path $root 'run\caddy.json'
$originalTaskXml = Join-Path $install 'kx_caddy_release_preflight\VehiculoIoT-Caddy.task.xml'
$preflightPath = Join-Path $install 'kx_caddy_release_preflight\release_preflight.json'
$caddyfile = Join-Path $root 'Caddyfile'
$launcher = 'C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$launcherHash = '873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
$phase = 'PREFLIGHT'

function Check([bool]$condition,[string]$label) {
    if (-not $condition) { throw ('NO-GO: ' + $label) }
    Write-Host ('OK: ' + $label) -ForegroundColor Green
}
function ProcessMatches($entry,[string]$description) {
    Check ($null -ne $entry) ($description + ' registrado')
    $proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$entry.process_id) -ErrorAction Stop
    Check ($null -ne $proc) ($description + ' activo')
    Check ([string]::Equals(
        $proc.CreationDate.ToUniversalTime().Ticks.ToString(),
        [string]$entry.creation_ticks,[StringComparison]::Ordinal)) ($description + ' misma fecha de creacion')
    Check ([string]::Equals(
        [string]$proc.ExecutablePath,
        [string]$entry.executable_path,[StringComparison]::OrdinalIgnoreCase)) ($description + ' misma imagen')
    $sid = (Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop).Sid
    Check ($sid -ceq 'S-1-5-18') ($description + ' pertenece a SYSTEM')
    return $proc
}
function Ports([int]$port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}
Write-Host ''
Write-Host '=== K-X: AUDITORIA SUPERVISOR Y REINTENTOS, SOLO LECTURA ===' -ForegroundColor Cyan
try {
    Check ($PSVersionTable.PSVersion.Major -eq 5) 'Windows PowerShell 5.x'
    $identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    Check ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Consola elevada'
    foreach ($path in @($root,$install,$manifestPath,$recordPath,$preflightPath,$originalTaskXml,$caddyfile,$launcher)) {
        Check (Test-Path -LiteralPath $path) 'Material de referencia presente'
        Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Ruta fisica sin redireccion'
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $kit = Get-Content -LiteralPath $preflightPath -Raw | ConvertFrom-Json
    Check ($manifest.mode -ceq 'loopback_only_not_public' -and
           $manifest.caddy_changed -eq $false -and
           $manifest.physical_control_enabled -eq $false) 'K-V no publicado y control fisico OFF'
    Check ((Get-FileHash -LiteralPath $caddyfile -Algorithm SHA256).Hash -ceq [string]$manifest.original_caddy_sha256) 'Caddyfile original verificado'
    Check ((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -ceq $launcherHash) 'Lanzador original verificado'
    Check ((Get-FileHash -LiteralPath $originalTaskXml -Algorithm SHA256).Hash -ceq [string]$kit.caddy_task_xml_sha256) 'XML respaldado verificado'

    $phase = 'TASK'
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    Check ($task.State -eq 'Running') 'Supervisor Caddy programado Running'
    Check (@($task.Actions).Count -eq 1) 'Unica accion de tarea'
    $a = @($task.Actions)[0]
    $powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Check ([string]::Equals([string]$a.Execute,$powerShellExe,[StringComparison]::OrdinalIgnoreCase)) 'Tarea inicia Windows PowerShell original'
    Check (([string]$a.Arguments).Contains($launcher)) 'Tarea conserva lanzador original'
    Check ((@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$task.Principal.UserId)) 'Tarea bajo SYSTEM'

    [xml]$taskXml = Export-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    $ns = New-Object System.Xml.XmlNamespaceManager($taskXml.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $retryNode = $taskXml.SelectSingleNode('//t:Settings/t:RestartOnFailure',$ns)
    Check ($null -ne $retryNode) 'Reintentos configurados'
    $countNode = $retryNode.SelectSingleNode('t:Count',$ns)
    $intervalNode = $retryNode.SelectSingleNode('t:Interval',$ns)
    Check ($null -ne $countNode -and $null -ne $intervalNode) 'Numero e intervalo de reintentos presentes'
    Check ([int]$countNode.InnerText -eq 999) 'Reintentos automaticos: 999'
    Check ($intervalNode.InnerText -ceq 'PT1M') 'Intervalo automatico: 1 minuto'
    Write-Host 'INFO: stop de tarea aislado NO constituye control suficiente de reintentos.' -ForegroundColor Yellow

    $phase = 'PROCESS_RECORD'
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    $supervisor = ProcessMatches $record.supervisor 'Supervisor registrado'
    $child = ProcessMatches $record.child 'Caddy hijo registrado'
    Check ([int]$child.ParentProcessId -eq [int]$supervisor.ProcessId) 'Relacion real padre-hijo coincide'

    $phase = 'LISTENERS'
    $ports443 = @(Ports 443)
    Check ($ports443.Count -gt 0) 'Puerto HTTPS 443 en escucha'
    $owners = @($ports443 | Select-Object -ExpandProperty OwningProcess -Unique)
    Check ($owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) 'Unico Caddy hijo propietario de HTTPS'
    Check ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Imagen Caddy original'
    Check (@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop).Count -eq 1) 'Un solo caddy.exe activo'
    $ports9444 = @(Ports 9444)
    Check ($ports9444.Count -eq 1 -and $ports9444[0].LocalAddress -ceq '127.0.0.1') 'K-V aislado en 9444'
    $ports8000 = @(Ports 8000)
    Check ($ports8000.Count -gt 0 -and @($ports8000 | Where-Object { $_.LocalAddress -notin @('127.0.0.1','::1') }).Count -eq 0) 'FastAPI solo loopback'
    Check (@(Ports 9481).Count -eq 0) 'Puerto de laboratorio libre'
    Check (@(Ports 2019 | Where-Object { $_.LocalAddress -notin @('127.0.0.1','::1') }).Count -eq 0) 'Caddy admin sin exposicion externa'
    Write-Host ''
    Write-Host '=== RESULTADO: IDENTIDAD SUPERVISOR CADDY Y REINTENTOS VERIFICADOS ===' -ForegroundColor Green
    Write-Host 'SUPERVISOR + HIJO: IDENTIDAD COMPLETA CON PID, CREACION, EXE Y SYSTEM'
    Write-Host 'TAREA: REINTENTOS AUTOMATICOS DETECTADOS, NO CAMBIADOS'
    Write-Host 'PRODUCCION 443: INTACTA; K-V NO PUBLICADO; CONTROL FISICO OFF'
    Write-Host 'SIGUIENTE: PLANIFICAR ARBITRAJE EXCLUSIVO Y RECUPERACION INDEPENDIENTE'
}
catch {
    Write-Host ''
    Write-Host '=== RESULTADO: NO-GO AUDITORIA SUPERVISOR ===' -ForegroundColor Red
    Write-Host ('FASE: ' + $phase) -ForegroundColor Yellow
    Write-Host ('TIPO: ' + $_.Exception.GetType().Name) -ForegroundColor Yellow
    Write-Host 'MENSAJE PRIVADO OMITIDO. No tocar el HTTPS ni repetir sin diagnostico.'
    exit 1
}
Write-Host 'SOLO LECTURA; SIN RESTART, TAREAS NUEVAS, ESCRITURA, AWS, RDS O MOTORES'
exit 0
