# K-X: isolated watchdog simulation after operator process termination.
# Windows PowerShell 5.1. NO tasks/services/ports/production file writes.
# This only proves independent process-level mirror recovery; it is NOT a production watchdog.
param(
 [Parameter(Mandatory=$true)][ValidateSet('FixtureCI','EC2CopyLab')][string]$Mode,
 [ValidateSet('Driver','Worker','Watchdog')][string]$Role='Driver',
 [string]$CaseDir=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$global:success=$false
$labRoot=$null
$originalCaddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$originalLauncher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$originalLauncherHash='873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
$cases=@('FAIL_AFTER_FIRST','FAIL_AFTER_SECOND','COMMIT_SUCCESS')
function Check([bool]$ok,[string]$label) {
 if(-not $ok){throw ('NO-GO: '+$label)}
 if($Role -ceq 'Driver'){Write-Host ('OK: '+$label) -ForegroundColor Green}
}
function Hash([string]$p){return (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash}
function RequireHash([string]$p,[string]$hash,[string]$label){
 Check (Test-Path -LiteralPath $p -PathType Leaf) ('Archivo existe: '+$label)
 Check ((Hash $p) -ceq $hash) ('SHA256 '+$label)
}
function Normal([string]$p) {
 Check (Test-Path -LiteralPath $p) 'Ruta requerida existe'
 Check (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Ruta no redirigida'
}
function WriteMarker([string]$name,[string]$value){
 $p=Join-Path $CaseDir $name
 [IO.File]::WriteAllText($p,$value,[Text.UTF8Encoding]::new($false))
}
function VerifyCase {
 Check (-not [string]::IsNullOrWhiteSpace($CaseDir)) 'Directorio de caso definido'
 $full=[IO.Path]::GetFullPath($CaseDir)
 if($Mode -ceq 'EC2CopyLab') {
  $labRoot='C:\ProgramData\VehiculoIoT-KX-Installer\kx_watchdog_process_lab_v1'
  Check ($full.StartsWith($labRoot+'\',[StringComparison]::OrdinalIgnoreCase)) 'Caso dentro del laboratorio privado'
 }
 else {
  Check ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'Worker exclusivo del runner Windows'
  Check ([IO.Path]::GetFileName([IO.Path]::GetDirectoryName($full)) -like 'KX-Watchdog-CI-*') 'Caso de fixture CI'
 }
 Check ($cases -contains [IO.Path]::GetFileName($full)) 'Nombre de caso permitido'
 Normal $full
 $acl=Get-Acl -LiteralPath $full
 Check ($acl.AreAccessRulesProtected) 'Caso sin herencia NTFS'
 foreach($name in @('original_caddy','original_launcher','candidate_caddy','candidate_launcher',
                     'Caddyfile.mirror','run_caddy.mirror.ps1','hashes.json','armed.flag')){
  Normal (Join-Path $full $name)
 }
 $script:CaseDir=$full
}
function Inputs {
 $h=Get-Content -LiteralPath (Join-Path $CaseDir 'hashes.json') -Raw|ConvertFrom-Json
 RequireHash (Join-Path $CaseDir 'original_caddy') ([string]$h.caddy) 'original Caddy en espejo'
 RequireHash (Join-Path $CaseDir 'original_launcher') ([string]$h.launcher) 'original launcher en espejo'
 RequireHash (Join-Path $CaseDir 'candidate_caddy') ([string]$h.new_caddy) 'candidato Caddy en espejo'
 RequireHash (Join-Path $CaseDir 'candidate_launcher') ([string]$h.new_launcher) 'candidato launcher en espejo'
 return $h
}
function ReplaceMirror([string]$source,[string]$destination,[string]$backup,[string]$expected){
 $prefix=[IO.Path]::GetFullPath($CaseDir).TrimEnd('\')+'\'
 foreach($p in @($source,$destination,$backup)){
  Check ([IO.Path]::GetFullPath($p).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) 'Ruta confinada al laboratorio'
 }
 Normal $source
 Normal $destination
 Check (-not (Test-Path -LiteralPath $backup)) 'Respaldo temporal disponible'
 $temp=$destination+'.incoming'
 Check (-not (Test-Path -LiteralPath $temp)) 'Temporal disponible'
 [IO.File]::Copy($source,$temp,$false)
 RequireHash $temp $expected 'archivo entrante'
 [IO.File]::Replace($temp,$destination,$backup)
 RequireHash $destination $expected 'espejo sustituido'
}
function Restore {
 $h=Inputs
 $tC=Join-Path $CaseDir 'Caddyfile.mirror'
 $tL=Join-Path $CaseDir 'run_caddy.mirror.ps1'
 if((Hash $tC) -cne [string]$h.caddy){
  ReplaceMirror (Join-Path $CaseDir 'original_caddy') $tC (Join-Path $CaseDir 'rollback_caddy.bak') ([string]$h.caddy)
 }
 if((Hash $tL) -cne [string]$h.launcher){
  ReplaceMirror (Join-Path $CaseDir 'original_launcher') $tL (Join-Path $CaseDir 'rollback_launcher.bak') ([string]$h.launcher)
 }
 RequireHash $tC ([string]$h.caddy) 'Caddy restaurado'
 RequireHash $tL ([string]$h.launcher) 'launcher restaurado'
}
function LockName {
 # CaseDir is unique. Hash-derived name contains no paths, supports multiprocess locking.
 $bytes=[Text.Encoding]::UTF8.GetBytes($CaseDir.ToUpperInvariant())
 $sha=[Security.Cryptography.SHA256]::Create()
 try {$hash=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','')}
 finally {$sha.Dispose()}
 return 'Local\KX_MIRROR_'+$hash.Substring(0,32)
}
function LockLab {
 $m=[Threading.Mutex]::new($false,(LockName))
 $owned=$false
 try {
  try { $owned=$m.WaitOne(8000) }
  catch [Threading.AbandonedMutexException] { $owned=$true }
  Check $owned 'Mutex obtenido'
  return $m
 }
 catch {
  $m.Dispose()
  throw
 }
}
function ProcessStillMatches($identity){
 $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$identity.pid) -ErrorAction SilentlyContinue
 if($null -eq $process){return $false}
 return ($process.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$identity.creation_ticks -and
         [string]::Equals([string]$process.ExecutablePath,[string]$identity.image,[StringComparison]::OrdinalIgnoreCase))
}
function WorkerMain {
 VerifyCase
 $h=Inputs
 Check (-not (Test-Path -LiteralPath (Join-Path $CaseDir 'worker.json'))) 'Identidad worker nueva'
 $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$PID) -ErrorAction Stop
 [ordered]@{
  pid=[int]$PID
  creation_ticks=$proc.CreationDate.ToUniversalTime().Ticks.ToString()
  image=[string]$proc.ExecutablePath
 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $CaseDir 'worker.json') -Encoding UTF8
 $mutex=LockLab
 try {
  $tC=Join-Path $CaseDir 'Caddyfile.mirror'
  $tL=Join-Path $CaseDir 'run_caddy.mirror.ps1'
  RequireHash $tC ([string]$h.caddy) 'Caddy origen'
  RequireHash $tL ([string]$h.launcher) 'launcher origen'
  ReplaceMirror (Join-Path $CaseDir 'candidate_caddy') $tC (Join-Path $CaseDir 'first_patch.bak') ([string]$h.new_caddy)
  if([IO.Path]::GetFileName($CaseDir) -ceq 'FAIL_AFTER_FIRST'){
   WriteMarker 'stage.flag' 'FIRST_REPLACED'
   while($true){Start-Sleep -Milliseconds 200}
  }
  ReplaceMirror (Join-Path $CaseDir 'candidate_launcher') $tL (Join-Path $CaseDir 'second_patch.bak') ([string]$h.new_launcher)
  if([IO.Path]::GetFileName($CaseDir) -ceq 'FAIL_AFTER_SECOND'){
   WriteMarker 'stage.flag' 'BOTH_REPLACED'
   while($true){Start-Sleep -Milliseconds 200}
  }
  RequireHash $tC ([string]$h.new_caddy) 'Caddy candidato'
  RequireHash $tL ([string]$h.new_launcher) 'launcher candidato'
  WriteMarker 'committed.flag' 'SIMULATED_SUCCESS_NO_PUBLICATION'
 }
 finally {
  $mutex.ReleaseMutex()
  $mutex.Dispose()
 }
}
function WatchdogMain {
 VerifyCase
 $h=Inputs
 # Hard, non-renewable lab timeout. A real watchdog requires additional service safety checks.
 Start-Sleep -Seconds 7
 $mutex=LockLab
 try {
  $committed=Join-Path $CaseDir 'committed.flag'
  if(Test-Path -LiteralPath $committed -PathType Leaf) {
   RequireHash (Join-Path $CaseDir 'Caddyfile.mirror') ([string]$h.new_caddy) 'Caddy candidato comprometido'
   RequireHash (Join-Path $CaseDir 'run_caddy.mirror.ps1') ([string]$h.new_launcher) 'launcher candidato comprometido'
   WriteMarker 'watchdog_result.flag' 'DISARMED_SIMULATED_COMMIT'
   return
  }
  $identityPath=Join-Path $CaseDir 'worker.json'
  Check (Test-Path -LiteralPath $identityPath -PathType Leaf) 'Identidad de ejecutor presente'
  $id=Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
  Check (-not (ProcessStillMatches $id)) 'Ejecutor terminado, sin carrera de archivos'
  Restore
  WriteMarker 'watchdog_result.flag' 'RECOVERED_MIRRORS_AFTER_CRASH'
 }
 finally {
  $mutex.ReleaseMutex()
  $mutex.Dispose()
 }
}
function StartRole([string]$role) {
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Mode '+$Mode+' -Role '+$role+' -CaseDir "'+$CaseDir+'"'
 return Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $CaseDir -WindowStyle Hidden -PassThru -ErrorAction Stop
}
function WaitMarker([string]$path,[int]$seconds) {
 for($i=0;$i -lt ($seconds*10);$i++){
  if(Test-Path -LiteralPath $path -PathType Leaf){return $true}
  Start-Sleep -Milliseconds 100
 }
 return $false
}
function RunCase([string]$name,[string]$inputRoot) {
 $script:CaseDir=Join-Path $labRoot $name
 [IO.Directory]::CreateDirectory($CaseDir)|Out-Null
 & icacls.exe $CaseDir /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) 'Herencia del caso restringida'
 & icacls.exe $CaseDir /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) 'Caso SYSTEM/Administradores'
 foreach($n in @('original_caddy','original_launcher','candidate_caddy','candidate_launcher')){
  [IO.File]::Copy((Join-Path $inputRoot $n),(Join-Path $CaseDir $n),$false)
 }
 [IO.File]::Copy((Join-Path $CaseDir 'original_caddy'),(Join-Path $CaseDir 'Caddyfile.mirror'),$false)
 [IO.File]::Copy((Join-Path $CaseDir 'original_launcher'),(Join-Path $CaseDir 'run_caddy.mirror.ps1'),$false)
 $h=[ordered]@{
  caddy=Hash (Join-Path $CaseDir 'original_caddy')
  launcher=Hash (Join-Path $CaseDir 'original_launcher')
  new_caddy=Hash (Join-Path $CaseDir 'candidate_caddy')
  new_launcher=Hash (Join-Path $CaseDir 'candidate_launcher')
 }
 $h|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $CaseDir 'hashes.json') -Encoding UTF8
 WriteMarker 'armed.flag' 'KX_LAB_ARMED_BEFORE_PROCESS_START'
 $wd=$null
 $worker=$null
 try {
  VerifyCase
  $wd=StartRole 'Watchdog'
  $worker=StartRole 'Worker'
  Check (WaitMarker (Join-Path $CaseDir 'worker.json') 8) 'Identidad worker publicada'
  if($name -ceq 'COMMIT_SUCCESS'){
   Check ($worker.WaitForExit(8000)) 'Worker completo sin interrupcion'
   Check ($worker.ExitCode -eq 0) 'Worker simulado exitoso'
   Check (Test-Path -LiteralPath (Join-Path $CaseDir 'committed.flag')) 'Commit simulado escrito'
  }
  else {
   Check (WaitMarker (Join-Path $CaseDir 'stage.flag') 8) 'Punto de fallo alcanzado'
   $identity=Get-Content -LiteralPath (Join-Path $CaseDir 'worker.json') -Raw|ConvertFrom-Json
   Check ([int]$identity.pid -eq [int]$worker.Id) 'Identidad exacta del worker obtenido'
   Check (ProcessStillMatches $identity) 'Worker sigue vivo antes de la interrupcion'
   # Kill ONLY the exact Process object created by StartRole, not by executable name.
   $worker.Kill()
   Check ($worker.WaitForExit(5000)) 'Worker propio terminado intencionalmente'
  }
  Check ($wd.WaitForExit(22000)) 'Watchdog independiente finalizo'
  Check ($wd.ExitCode -eq 0) 'Watchdog reporta exito'
  $actual=[IO.File]::ReadAllText((Join-Path $CaseDir 'watchdog_result.flag'))
  if($name -ceq 'COMMIT_SUCCESS'){
   Check ($actual -ceq 'DISARMED_SIMULATED_COMMIT') 'Watchdog no restaura falso exito'
   RequireHash (Join-Path $CaseDir 'Caddyfile.mirror') ([string]$h.new_caddy) 'Caddy candidato conservado'
   RequireHash (Join-Path $CaseDir 'run_caddy.mirror.ps1') ([string]$h.new_launcher) 'launcher candidato conservado'
   # Driver's final housekeeping uses the same tested mirror restoration function.
   $m=LockLab
   try{Restore}finally{$m.ReleaseMutex();$m.Dispose()}
  }
  else {
   Check ($actual -ceq 'RECOVERED_MIRRORS_AFTER_CRASH') 'Watchdog restauro despues de interrupcion'
  }
  RequireHash (Join-Path $CaseDir 'Caddyfile.mirror') ([string]$h.caddy) 'Caddy original final'
  RequireHash (Join-Path $CaseDir 'run_caddy.mirror.ps1') ([string]$h.launcher) 'launcher original final'
  Write-Host ('OK: '+$name+' -> ambos archivos originales, proceso independiente') -ForegroundColor Green
 }
 finally {
  if($null -ne $worker){try{if(-not $worker.HasExited){$worker.Kill();$null=$worker.WaitForExit(4000)}}catch{};$worker.Dispose()}
  if($null -ne $wd){try{if(-not $wd.HasExited){$wd.Kill();$null=$wd.WaitForExit(4000)}}catch{};$wd.Dispose()}
 }
}
function DriverMain {
 if($Mode -ceq 'FixtureCI') {
  Check ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'Solo CI Windows'
  $script:labRoot=Join-Path $env:TEMP ('KX-Watchdog-CI-'+[Guid]::NewGuid().ToString('N'))
  Check (-not (Test-Path -LiteralPath $labRoot)) 'CI privado nuevo'
  [IO.Directory]::CreateDirectory($labRoot)|Out-Null
  $script:created=$true
  $inputs=Join-Path $labRoot 'inputs'
  [IO.Directory]::CreateDirectory($inputs)|Out-Null
  [IO.File]::WriteAllText((Join-Path $inputs 'original_caddy'),'LEGACY_ORIGINAL',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'original_launcher'),'LAUNCHER_ORIGINAL',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'candidate_caddy'),'CANDIDATE_ONLY',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputs 'candidate_launcher'),'LAUNCHER_CANDIDATE',[Text.UTF8Encoding]::new($false))
 }
 else {
  $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  Check ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Admin elevado'
  $root='C:\ProgramData\VehiculoIoT-KX-Installer'
  $manifestPath='C:\ProgramData\VehiculoIoT-KX-State\service\install.json'
  $release=Join-Path $root 'kx_https_public_release_v1_offline'
  $stage=Join-Path $release 'launcher_staging_v1'
  $sources=@{
   original_caddy=(Join-Path $root 'kx_caddy_release_preflight\Caddyfile.original.copy')
   original_launcher=(Join-Path $stage 'run_caddy.original.backup.ps1')
   candidate_caddy=(Join-Path $release 'Caddyfile.kx.ready.NOT_ACTIVE')
   candidate_launcher=(Join-Path $stage 'run_caddy.kx.pending.ps1')
  }
  $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
  $prep=Get-Content -LiteralPath (Join-Path $release 'preparation.json') -Raw|ConvertFrom-Json
  $staging=Get-Content -LiteralPath (Join-Path $stage 'launcher_stage_report.json') -Raw|ConvertFrom-Json
  Check ($manifest.mode -ceq 'loopback_only_not_public' -and $manifest.caddy_changed -eq $false -and $manifest.physical_control_enabled -eq $false) 'Virtual/no public/physical OFF'
  Check ($prep.mode -ceq 'offline_public_https_candidate_never_activated') 'Candidato sin activar'
  Check ($staging.mode -ceq 'launcher_candidate_staged_offline_not_installed') 'Launcher sin activar'
  RequireHash $sources.original_caddy ([string]$manifest.original_caddy_sha256) 'Caddy respaldado'
  RequireHash $sources.original_launcher $originalLauncherHash 'launcher respaldado'
  RequireHash $sources.candidate_caddy ([string]$prep.candidate_sha256) 'Caddy candidato'
  RequireHash $sources.candidate_launcher ([string]$staging.launcher_candidate_sha256) 'launcher candidato'
  RequireHash $originalCaddy ([string]$manifest.original_caddy_sha256) 'Caddy vivo intacto'
  RequireHash $originalLauncher $originalLauncherHash 'launcher vivo intacto'
  Check ((Get-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-Caddy').State -ceq 'Running') 'Tarea Caddy intacta'
  Check ((Get-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-FastAPI').State -ceq 'Running') 'FastAPI intacta'
  Check ((Get-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-Admission-Virtual').State -ceq 'Running') 'K-V intacta'
  Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) 'Instalador privado'
  $script:labRoot=Join-Path $root 'kx_watchdog_process_lab_v1'
  Check (-not (Test-Path -LiteralPath $labRoot)) 'Nuevo laboratorio sin sobrescritura'
  [IO.Directory]::CreateDirectory($labRoot)|Out-Null
  $script:created=$true
  & icacls.exe $labRoot /inheritance:r|Out-Null
  Check ($LASTEXITCODE -eq 0) 'Herencia de laboratorio retirada'
  & icacls.exe $labRoot /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
  Check ($LASTEXITCODE -eq 0) 'Lab SYSTEM/Administradores'
  Check ((Get-Acl -LiteralPath $labRoot).AreAccessRulesProtected) 'ACL privada confirmada'
  $inputs=Join-Path $labRoot 'inputs'
  [IO.Directory]::CreateDirectory($inputs)|Out-Null
  foreach($key in @('original_caddy','original_launcher','candidate_caddy','candidate_launcher')){
   [IO.File]::Copy([string]$sources[$key],(Join-Path $inputs $key),$false)
  }
 }
 foreach($name in $cases){
  Write-Host ('--- K-X watchdog LAB: '+$name+' ---') -ForegroundColor Cyan
  RunCase $name $inputs
 }
 if($Mode -ceq 'EC2CopyLab'){
  RequireHash $originalCaddy ([string]$manifest.original_caddy_sha256) 'Caddy publico nunca modificado'
  RequireHash $originalLauncher $originalLauncherHash 'launcher publico nunca modificado'
  $report=[ordered]@{
   mode='isolated_mirror_watchdog_process_rehearsal'
   timestamp_utc=[DateTime]::UtcNow.ToString('o')
   results=@($cases)
   isolated_process_recovered=$true
   real_windows_task_watchdog_armed=$false
   abrupt_operator_console_disconnect_tested=$false
   public_service_rollback_tested=$false
   public_caddy_modified=$false
   physical_control_enabled=$false
  }
  $report|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $labRoot 'watchdog_process_lab_report.json') -Encoding UTF8
 }
 $global:success=$true
 Write-Host '=== RESULTADO: WATCHDOG INDEPENDIENTE EN ESPEJOS APROBADO ===' -ForegroundColor Green
 Write-Host 'FALLO TRAS PRIMER/SEGUNDO ARCHIVO: RECUPERADO DESDE OTRO PROCESO'
 Write-Host 'COMMIT FICTICIO: WATCHDOG DESARMADO, SIN FALSO ROLLBACK'
 Write-Host 'TAREAS REALES, HTTPS 443 Y CONTROL FISICO: INTACTOS'
 Write-Host 'NO ES AUN UN WATCHDOG DURABLE NI UN ROLLBACK DEL SERVICIO REAL'
}
try{
 if($Role -ceq 'Driver'){ DriverMain }
 elseif($Role -ceq 'Worker'){WorkerMain;$global:success=$true}
 elseif($Role -ceq 'Watchdog'){WatchdogMain;$global:success=$true}
}
catch{
 Write-Host ('=== NO-GO K-X WATCHDOG LAB / '+$Role+' ===') -ForegroundColor Red
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 if($Mode -ceq 'FixtureCI'){Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Yellow}
}
finally{
 if($Role -ceq 'Driver' -and $Mode -ceq 'FixtureCI' -and $global:success -and
    (Get-Variable -Name created -Scope Script -ErrorAction SilentlyContinue) -and
    $script:created -and (Test-Path -LiteralPath $labRoot)){
  try{Remove-Item -LiteralPath $labRoot -Recurse -Force -ErrorAction Stop}
  catch{$global:success=$false}
 }
}
if(-not $global:success){exit 1}
exit 0
