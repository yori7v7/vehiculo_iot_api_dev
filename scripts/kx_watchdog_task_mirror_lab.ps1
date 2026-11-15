# K-X: Scheduled Task watchdog LAB for mirrored files ONLY. Windows PowerShell 5.1.
# Registers unique triggerless temporary tasks under SYSTEM. NEVER modifies real tasks/files.
# Tests worker crash at two replacement boundaries and successful simulated commit.
param(
 [Parameter(Mandatory=$true)][ValidateSet('FixtureCI','EC2CopyLab')][string]$Mode,
 [ValidateSet('Driver','Worker','Watchdog')][string]$Role='Driver',
 [string]$CaseDir=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$ok=$false
$root=$null
$known=@('FAIL_AFTER_FIRST','FAIL_AFTER_SECOND','COMMIT_SUCCESS')
$liveCaddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$liveLauncher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$launcherHash='873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
function Check([bool]$yes,[string]$label){
 if(-not $yes){throw ('NO-GO: '+$label)}
 if($Role -ceq 'Driver'){Write-Host ('OK: '+$label) -ForegroundColor Green}
}
function Hash([string]$p){return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}
function Same([string]$p,[string]$h,[string]$label){
 Check (Test-Path -LiteralPath $p -PathType Leaf) ($label+' existe')
 Check ((Hash $p) -ceq $h) ($label+' SHA256')
}
function Normal([string]$p){
 Check (Test-Path -LiteralPath $p) 'Ruta existente'
 Check (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Ruta sin redireccion'
}
function ValidateCase {
 Check (-not [string]::IsNullOrWhiteSpace($CaseDir)) 'CaseDir definido'
 $case=[IO.Path]::GetFullPath($CaseDir)
 $r=[IO.Path]::GetDirectoryName($case).TrimEnd('\')
 Check ($known -ccontains [IO.Path]::GetFileName($case)) 'Caso autorizado'
 if($Mode -ceq 'EC2CopyLab'){
  Check ([string]::Equals($r,'C:\ProgramData\VehiculoIoT-KX-Installer\kx_watchdog_task_lab_v1',[StringComparison]::OrdinalIgnoreCase)) 'Lab EC2 confinado'
 }else{
  Check ([IO.Path]::GetFileName($r) -match '^KX-Task-Watchdog-CI-[a-f0-9]{32}$') 'Lab CI confinado'
 }
 Check ([string]::Equals([IO.Path]::GetFullPath($PSCommandPath),
   [IO.Path]::Combine($r,'kx_watchdog_task_lab_worker.ps1'),[StringComparison]::OrdinalIgnoreCase)) 'Script ejecutado desde lab privado'
 Normal $r
 Check ((Get-Acl -LiteralPath $r).AreAccessRulesProtected) 'Raiz lab con ACL protegida'
 Normal $case
 $script:root=$r
 $script:CaseDir=$case
 foreach($name in @('old_caddy','old_launcher','new_caddy','new_launcher','Caddyfile.MIRROR','run_caddy.MIRROR.ps1','hashes.json')){
  Normal (Join-Path $case $name)
 }
}
function Files {
 $h=Get-Content -LiteralPath (Join-Path $CaseDir 'hashes.json') -Raw|ConvertFrom-Json
 Same (Join-Path $CaseDir 'old_caddy') ([string]$h.old_caddy) 'Original Caddy'
 Same (Join-Path $CaseDir 'old_launcher') ([string]$h.old_launcher) 'Original launcher'
 Same (Join-Path $CaseDir 'new_caddy') ([string]$h.new_caddy) 'Candidato Caddy'
 Same (Join-Path $CaseDir 'new_launcher') ([string]$h.new_launcher) 'Candidato launcher'
 return $h
}
function Swap([string]$source,[string]$target,[string]$backup,[string]$hash) {
 $prefix=$CaseDir.TrimEnd('\')+'\'
 foreach($p in @($source,$target,$backup)){
  Check ([IO.Path]::GetFullPath($p).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) 'Ruta de reemplazo limitada al espejo'
 }
 Check (-not (Test-Path -LiteralPath $backup)) 'Backup temporal libre'
 $incoming=$target+'.incoming'
 Check (-not (Test-Path -LiteralPath $incoming)) 'Temporal libre'
 [IO.File]::Copy($source,$incoming,$false)
 Same $incoming $hash 'Archivo entrante'
 [IO.File]::Replace($incoming,$target,$backup)
 Same $target $hash 'Archivo espejado'
}
function Restore {
 $h=Files
 $a=Join-Path $CaseDir 'Caddyfile.MIRROR'
 $b=Join-Path $CaseDir 'run_caddy.MIRROR.ps1'
 if((Hash $a) -cne [string]$h.old_caddy){
  Swap (Join-Path $CaseDir 'old_caddy') $a (Join-Path $CaseDir 'retired_caddy.bak') ([string]$h.old_caddy)
 }
 if((Hash $b) -cne [string]$h.old_launcher){
  Swap (Join-Path $CaseDir 'old_launcher') $b (Join-Path $CaseDir 'retired_launcher.bak') ([string]$h.old_launcher)
 }
 Same $a ([string]$h.old_caddy) 'Caddy restaurado'
 Same $b ([string]$h.old_launcher) 'Launcher restaurado'
}
function Marker([string]$name,[string]$text){
 [IO.File]::WriteAllText((Join-Path $CaseDir $name),$text,[Text.UTF8Encoding]::new($false))
}
function MatchWorker($x){
 $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$x.pid) -ErrorAction SilentlyContinue
 if($null -eq $proc){return $false}
 return ($proc.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$x.creation_ticks -and
 [string]::Equals([string]$proc.ExecutablePath,[string]$x.executable_path,[StringComparison]::OrdinalIgnoreCase))
}
function Worker {
 ValidateCase
 $h=Files
 $c=Join-Path $CaseDir 'Caddyfile.MIRROR'
 $l=Join-Path $CaseDir 'run_caddy.MIRROR.ps1'
 Same $c ([string]$h.old_caddy) 'Caddy inicial'
 Same $l ([string]$h.old_launcher) 'Launcher inicial'
 $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$PID) -ErrorAction Stop
 $id=[ordered]@{pid=[int]$PID;creation_ticks=$proc.CreationDate.ToUniversalTime().Ticks.ToString();executable_path=[string]$proc.ExecutablePath}
 $id|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $CaseDir 'worker.json') -Encoding UTF8
 Swap (Join-Path $CaseDir 'new_caddy') $c (Join-Path $CaseDir 'forward_caddy.bak') ([string]$h.new_caddy)
 if([IO.Path]::GetFileName($CaseDir) -ceq 'FAIL_AFTER_FIRST'){
  Marker 'stage.flag' 'ONE_REPLACED'
  while($true){Start-Sleep -Milliseconds 200}
 }
 Swap (Join-Path $CaseDir 'new_launcher') $l (Join-Path $CaseDir 'forward_launcher.bak') ([string]$h.new_launcher)
 if([IO.Path]::GetFileName($CaseDir) -ceq 'FAIL_AFTER_SECOND'){
  Marker 'stage.flag' 'BOTH_REPLACED'
  while($true){Start-Sleep -Milliseconds 200}
 }
 Marker 'committed.flag' 'SIMULATED_LAB_ONLY'
}
function Watchdog {
 ValidateCase
 $me=[Security.Principal.WindowsIdentity]::GetCurrent()
 Check ($me.User.Value -ceq 'S-1-5-18') 'Watchdog SYSTEM real'
 $h=Files
 $identityPath=Join-Path $CaseDir 'worker.json'
 Check (Test-Path -LiteralPath $identityPath -PathType Leaf) 'Worker registrado'
 $identity=Get-Content -LiteralPath $identityPath -Raw|ConvertFrom-Json
 Check (-not (MatchWorker $identity)) 'Worker ya no esta ejecutando'
 $committed=Join-Path $CaseDir 'committed.flag'
 if(Test-Path -LiteralPath $committed -PathType Leaf){
  Check ([IO.File]::ReadAllText($committed) -ceq 'SIMULATED_LAB_ONLY') 'Commit ficticio exacto'
  Same (Join-Path $CaseDir 'Caddyfile.MIRROR') ([string]$h.new_caddy) 'Caddy candidato confirmado'
  Same (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') ([string]$h.new_launcher) 'launcher candidato confirmado'
  Marker 'watchdog.result' 'NO_ROLLBACK_ON_SUCCESS'
 }else{
  Check (Test-Path -LiteralPath (Join-Path $CaseDir 'stage.flag')) 'Fallo de worker ocurre tras reemplazo'
  Restore
  Marker 'watchdog.result' 'RESTORED_BOTH_AFTER_CRASH'
 }
}
function LaunchWorker {
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $workerPath=Join-Path $root 'kx_watchdog_task_lab_worker.ps1'
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$workerPath+'" -Mode '+$Mode+' -Role Worker -CaseDir "'+$CaseDir+'"'
 return Start-Process -FilePath $exe -ArgumentList $args -WindowStyle Hidden -PassThru -ErrorAction Stop
}
function Await([string]$p,[int]$maxSeconds){
 for($i=0;$i -lt $maxSeconds*10;$i++){
  if(Test-Path -LiteralPath $p -PathType Leaf){return $true}
  Start-Sleep -Milliseconds 100
 }
 return $false
}
function TaskCase([string]$name,[string]$inputs){
 $script:CaseDir=Join-Path $root $name
 [IO.Directory]::CreateDirectory($CaseDir)|Out-Null
 foreach($n in @('old_caddy','old_launcher','new_caddy','new_launcher')){
  [IO.File]::Copy((Join-Path $inputs $n),(Join-Path $CaseDir $n),$false)
 }
 [IO.File]::Copy((Join-Path $CaseDir 'old_caddy'),(Join-Path $CaseDir 'Caddyfile.MIRROR'),$false)
 [IO.File]::Copy((Join-Path $CaseDir 'old_launcher'),(Join-Path $CaseDir 'run_caddy.MIRROR.ps1'),$false)
 $h=[ordered]@{old_caddy=Hash (Join-Path $CaseDir 'old_caddy');old_launcher=Hash (Join-Path $CaseDir 'old_launcher');new_caddy=Hash (Join-Path $CaseDir 'new_caddy');new_launcher=Hash (Join-Path $CaseDir 'new_launcher')}
 $h | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $CaseDir 'hashes.json') -Encoding UTF8
 $taskName='VehiculoIoT-KX-LAB-Watchdog-'+[guid]::NewGuid().ToString('N')
 $registered=$false
 $worker=$null
 $clean=$true
 try{
  $scriptPath=Join-Path $root 'kx_watchdog_task_lab_worker.ps1'
  $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'" -Mode '+$Mode+' -Role Watchdog -CaseDir "'+$CaseDir+'"'
  $action=New-ScheduledTaskAction -Execute $exe -Argument $args
  $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
  Check ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)) 'Tarea LAB disponible'
  Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Action $action -Principal $principal -Settings $settings -ErrorAction Stop|Out-Null
  $registered=$true
  Check ((Get-ScheduledTask -TaskPath '\' -TaskName $taskName).Principal.UserId -match '^(SYSTEM|S-1-5-18|NT AUTHORITY\\SYSTEM)$') 'Tarea temporal solo SYSTEM'
  $worker=LaunchWorker
  Check (Await (Join-Path $CaseDir 'worker.json') 10) 'Worker real registrado'
  if($name -ceq 'COMMIT_SUCCESS'){
   Check ($worker.WaitForExit(12000)) 'Worker simulado completa'
   Check ($worker.ExitCode -eq 0) 'Worker simulado finaliza sin error'
   Check (Test-Path -LiteralPath (Join-Path $CaseDir 'committed.flag')) 'Commit ficticio creado'
  }else{
   Check (Await (Join-Path $CaseDir 'stage.flag') 10) 'Punto de fallo ficticio alcanzado'
   $id=Get-Content -LiteralPath (Join-Path $CaseDir 'worker.json') -Raw|ConvertFrom-Json
   Check ([int]$id.pid -eq [int]$worker.Id -and (MatchWorker $id)) 'Worker exacto antes de terminar'
   $worker.Kill()
   Check ($worker.WaitForExit(5000)) 'Solo Worker de laboratorio terminado'
  }
  Start-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
  Check (Await (Join-Path $CaseDir 'watchdog.result') 20) 'Watchdog SYSTEM de tarea independiente finalizo'
  for($i=0;$i -lt 60;$i++){
   if((Get-ScheduledTask -TaskPath '\' -TaskName $taskName).State -ne 'Running'){break}
   Start-Sleep -Milliseconds 100
  }
  Check ((Get-ScheduledTaskInfo -TaskPath '\' -TaskName $taskName).LastTaskResult -eq 0) 'Tarea watchdog termino 0'
  $result=[IO.File]::ReadAllText((Join-Path $CaseDir 'watchdog.result'))
  if($name -ceq 'COMMIT_SUCCESS'){
   Check ($result -ceq 'NO_ROLLBACK_ON_SUCCESS') 'Sin falso rollback tras commit'
   Same (Join-Path $CaseDir 'Caddyfile.MIRROR') ([string]$h.new_caddy) 'Caddy candidato se preserva'
   Same (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') ([string]$h.new_launcher) 'launcher candidato se preserva'
   # Clean up successful mirror explicitly, never production.
   $incomingC=Join-Path $CaseDir 'cleanup_caddy.incoming'
   $incomingL=Join-Path $CaseDir 'cleanup_launcher.incoming'
   [IO.File]::Copy((Join-Path $CaseDir 'old_caddy'),$incomingC,$false)
   [IO.File]::Copy((Join-Path $CaseDir 'old_launcher'),$incomingL,$false)
   [IO.File]::Replace($incomingC,(Join-Path $CaseDir 'Caddyfile.MIRROR'),(Join-Path $CaseDir 'cleanup_caddy.bak'))
   [IO.File]::Replace($incomingL,(Join-Path $CaseDir 'run_caddy.MIRROR.ps1'),(Join-Path $CaseDir 'cleanup_launcher.bak'))
  }else{
   Check ($result -ceq 'RESTORED_BOTH_AFTER_CRASH') 'Rollback ejecutado por SYSTEM independiente'
  }
  Same (Join-Path $CaseDir 'Caddyfile.MIRROR') ([string]$h.old_caddy) 'Caddy final original'
  Same (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') ([string]$h.old_launcher) 'launcher final original'
 }
 finally{
  if($null -ne $worker){
   try {if(-not $worker.HasExited){$worker.Kill();$null=$worker.WaitForExit(5000)}} catch {$clean=$false}
   $worker.Dispose()
  }
  if($registered){
   try {
    $t=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    if($t.State -eq 'Running'){
     Stop-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
     Start-Sleep -Milliseconds 250
    }
    Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Check ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)) 'Tarea LAB eliminada'
   }catch {$clean=$false;Write-Host 'NO-GO: tarea temporal no eliminada' -ForegroundColor Red}
  }
  if(-not $clean){throw 'NO-GO: limpieza de laboratorio incompleta'}
 }
 Write-Host ('OK: tarea SYSTEM independiente '+$name+' y limpieza verificada') -ForegroundColor Green
}
function Driver {
 $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Administrador elevado'
 if($Mode -ceq 'FixtureCI'){
  Check ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'Runner Windows CI confirmado'
  $script:root=Join-Path $env:TEMP ('KX-Task-Watchdog-CI-'+[guid]::NewGuid().ToString('N'))
  $sources=$null
 }else{
  $script:root='C:\ProgramData\VehiculoIoT-KX-Installer\kx_watchdog_task_lab_v1'
  $kit='C:\ProgramData\VehiculoIoT-KX-Installer'
  $manifest=Get-Content -LiteralPath 'C:\ProgramData\VehiculoIoT-KX-State\service\install.json' -Raw|ConvertFrom-Json
  Check ($manifest.mode -ceq 'loopback_only_not_public' -and $manifest.caddy_changed -eq $false -and $manifest.physical_control_enabled -eq $false) 'Virtual aislado, fisico OFF'
  $rel=Join-Path $kit 'kx_https_public_release_v1_offline'
  $stage=Join-Path $rel 'launcher_staging_v1'
  $prep=Get-Content -LiteralPath (Join-Path $rel 'preparation.json') -Raw|ConvertFrom-Json
  $sr=Get-Content -LiteralPath (Join-Path $stage 'launcher_stage_report.json') -Raw|ConvertFrom-Json
  $sources=@{
   old_caddy=Join-Path $kit 'kx_caddy_release_preflight\Caddyfile.original.copy'
   old_launcher=Join-Path $stage 'run_caddy.original.backup.ps1'
   new_caddy=Join-Path $rel 'Caddyfile.kx.ready.NOT_ACTIVE'
   new_launcher=Join-Path $stage 'run_caddy.kx.pending.ps1'
  }
  Same $sources.old_caddy ([string]$manifest.original_caddy_sha256) 'Caddy original respaldado'
  Same $sources.old_launcher $launcherHash 'Launcher original respaldado'
  Same $sources.new_caddy ([string]$prep.candidate_sha256) 'Caddy candidato respaldado'
  Same $sources.new_launcher ([string]$sr.launcher_candidate_sha256) 'launcher candidato respaldado'
  Same $liveCaddy ([string]$manifest.original_caddy_sha256) 'Caddy publico intacto inicialmente'
  Same $liveLauncher $launcherHash 'Launcher publico intacto inicialmente'
  foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
   Check ((Get-ScheduledTask -TaskPath '\' -TaskName $name).State -eq 'Running') ($name+' Running')
  }
 }
 Check (-not (Test-Path -LiteralPath $root)) 'Nueva carpeta de laboratorio'
 [IO.Directory]::CreateDirectory($root)|Out-Null
 & icacls.exe $root /inheritance:r|Out-Null
 Check ($LASTEXITCODE -eq 0) 'Herencia NTFS retirada'
 & icacls.exe $root /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
 Check ($LASTEXITCODE -eq 0) 'ACL SYSTEM y Administradores'
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) 'Lab privado'
 $workerScript=Join-Path $root 'kx_watchdog_task_lab_worker.ps1'
 [IO.File]::Copy($PSCommandPath,$workerScript,$false)
 Check ((Hash $workerScript) -ceq (Hash $PSCommandPath)) 'Worker script identico al descargado'
 $inputs=Join-Path $root 'inputs'
 [IO.Directory]::CreateDirectory($inputs)|Out-Null
 if($Mode -ceq 'FixtureCI'){
  [IO.File]::WriteAllText((Join-Path $inputs 'old_caddy'),'ORIGINAL CADDY',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'old_launcher'),'ORIGINAL LAUNCHER',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'new_caddy'),'CANDIDATE CADDY',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'new_launcher'),'CANDIDATE LAUNCHER',[Text.UTF8Encoding]::new($false))
 }else{
  foreach($key in @('old_caddy','old_launcher','new_caddy','new_launcher')){
   [IO.File]::Copy([string]$sources[$key],(Join-Path $inputs $key),$false)
  }
 }
 foreach($case in $known){
  Write-Host ('--- '+$case+' ---') -ForegroundColor Cyan
  TaskCase $case $inputs
 }
 if($Mode -ceq 'EC2CopyLab'){
  Same $liveCaddy ([string]$manifest.original_caddy_sha256) 'Caddy publico intacto al final'
  Same $liveLauncher $launcherHash 'Launcher publico intacto al final'
 }
 Write-Host '=== RESULTADO: TAREA WATCHDOG SYSTEM AISLADA APROBADA ===' -ForegroundColor Green
 Write-Host '3 CASOS: FAIL_AFTER_FIRST, FAIL_AFTER_SECOND, COMMIT_SUCCESS'
 Write-Host 'TAREAS LAB: ELIMINADAS; TAREAS ORIGINALES: NO MODIFICADAS'
 Write-Host 'HTTPS 443 Y CONTROL FISICO: SIN MODIFICAR'
 Write-Host 'NO SE HA PROBADO REINICIO WINDOWS, CIERRE RDP NI RECUPERACION REAL 443'
}
try {
 if($Role -ceq 'Driver'){Driver}
 elseif($Role -ceq 'Worker'){Worker}
 else{Watchdog}
 $ok=$true
}
catch{
 Write-Host ('=== NO-GO WATCHDOG POR TAREA / '+$Role+' ===') -ForegroundColor Red
 Write-Host ('FASE: '+$Role+'; ERROR: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 if($Mode -ceq 'FixtureCI'){Write-Host ('CI detalle: '+$_.Exception.Message)}
}
if(-not $ok){exit 1}
exit 0
