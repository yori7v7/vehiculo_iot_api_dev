# K-X integrated HTTPS transaction RECOVERER -- LAB ONLY.
# Windows PowerShell 5.1. Never targets real Caddy, port 443, secrets or production tasks.
# Activated by a one-time SYSTEM task; recovery is independent of the operator session.
param([Parameter(Mandatory=$true)][ValidateSet('FixtureCI','EC2CopyLab')][string]$Mode,
      [Parameter(Mandatory=$true)][string]$CaseDir)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$ok=$false
function Assert-Lab {
 $full=[IO.Path]::GetFullPath($CaseDir).TrimEnd('\')
 $root=[IO.Path]::GetDirectoryName($full)
 if($Mode -ceq 'EC2CopyLab'){
  if(-not [string]::Equals($root,'C:\ProgramData\VehiculoIoT-KX-Installer\kx_integrated_cutover_lab_v1',[StringComparison]::OrdinalIgnoreCase)){throw 'NO-GO: root EC2 LAB'}
 }else{
  if([IO.Path]::GetFileName($root) -notmatch '^KX-Integrated-CI-[a-f0-9]{32}$'){throw 'NO-GO: root CI LAB'}
 }
 if([IO.Path]::GetFileName($full) -notin @('CRASH_AFTER_SECOND','COMMIT_OK')){throw 'NO-GO: case name'}
 foreach($p in @($root,$full)) {
  if(-not (Test-Path -LiteralPath $p -PathType Container)){throw 'NO-GO: missing protected lab'}
  $item=Get-Item -LiteralPath $p -Force
  if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'NO-GO: lab redirection'}
  if(-not (Get-Acl -LiteralPath $p).AreAccessRulesProtected){throw 'NO-GO: lab ACL inheritance'}
 }
 $own=[IO.Path]::GetFullPath($PSCommandPath)
 $expected=Join-Path $root 'kx_integrated_recoverer.ps1'
 if(-not [string]::Equals($own,$expected,[StringComparison]::OrdinalIgnoreCase)){throw 'NO-GO: recoverer not from lab'}
 $who=[Security.Principal.WindowsIdentity]::GetCurrent()
 if($who.User.Value -cne 'S-1-5-18'){throw 'NO-GO: recoverer must run as SYSTEM'}
 $script:CaseDir=$full
}
function Hash([string]$p){return (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash}
function RequireHash([string]$p,[string]$h){
 if(-not(Test-Path -LiteralPath $p -PathType Leaf) -or (Hash $p) -cne $h){throw 'NO-GO: mismatch in LAB file'}
 if(((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'NO-GO: linked LAB file'}
}
function Read-State {return (Get-Content -LiteralPath (Join-Path $CaseDir 'txn.json') -Raw|ConvertFrom-Json)}
function Save-State($s,[string]$newState) {
 $s.phase=$newState
 $s.updated_utc=[DateTime]::UtcNow.ToString('o')
 $p=Join-Path $CaseDir 'txn.json'
 $tmp=$p+'.in'
 if(Test-Path -LiteralPath $tmp){throw 'NO-GO: state temp already exists'}
 $s|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $tmp -Encoding UTF8
 [IO.File]::Replace($tmp,$p,[NullString]::Value)
}
function VerifyState($s){
 if($s.schema -ne 1 -or $s.mode -cne 'isolated_cutover_integrated_lab' -or
    $s.transaction_id -notmatch '^[a-f0-9]{32}$' -or
    [string]::IsNullOrWhiteSpace($s.phase)){throw 'NO-GO: invalid protected state'}
 foreach($field in @('service_task','watchdog_task')){
  $name=[string]$s.$field
  if($name -notmatch '^VehiculoIoT-KX-INT-LAB-(Service|Recovery)-[a-f0-9]{32}$'){throw 'NO-GO: task identity outside laboratory'}
 }
 $name=[string]$s.service_task
 if(-not $name.StartsWith('VehiculoIoT-KX-INT-LAB-Service-')){throw 'NO-GO: wrong service name'}
 if(-not ([string]$s.watchdog_task).StartsWith('VehiculoIoT-KX-INT-LAB-Recovery-')){throw 'NO-GO: wrong watchdog name'}
 foreach($x in @('old_caddy','old_launcher','new_caddy','new_launcher')){
  RequireHash (Join-Path $CaseDir $x) ([string]$s.hashes.$x)
 }
 $root=[IO.Path]::GetDirectoryName($CaseDir)
 RequireHash (Join-Path $root 'kx_integrated_operator.ps1') ([string]$s.hashes.operator_script)
 RequireHash (Join-Path $root 'kx_integrated_recoverer.ps1') ([string]$s.hashes.recover_script)
}
function Take-Lock {
 $path=Join-Path $CaseDir 'exclusive.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: lock timeout'
}
function MockServiceHealthy([string]$expect,[string]$taskName) {
 try {
  $t=Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
  if($t.State -ne 'Running'){return $false}
  $p=Join-Path $CaseDir 'health.json'
  if(-not(Test-Path -LiteralPath $p)){return $false}
  $data=Get-Content -LiteralPath $p -Raw | ConvertFrom-Json
  if($data.mode -cne $expect){return $false}
  $stamp=[DateTime]::Parse([string]$data.utc,[Globalization.CultureInfo]::InvariantCulture,
                            [Globalization.DateTimeStyles]::RoundtripKind)
  if(([DateTime]::UtcNow-$stamp.ToUniversalTime()).TotalSeconds -gt 4){return $false}
  $pr=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$data.pid) -ErrorAction SilentlyContinue
  if($null -eq $pr -or $pr.CreationDate.ToUniversalTime().Ticks.ToString() -cne [string]$data.creation_ticks){return $false}
  if((Invoke-CimMethod -InputObject $pr -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){return $false}
  return $true
 }catch{return $false}
}
function Recover($s) {
 $service=[string]$s.service_task
 $task=Get-ScheduledTask -TaskName $service -TaskPath '\' -ErrorAction Stop
 if($task.Principal.UserId -notmatch '^(SYSTEM|S-1-5-18|NT AUTHORITY\\SYSTEM)$'){throw 'NO-GO: service task changed'}
 $action=@($task.Actions)
 if($action.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$action[0].Arguments) -or
    -not ([string]$action[0].Arguments).Contains((Join-Path ([IO.Path]::GetDirectoryName($CaseDir)) 'kx_integrated_operator.ps1'))){
  throw 'NO-GO: service task action not from lab'
 }
 # Disable first: prevent retries from competing with restoration.
 Disable-ScheduledTask -TaskName $service -TaskPath '\' -ErrorAction Stop|Out-Null
 if((Get-ScheduledTask -TaskName $service -TaskPath '\').State -eq 'Running'){
  Stop-ScheduledTask -TaskName $service -TaskPath '\' -ErrorAction Stop
 }
 for($i=0;$i -lt 50;$i++){
  if((Get-ScheduledTask -TaskName $service -TaskPath '\').State -ne 'Running'){break}
  Start-Sleep -Milliseconds 100
 }
 if((Get-ScheduledTask -TaskName $service -TaskPath '\').State -eq 'Running'){throw 'NO-GO: service still running'}
 Save-State $s 'ROLLBACK_IN_PROGRESS'
 foreach($set in @(@('old_caddy','Caddyfile.MIRROR','rollback_caddy.bak'),@('old_launcher','run_caddy.MIRROR.ps1','rollback_launcher.bak'))){
  $src=Join-Path $CaseDir $set[0]
  $dst=Join-Path $CaseDir $set[1]
  $backup=Join-Path $CaseDir $set[2]
  $h=[string]$s.hashes.($set[0])
  RequireHash $src $h
  if(-not(Test-Path -LiteralPath $dst -PathType Leaf)){throw 'NO-GO: missing mirror'}
  if((Hash $dst) -cne $h) {
   if(Test-Path -LiteralPath $backup){throw 'NO-GO: rollback backup exists'}
   $temp=$dst+'.incoming'
   if(Test-Path -LiteralPath $temp){throw 'NO-GO: incoming exists'}
   [IO.File]::Copy($src,$temp,$false)
   RequireHash $temp $h
   [IO.File]::Replace($temp,$dst,$backup)
   RequireHash $dst $h
  }
 }
 Enable-ScheduledTask -TaskName $service -TaskPath '\' -ErrorAction Stop|Out-Null
 Start-ScheduledTask -TaskName $service -TaskPath '\' -ErrorAction Stop
 $healthy=$false
 for($i=0;$i -lt 100;$i++){
  if(MockServiceHealthy 'ORIGINAL' $service){$healthy=$true;break}
  Start-Sleep -Milliseconds 100
 }
 if(-not $healthy){throw 'NO-GO: original mock service did not return healthy'}
 $s=Read-State
 Save-State $s 'ROLLED_BACK_VERIFIED'
 [IO.File]::WriteAllText((Join-Path $CaseDir 'watchdog.result'),'ROLLED_BACK_VERIFIED',[Text.UTF8Encoding]::new($false))
}
try {
 Assert-Lab
 $lock=Take-Lock
 try{
  $s=Read-State
  VerifyState $s
  if($s.phase -ceq 'COMMITTED_VERIFIED'){
   if(-not (MockServiceHealthy 'CANDIDATE' ([string]$s.service_task))){throw 'NO-GO: committed service unhealthy'}
   [IO.File]::WriteAllText((Join-Path $CaseDir 'watchdog.result'),'COMMIT_PRESERVED',[Text.UTF8Encoding]::new($false))
  }elseif($s.phase -in @('ARMED','QUIESCING','PATCHING','STARTING','VERIFYING','ROLLBACK_IN_PROGRESS')){
   Recover $s
  }elseif($s.phase -ceq 'PREPARED'){
   [IO.File]::WriteAllText((Join-Path $CaseDir 'watchdog.result'),'PREPARED_UNTOUCHED',[Text.UTF8Encoding]::new($false))
  }else{throw 'NO-GO: unknown transaction state'}
 }finally{$lock.Dispose()}
 $ok=$true
}catch{
 try{[IO.File]::WriteAllText((Join-Path $CaseDir 'watchdog.failure'),'NO-GO_INTEGRATED_RECOVERY',[Text.UTF8Encoding]::new($false))}catch{}
 Write-Host 'NO-GO INTEGRATED RECOVERER: protected LAB check failed; no production action.' -ForegroundColor Red
}
if(-not $ok){exit 1}
exit 0
