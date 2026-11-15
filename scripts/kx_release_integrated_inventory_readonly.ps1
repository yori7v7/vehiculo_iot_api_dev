# K-X release-gate inventory after end-to-end EC2 LAB success.
# READ ONLY. Windows PowerShell 5.1. Never modifies files, tasks, process, ports or firewall.
# No secret values are read, printed or saved. NO HTTP traffic. NO PUBLICATION.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$phase='START'
$step='BEGIN'
$base='C:\ProgramData\VehiculoIoT-KX-Installer'
$stateRoot='C:\ProgramData\VehiculoIoT-KX-State\service'
$manifestFile=Join-Path $stateRoot 'install.json'
$release=Join-Path $base 'kx_https_public_release_v1_offline'
$stage=Join-Path $release 'launcher_staging_v1'
$manifest=Join-Path $release 'preparation.json'
$stageManifest=Join-Path $stage 'launcher_stage_report.json'
$lab=Join-Path $base 'kx_integrated_cutover_lab_v1'
$labReport=Join-Path $lab 'integrated_lab_report.json'
$liveCaddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$liveLauncher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$legacyLauncherSHA='873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
$runRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
$success=$false

function Check([bool]$ok,[string]$label){
 if(-not $ok){throw ('NO-GO: '+$label)}
 Write-Host ('OK: '+$label) -ForegroundColor Green
}
function Normal([string]$path,[string]$label,[bool]$directory=$false){
 $kind=if($directory){'Container'}else{'Leaf'}
 Check (Test-Path -LiteralPath $path -PathType $kind) ($label+' existe')
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ($label+' sin enlace')
}
function Hash([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash }
function Same([string]$path,[string]$expected,[string]$label){
 Normal $path $label
 Check ((Hash $path) -ceq $expected) ($label+' SHA256')
}
function OwnerIsSystem([uint32]$id){
 $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$id) -ErrorAction Stop
 if($null -eq $proc){return $false}
 $res=Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop
 return $res.Sid -ceq 'S-1-5-18'
}
function MatchesRecord($rec){
 if($null -eq $rec){return $false}
 $p=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$rec.process_id) -ErrorAction Stop
 if($null -eq $p){return $false}
 return ($p.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$rec.creation_ticks -and
    [string]::Equals([string]$p.ExecutablePath,[string]$rec.executable_path,[StringComparison]::OrdinalIgnoreCase) -and
    (OwnerIsSystem ([uint32]$rec.process_id)))
}
function Listen([int]$port){return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)}

