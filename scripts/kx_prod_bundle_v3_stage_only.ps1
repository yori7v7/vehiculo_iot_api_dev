# K-X: Stage protected REAL HTTPS cutover bundle, without activating it. Windows PowerShell 5.1.
# Copies verified original/candidate Caddy and launcher + locked controller/recoverer.
# Does NOT modify Caddy's running configuration, Task Scheduler, ports, AWS, RDS or ESP.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$phase='INITIAL'
$success=$false
$kit='C:\ProgramData\VehiculoIoT-KX-Installer'
$target=Join-Path $kit 'kx_https_cutover_bundle_v3_RELEASE_READY'
$kxState='C:\ProgramData\VehiculoIoT-KX-State\service'
$originalLauncherHash='873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
$controllerBlob='5880af534f54a3fe286967d091905b0403b35727'
$recovererBlob='f7fae91ba887805d6ebc76d2f33bca319c745f1d'
$originalCaddyLive='C:\ProgramData\VehiculoIoT\Caddyfile'
$originalLauncherLive='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$manifestPath=Join-Path $kxState 'install.json'
$release=Join-Path $kit 'kx_https_public_release_v1_offline'
$stage=Join-Path $release 'launcher_staging_v1'
$task='VehiculoIoT-Caddy'
$runRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
function KX-Check([bool]$okay,[string]$label){
 if(-not $okay){throw ('NO-GO: '+$label)}
 Write-Host ('OK: '+$label) -ForegroundColor Green
}
function KX-CheckPath([string]$path,[bool]$isFolder=$false){
 $kind=if($isFolder){'Container'}else{'Leaf'}
 KX-Check (Test-Path -LiteralPath $path -PathType $kind) 'Ruta de referencia existe'
 KX-Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Sin ruta redirigida'
}
function KX-Hash([string]$path){return (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash}
function KX-Compare([string]$path,[string]$hash,[string]$label){
 KX-CheckPath $path
 KX-Check ((KX-Hash $path) -ceq $hash) ($label+' SHA256')
}
function KX-Blob([string]$path){
 $content=[IO.File]::ReadAllBytes($path)
 $header=[Text.Encoding]::ASCII.GetBytes("blob $($content.Length)$([char]0)")
 $data=New-Object byte[] ($header.Length+$content.Length)
 [Array]::Copy($header,0,$data,0,$header.Length)
 [Array]::Copy($content,0,$data,$header.Length,$content.Length)
 $sha=[Security.Cryptography.SHA1]::Create()
 try{return [BitConverter]::ToString($sha.ComputeHash($data)).Replace('-','').ToLowerInvariant()}
 finally{$sha.Dispose()}
}
function KX-TaskSafe {
 $taskRef=Get-ScheduledTask -TaskPath '\' -TaskName $task -ErrorAction Stop
 KX-Check ($taskRef.State -eq 'Running') 'Caddy task Running'
 $actions=@($taskRef.Actions)
 KX-Check ($actions.Count -eq 1) 'Caddy task has single action'
 KX-Check (([string]$actions[0].Arguments).Contains($originalLauncherLive)) 'Caddy task still points to original launcher'
 KX-Check (@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$taskRef.Principal.UserId) 'Caddy task runs under SYSTEM'
 [xml]$xml=Export-ScheduledTask -TaskPath '\' -TaskName $task -ErrorAction Stop
 $ns=New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $count=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Count',$ns)
 $interval=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Interval',$ns)
 KX-Check ($null -ne $count -and $null -ne $interval) 'Retry definition present'
 KX-Check ([int]$count.InnerText -eq 999 -and $interval.InnerText -ceq 'PT1M') 'Original retry 999/PT1M'
}
function KX-Tracked($data){
 $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$data.process_id) -ErrorAction Stop
 KX-Check ($null -ne $process) 'Tracked process exists'
 KX-Check ($process.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$data.creation_ticks) 'Tracked process creation'
 KX-Check ([string]::Equals([string]$process.ExecutablePath,[string]$data.executable_path,[StringComparison]::OrdinalIgnoreCase)) 'Tracked process image'
 KX-Check ((Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid -ErrorAction Stop).Sid -ceq 'S-1-5-18') 'Tracked SYSTEM SID'
 return $process
}
Write-Host ''
Write-Host '=== K-X: PREPARACION DE CANDIDATO V3, TODAVIA SIN ACTIVAR ===' -ForegroundColor Cyan
try {
 $phase='IDENTITY_AND_INPUTS'
 KX-Check ($PSVersionTable.PSVersion.Major -eq 5) 'Windows PowerShell 5.1'
 $admin=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 KX-Check ($admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Admin elevado'
 KX-CheckPath $kit $true
 KX-CheckPath $kxState $true
 KX-CheckPath $release $true
 KX-CheckPath $stage $true
 KX-Check ((Get-Acl -LiteralPath $kit).AreAccessRulesProtected) 'Instalador privado'
 KX-Check ((Get-Acl -LiteralPath $kxState).AreAccessRulesProtected) 'Estado K-V privado'
 KX-Check (-not (Test-Path -LiteralPath $target)) 'Nuevo paquete, sin sobrescribir'
 $m=Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop|ConvertFrom-Json
 $releaseReport=Get-Content -LiteralPath (Join-Path $release 'preparation.json') -Raw|ConvertFrom-Json
 $stageReport=Get-Content -LiteralPath (Join-Path $stage 'launcher_stage_report.json') -Raw|ConvertFrom-Json
 $preflight=Get-Content -LiteralPath (Join-Path $kit 'kx_caddy_release_preflight\release_preflight.json') -Raw|ConvertFrom-Json
 KX-Check ($m.mode -ceq 'loopback_only_not_public' -and $m.caddy_changed -eq $false -and $m.physical_control_enabled -eq $false) 'K-V aun aislado y control fisico OFF'
 KX-Check ($releaseReport.mode -ceq 'offline_public_https_candidate_never_activated') 'Caddy candidato no activado'
 KX-Check ($stageReport.mode -ceq 'launcher_candidate_staged_offline_not_installed') 'Lanzador candidato no activado'
 $src=@{
  caddy_original=(Join-Path $kit 'kx_caddy_release_preflight\Caddyfile.original.copy')
  launcher_original=(Join-Path $stage 'run_caddy.original.backup.ps1')
  caddy_candidate=(Join-Path $release 'Caddyfile.kx.ready.NOT_ACTIVE')
  launcher_candidate=(Join-Path $stage 'run_caddy.kx.pending.ps1')
  task_xml=(Join-Path $kit 'kx_caddy_release_preflight\VehiculoIoT-Caddy.task.xml')
  controller=(Join-Path $PSScriptRoot 'kx_prod_cutover_controller_v3_RELEASE.ps1')
  recoverer=(Join-Path $PSScriptRoot 'kx_prod_recoverer_v3_RELEASE.ps1')
 }
 $expected=@{
  caddy_original=[string]$m.original_caddy_sha256
  launcher_original=$originalLauncherHash
  caddy_candidate=[string]$releaseReport.candidate_sha256
  launcher_candidate=[string]$stageReport.launcher_candidate_sha256
  task_xml=[string]$preflight.caddy_task_xml_sha256
 }
 foreach($key in $expected.Keys){KX-Compare $src[$key] $expected[$key] ('Entrada '+$key)}
 KX-Check ((KX-Blob $src.controller) -ceq $controllerBlob) 'Controlador LOCKED Git blob verificado'
 KX-Check ((KX-Blob $src.recoverer) -ceq $recovererBlob) 'Recuperador LOCKED Git blob verificado'
 $controller=[IO.File]::ReadAllText($src.controller)
 $recoverer=[IO.File]::ReadAllText($src.recoverer)
 KX-Check ($controller.Contains('EnableProductionCutover=$true') -and
   $recoverer.Contains('EnableProductionRecovery=$true') -and
   $controller.Contains('-AuthorizeRealCutover')) 'Release V3: doble componente habilitado y corte explicito requerido'
 KX-Check ((KX-Hash $originalCaddyLive) -ceq $expected.caddy_original -and
   (KX-Hash $originalLauncherLive) -ceq $expected.launcher_original) 'Produccion original identica a los respaldos'
 KX-TaskSafe
 foreach($name in @('VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
  KX-Check ((Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop).State -eq 'Running') ($name+' Running')
 }
 $rec=Get-Content -LiteralPath $runRecord -Raw|ConvertFrom-Json
 $super=KX-Tracked $rec.supervisor
 $child=KX-Tracked $rec.child
 KX-Check ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Supervisor y Caddy hijo coinciden'
 KX-Check ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Unico proceso hijo Caddy'
 $ports=@(Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue)
 $owners=@($ports|Select-Object -ExpandProperty OwningProcess -Unique)
 KX-Check ($owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) '443 sigue en Caddy original SYSTEM'
 $kv=@(Get-NetTCPConnection -State Listen -LocalPort 9444 -ErrorAction SilentlyContinue)
 KX-Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -ceq '127.0.0.1') 'K-V solo loopback'
 KX-Check (@(Get-NetTCPConnection -State Listen -LocalPort 9481 -ErrorAction SilentlyContinue).Count -eq 0) '9481 sin laboratorio'

 # Prior V1 has been staged successfully by the operator. Verify, NEVER alter it.
 $v1=Join-Path $kit 'kx_https_cutover_bundle_v1_NOT_ARMED'
 KX-CheckPath $v1 $true
 KX-Check ((Get-Acl -LiteralPath $v1).AreAccessRulesProtected) 'V1 sigue privado e independiente'
 # Release V3 MUST preserve both prior review snapshots unchanged.
 $v2=Join-Path $kit 'kx_https_cutover_bundle_v2_NOT_ARMED'
 KX-CheckPath $v2 $true
 KX-Check ((Get-Acl -LiteralPath $v2).AreAccessRulesProtected) 'V2 reviewed bundle private'
 $v2Package=Get-Content -LiteralPath (Join-Path $v2 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 $v2State=Get-Content -LiteralPath (Join-Path $v2 'transaction.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Check ($v2Package.mode -ceq 'prod_cutover_bundle_prepared_not_armed_v2' -and
   $v2Package.tasks_registered -eq $false -and
   $v2State.phase -ceq 'PREPARED' -and
   $v2State.recovery_task_armed -eq $false -and
   $v2State.production_modified -eq $false) 'V2 reviewed snapshot unchanged and unarmed'

 $v1Package=Get-Content -LiteralPath (Join-Path $v1 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Check ($v1Package.schema_version -eq 1 -and
   $v1Package.mode -ceq 'prod_cutover_bundle_prepared_not_armed' -and
   $v1Package.tasks_registered -eq $false -and
   $v1Package.caddy_live_changed -eq $false -and
   $v1Package.launcher_live_changed -eq $false) 'Paquete V1 nunca activado'
 foreach($name in @('caddy_original','launcher_original','caddy_candidate','launcher_candidate')){
  KX-Check ([string]$v1Package.hashes.$name -ceq [string]$expected[$name]) ('Hash original V1 inalterado: '+$name)
 }
 KX-Check (@(Get-ScheduledTask -ErrorAction Stop|Where-Object {$_.TaskName -like 'VehiculoIoT-KX-PROD-Recovery-*'}).Count -eq 0) 'V1 no dejo watchdog productivo'

 $phase='PRIVATE_BUNDLE_COPY'
 New-Item -ItemType Directory -Path $target -ErrorAction Stop|Out-Null
 & icacls.exe $target /inheritance:r|Out-Null
 KX-Check ($LASTEXITCODE -eq 0) 'ACL herencia retirada'
 & icacls.exe $target /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
 KX-Check ($LASTEXITCODE -eq 0) 'ACL solo SYSTEM/Administradores'
 KX-Check ((Get-Acl -LiteralPath $target).AreAccessRulesProtected) 'Bundle privado'
 $names=@{
  caddy_original='Caddyfile.original'
  launcher_original='run_caddy.original.ps1'
  caddy_candidate='Caddyfile.candidate.NOT_ACTIVE'
  launcher_candidate='run_caddy.candidate.NOT_ACTIVE.ps1'
  task_xml='VehiculoIoT-Caddy.original.task.xml'
  controller='kx_prod_cutover_controller_v3_RELEASE.ps1'
  recoverer='kx_prod_recoverer_v3_RELEASE.ps1'
 }
 foreach($k in $names.Keys){
  $destination=Join-Path $target $names[$k]
  [IO.File]::Copy([string]$src[$k],$destination,$false)
  KX-Check ((KX-Hash $destination) -ceq (KX-Hash $src[$k])) ('Copia privada '+$k)
 }
 $hashes=[ordered]@{}
 foreach($k in $names.Keys){$hashes[$k]=KX-Hash (Join-Path $target $names[$k])}
 $pkg=[ordered]@{
  schema_version=1
  mode='prod_cutover_bundle_v3_release_ready'
  release_enabled=$true
  recovery_enabled=$true
  requires_explicit_cutover_switch=$true
  timestamp_utc=[DateTime]::UtcNow.ToString('o')
  source_commit='898c3225514f8de46a957c52191010d593f22cda'
  task_name='VehiculoIoT-Caddy'
  public_hostname='100-30-4-62.nip.io'
  caddy_live_changed=$false
  launcher_live_changed=$false
  tasks_registered=$false
  https_interrupted=$false
  physical_control_enabled=$false
  hashes=$hashes
 }
 $pkg|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $target 'package.json') -Encoding UTF8
 $transaction=[ordered]@{
  schema_version=1
  transaction_id=[guid]::NewGuid().ToString('N')
  phase='PREPARED'
  updated_utc=[DateTime]::UtcNow.ToString('o')
  recovery_task_armed=$false
  production_modified=$false
 }
 $transaction|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $target 'transaction.json') -Encoding UTF8
 [IO.File]::WriteAllText((Join-Path $target 'transaction.lock'),'K-X Prepared but NOT ARMED',[Text.UTF8Encoding]::new($false))
 KX-Check ((Get-ScheduledTask -TaskPath '\' -TaskName $task).State -eq 'Running') 'Tarea Caddy original Running al terminar'
 KX-Check ((KX-Hash $originalCaddyLive) -ceq $expected.caddy_original -and
   (KX-Hash $originalLauncherLive) -ceq $expected.launcher_original) 'Archivos originales intactos al terminar'
 KX-Check (@(Get-ScheduledTask -ErrorAction Stop|Where-Object {$_.TaskName -like 'VehiculoIoT-KX-PROD-Recovery-*'}).Count -eq 0) 'No hay tareas de recuperacion productiva armadas'
 $phase='COMPLETE'
 $success=$true
 Write-Host ''
 Write-Host '=== RESULTADO: CANDIDATO V3 PREPARADO, SIN ACTIVAR HTTPS ===' -ForegroundColor Green
 Write-Host 'COPIAS ORIGINALES/CANDIDATAS: PROTEGIDAS Y VERIFICADAS'
 Write-Host 'CONTROLADOR Y RECUPERADOR: V3 PREPARADOS; NO INVOCADOS'
 Write-Host 'HTTPS 443: SIN RESTART NI CAMBIOS'
 Write-Host 'TAREAS PRODUCTIVAS: INTACTAS, SIN WATCHDOG REGISTRADO'
 Write-Host 'PUBLICACION: PENDIENTE CUTOVER EXPLICITO; NO SE REGISTRO WATCHDOG'
}catch{
 Write-Host ('=== NO-GO PAQUETE K-X / '+$phase+' ===') -ForegroundColor Red
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host 'No reintentar si la carpeta privada se creo; no modificar Caddy.'
}
if(-not $success){exit 1}
exit 0