Write-Host ''
Write-Host '=== K-X FINAL: INVENTARIO DE PREPARACION SIN MUTACIONES ===' -ForegroundColor Cyan
try{
 $phase='PREREQUISITES'
 Check ($PSVersionTable.PSVersion.Major -eq 5) 'Windows PowerShell 5.1'
 $identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Administrador elevado'
 foreach($p in @($base,$stateRoot,$release,$stage,$lab)){Normal $p 'Carpeta privada' $true}
 foreach($p in @($base,$stateRoot,$lab)){
  Check ((Get-Acl -LiteralPath $p).AreAccessRulesProtected) 'Raiz privada sin herencia NTFS'
 }
 foreach($p in @($manifestFile,$manifest,$stageManifest,$labReport,$runRecord)){
  Normal $p 'Manifiesto/evidencia privado'
 }
 $installData=Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
 $prep=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
 $launchPrep=Get-Content -LiteralPath $stageManifest -Raw | ConvertFrom-Json
 Check ($installData.mode -ceq 'loopback_only_not_public' -and
    $installData.caddy_changed -eq $false -and
    $installData.physical_control_enabled -eq $false) 'K-V privado, sin publicacion ni control fisico'
 Check ($prep.mode -ceq 'offline_public_https_candidate_never_activated') 'Caddy candidato inactivo'
 Check ($launchPrep.mode -ceq 'launcher_candidate_staged_offline_not_installed') 'Lanzador candidato inactivo'

 $phase='HASHES'
 Same $liveCaddy ([string]$installData.original_caddy_sha256) 'Caddyfile productivo original'
 Same $liveLauncher $legacyLauncherSHA 'Lanzador productivo original'
 Same (Join-Path $base 'kx_caddy_release_preflight\Caddyfile.original.copy') ([string]$installData.original_caddy_sha256) 'Respaldo Caddy original'
 Same (Join-Path $stage 'run_caddy.original.backup.ps1') $legacyLauncherSHA 'Respaldo lanzador original'
 Same (Join-Path $release 'Caddyfile.kx.ready.NOT_ACTIVE') ([string]$prep.candidate_sha256) 'Caddyfile candidato offline'
 Same (Join-Path $stage 'run_caddy.kx.pending.ps1') ([string]$launchPrep.launcher_candidate_sha256) 'Lanzador candidato offline'

 $phase='LAB_EVIDENCE'
 $report=Get-Content -LiteralPath $labReport -Raw | ConvertFrom-Json
 Check ($report.mode -ceq 'integrated_end_to_end_lab_only') 'Reporte de transaccion integrada'
 $cases=@($report.scenarios)
 Check ($cases.Count -eq 2 -and ($cases -contains 'CRASH_AFTER_SECOND') -and ($cases -contains 'COMMIT_OK')) 'Dos escenarios integrados cubiertos'
 Check ($report.independent_system_task_triggered -eq $true -and
  $report.cross_session_lock_exercised -eq $true -and
  $report.service_fictitious_task_tested -eq $true) 'Watchdog, lock y servicio ficticio reportados'
 Check ($report.public_https_modified -eq $false -and
  $report.service_production_tested -eq $false -and
  $report.production_rollback_tested -eq $false -and
  $report.physical_control_enabled -eq $false) 'Laboratorio no afirma tocar produccion'
 Check ((@(
  Get-ScheduledTask -ErrorAction Stop |
   Where-Object { $_.TaskName -like 'VehiculoIoT-KX-INT-LAB-*' }
 )).Count -eq 0) 'Sin tareas residuales del laboratorio integrado'

 $phase='TASK_AND_PROCESS'
 $step='TASK_STATES'
 foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
  $step='TASK_STATE_'+$name
  $task=Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
  Check ($task.State -eq 'Running') ($name+' Running')
 }
 $step='CADDY_ACTION'
 $caddyTask=Get-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-Caddy' -ErrorAction Stop
 $actions=@($caddyTask.Actions)
 Check ($actions.Count -eq 1) 'Tarea Caddy tiene una accion'
 $originalAction=$actions[0]
 Check ($null -ne $originalAction) 'Accion Caddy presente'
 Check (([string]$originalAction.Arguments).Contains($liveLauncher)) 'Tarea Caddy usa lanzador original'

 $step='CADDY_PRINCIPAL'
 $principal=$caddyTask.Principal
 Check ($null -ne $principal) 'Principal de Caddy presente'
 Check ((@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$principal.UserId)) 'Tarea Caddy bajo SYSTEM'

 $step='CADDY_RETRY_XML'
 [xml]$taskXml=Export-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-Caddy' -ErrorAction Stop
 $ns=New-Object System.Xml.XmlNamespaceManager($taskXml.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $n1=$taskXml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Count',$ns)
 $n2=$taskXml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Interval',$ns)
 Check ($null -ne $n1 -and $null -ne $n2) 'Nodos de reintento XML presentes'
 Check ([int]$n1.InnerText -eq 999 -and $n2.InnerText -ceq 'PT1M') 'Reintentos originales 999 / 1 minuto'

 $step='PROCESS_RECORD'
 $r=Get-Content -LiteralPath $runRecord -Raw |ConvertFrom-Json
 Check ($null -ne $r) 'Registro de proceso presente'
 Check (MatchesRecord $r.supervisor) 'Identidad supervisor PID/fecha/ruta/SYSTEM'
 Check (MatchesRecord $r.child) 'Identidad Caddy hijo PID/fecha/ruta/SYSTEM'
 $sup=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$r.supervisor.process_id) -ErrorAction Stop
 $child=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$r.child.process_id) -ErrorAction Stop
 Check ($null -ne $sup -and $null -ne $child) 'Supervisor y Caddy hijo presentes'
 Check ([int]$child.ParentProcessId -eq [int]$sup.ProcessId) 'Relacion supervisor-hijo exacta'
 Check ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Imagen unica Caddy'

 $step='LISTENER_443'
 $l443=@(Listen 443)
 Check ($l443.Count -gt 0) 'Puerto HTTPS 443 en escucha'
 $owners443=@($l443|Select-Object -ExpandProperty OwningProcess -Unique)
 Check ($owners443.Count -eq 1 -and
  [int]$owners443[0] -eq [int]$child.ProcessId) 'HTTPS 443 propiedad de Caddy hijo identificado'
 Check (@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop).Count -eq 1) 'Solo un proceso caddy.exe'

 $step='LISTENER_9444'
 $l9444=@(Listen 9444)
 Check ($l9444.Count -eq 1 -and
  $l9444[0].LocalAddress -ceq '127.0.0.1') 'K-V loopback 9444'

 $step='LISTENER_8000'
 $l8000=@(Listen 8000)
 Check ($l8000.Count -gt 0 -and
  @($l8000|Where-Object {$_.LocalAddress -notin @('127.0.0.1','::1')}).Count -eq 0) 'FastAPI loopback 8000'

 $step='LISTENER_9481'
 Check (@(Listen 9481).Count -eq 0) 'Puerto laboratorio 9481 libre'

 $step='LISTENER_2019'
 Check (@(Listen 2019|Where-Object {$_.LocalAddress -notin @('127.0.0.1','::1')}).Count -eq 0) 'Caddy admin 2019 no publicado'

 $phase='CLOSING_HASH'
 Check ((Hash $liveCaddy) -ceq [string]$installData.original_caddy_sha256 -and
   (Hash $liveLauncher) -ceq $legacyLauncherSHA) 'Archivos productivos intactos al finalizar'

 Write-Host ''
 Write-Host '=== RESULTADO: K-X INVENTARIO INTEGRADO READ-ONLY APROBADO ===' -ForegroundColor Green
 Write-Host 'LABORATORIO INTEGRADO: EVIDENCIA EC2, TAREAS TEMPORALES AUSENTES'
 Write-Host 'PRODUCCION: CADDY SYSTEM Y FASTAPI/K-V SIN CAMBIOS'
 Write-Host 'REINTENTOS 999/PT1M: CONFIRMADOS'
 Write-Host 'PUBLICACION: NO-GO HASTA RECUPERADOR REAL, PREFLIGHT HTTP Y AUTORIZACION'
 $success=$true
}catch{
 Write-Host ''
 Write-Host '=== RESULTADO: NO-GO INVENTARIO K-X READ-ONLY ===' -ForegroundColor Red
 Write-Host ('FASE: '+$phase) -ForegroundColor Yellow
 Write-Host ('PASO: '+$step) -ForegroundColor Yellow
 Write-Host ('LINEA: '+[int]$_.InvocationInfo.ScriptLineNumber) -ForegroundColor Yellow
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host 'No repetir ni tocar HTTPS: comprobar evidencia y tareas antes de continuar.' -ForegroundColor Yellow
}
Write-Host 'SOLO LECTURA: SIN RESTART, TAREAS, ARCHIVOS, REDES, AWS/RDS O MOTORES' -ForegroundColor Cyan
if(-not $success){exit 1}
exit 0
