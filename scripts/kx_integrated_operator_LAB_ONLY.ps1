# K-X integrated HTTPS transaction EXECUTOR + fake SYSTEM scheduled service -- LAB ONLY.
# Paired with kx_integrated_recoverer_LAB_ONLY.ps1; never writes real Caddy/tasks/443.
# Windows PowerShell 5.1. Modes FixtureCI / EC2CopyLab, roles Driver / Worker / Service.
param([Parameter(Mandatory=$true)][ValidateSet('FixtureCI','EC2CopyLab')][string]$Mode,
      [ValidateSet('Driver','Worker','Service')][string]$Role='Driver',
      [string]$CaseDir='')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$success=$false
$labRoot=$null
$known=@('CRASH_AFTER_SECOND','COMMIT_OK')
$expectedLauncher='873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
$liveCaddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$liveLauncher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
function Check([bool]$passed,[string]$label){
 if(-not $passed){throw ('NO-GO INTEGRATED LAB: '+$label)}
 if($Role -ceq 'Driver'){Write-Host ('OK: '+$label) -ForegroundColor Green}
}
function Hash([string]$p){return (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash}
function Confirm([string]$p,[string]$h,[string]$label){
 Check (Test-Path -LiteralPath $p -PathType Leaf) ($label+' exists')
 Check ((Hash $p) -ceq $h) ($label+' SHA256')
 Check (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ($label+' no link')
}
function ValidateLab {
 Check (-not [string]::IsNullOrWhiteSpace($CaseDir)) 'CaseDir supplied'
 $full=[IO.Path]::GetFullPath($CaseDir).TrimEnd('\')
 $root=[IO.Path]::GetDirectoryName($full)
 Check ($known -ccontains [IO.Path]::GetFileName($full)) 'Known LAB case'
 if($Mode -ceq 'EC2CopyLab'){
  Check ([string]::Equals($root,'C:\ProgramData\VehiculoIoT-KX-Installer\kx_integrated_cutover_lab_v1',[StringComparison]::OrdinalIgnoreCase)) 'EC2 dedicated LAB root'
 }else{
  Check ([IO.Path]::GetFileName($root) -match '^KX-Integrated-CI-[a-f0-9]{32}$') 'CI unique LAB root'
 }
 foreach($p in @($root,$full)){
  Check (Test-Path -LiteralPath $p -PathType Container) 'LAB folder exists'
  Check (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'LAB no reparse'
  Check ((Get-Acl -LiteralPath $p).AreAccessRulesProtected) 'LAB ACL protected'
 }
 $own=[IO.Path]::GetFullPath($PSCommandPath)
 Check ([string]::Equals($own,(Join-Path $root 'kx_integrated_operator.ps1'),[StringComparison]::OrdinalIgnoreCase)) 'Runs private LAB copy'
 $script:labRoot=$root
 $script:CaseDir=$full
}
function ReadState {return (Get-Content -LiteralPath (Join-Path $CaseDir 'txn.json') -Raw|ConvertFrom-Json)}
function SaveState($s,[string]$next){
 $s.phase=$next
 $s.updated_utc=[DateTime]::UtcNow.ToString('o')
 $p=Join-Path $CaseDir 'txn.json'
 $temp=$p+'.in'
 Check (-not (Test-Path -LiteralPath $temp)) 'State temp unused'
 $s|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $temp -Encoding UTF8
 [IO.File]::Replace($temp,$p,[NullString]::Value)
}
function AcquireLock{
 $p=Join-Path $CaseDir 'exclusive.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: cross-session file lock timeout'
}
function VerifyInputs($s){
 Check ($s.schema -eq 1 -and $s.mode -ceq 'isolated_cutover_integrated_lab') 'Transaction schema'
 Check ($s.transaction_id -match '^[a-f0-9]{32}$') 'Transaction identifier'
 foreach($name in @('old_caddy','old_launcher','new_caddy','new_launcher')){
  Confirm (Join-Path $CaseDir $name) ([string]$s.hashes.$name) ('input '+$name)
 }
 Confirm (Join-Path $labRoot 'kx_integrated_operator.ps1') ([string]$s.hashes.operator_script) 'Operator code'
 Confirm (Join-Path $labRoot 'kx_integrated_recoverer.ps1') ([string]$s.hashes.recover_script) 'Recoverer code'
}
function MockHealth([string]$expected,$s){
 $p=Join-Path $CaseDir 'health.json'
 try{
  $task=Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -ErrorAction Stop
  if($task.State -ne 'Running' -or -not (Test-Path -LiteralPath $p -PathType Leaf)){return $false}
  $a=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json
  if($a.mode -cne $expected){return $false}
  $stamp=[DateTime]::Parse([string]$a.utc,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind)
  if(([DateTime]::UtcNow-$stamp.ToUniversalTime()).TotalSeconds -gt 4){return $false}
  $pr=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$a.pid) -ErrorAction SilentlyContinue
  if($null -eq $pr -or $pr.CreationDate.ToUniversalTime().Ticks.ToString() -cne [string]$a.creation_ticks){return $false}
  return (Invoke-CimMethod -InputObject $pr -MethodName GetOwnerSid).Sid -ceq 'S-1-5-18'
 }catch{return $false}
}
function AwaitMock([string]$state,$s,[int]$maxSeconds){
 for($i=0;$i -lt ($maxSeconds*5);$i++){
  if(MockHealth $state $s){return $true}
  Start-Sleep -Milliseconds 200
 }
 return $false
}
function AwaitMarker([string]$file,[int]$maxSeconds){
 for($i=0;$i -lt $maxSeconds*5;$i++){
  if(Test-Path -LiteralPath (Join-Path $CaseDir $file) -PathType Leaf){return $true}
  Start-Sleep -Milliseconds 200
 }
 return $false
}
function AssertLabTask([string]$name,[string]$prefix,[string]$role){
 Check ($name -match ('^VehiculoIoT-KX-INT-LAB-'+$prefix+'-[a-f0-9]{32}$')) 'Exact dedicated task name'
 $t=Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
 Check ($t.Principal.UserId -match '^(SYSTEM|S-1-5-18|NT AUTHORITY\\SYSTEM)$') 'Lab task SYSTEM'
 Check (@($t.Actions).Count -eq 1) 'Single lab task action'
 Check (([string]$t.Actions[0].Arguments).Contains((Join-Path $labRoot (('kx_integrated_{0}.ps1' -f $role))))) 'Lab task script path'
 return $t
}
function StopFake($s){
 $name=[string]$s.service_task
 $null=AssertLabTask $name 'Service' 'operator'
 Disable-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop|Out-Null
 if((Get-ScheduledTask -TaskPath '\' -TaskName $name).State -eq 'Running'){
  Stop-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
 }
 for($i=0;$i -lt 60;$i++){
  if((Get-ScheduledTask -TaskPath '\' -TaskName $name).State -ne 'Running'){return}
  Start-Sleep -Milliseconds 100
 }
 throw 'NO-GO: fake SYSTEM service did not stop'
}
function StartFake($s){
 $name=[string]$s.service_task
 $null=AssertLabTask $name 'Service' 'operator'
 Enable-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop|Out-Null
 Start-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
}
function Swap([string]$input,[string]$dest,[string]$backup,[string]$h){
 $prefix=$CaseDir.TrimEnd('\')+'\'
 foreach($p in @($input,$dest,$backup)){
  Check ([IO.Path]::GetFullPath($p).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) 'Swap confined to LAB'
 }
 Confirm $input $h 'Swap source'
 Check (Test-Path -LiteralPath $dest -PathType Leaf) 'Mirror destination exists'
 Check (-not(Test-Path -LiteralPath $backup)) 'Swap backup available'
 $incoming=$dest+'.incoming'
 Check (-not(Test-Path -LiteralPath $incoming)) 'Incoming available'
 [IO.File]::Copy($input,$incoming,$false)
 Confirm $incoming $h 'Incoming verified'
 [IO.File]::Replace($incoming,$dest,$backup)
 Confirm $dest $h 'Swapped mirror'
}
function MockService{
 ValidateLab
 $who=[Security.Principal.WindowsIdentity]::GetCurrent()
 Check ($who.User.Value -ceq 'S-1-5-18') 'Only SYSTEM mock service'
 $s=ReadState
 VerifyInputs $s
 $pr=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$PID) -ErrorAction Stop
 while($true){
  $hC=Hash (Join-Path $CaseDir 'Caddyfile.MIRROR')
  $hL=Hash (Join-Path $CaseDir 'run_caddy.MIRROR.ps1')
  $status='INVALID'
  if($hC -ceq [string]$s.hashes.old_caddy -and $hL -ceq [string]$s.hashes.old_launcher){$status='ORIGINAL'}
  if($hC -ceq [string]$s.hashes.new_caddy -and $hL -ceq [string]$s.hashes.new_launcher){$status='CANDIDATE'}
  $record=[ordered]@{mode=$status;pid=[int]$PID;creation_ticks=$pr.CreationDate.ToUniversalTime().Ticks.ToString();utc=[DateTime]::UtcNow.ToString('o')}
  $temp=Join-Path $CaseDir ('health.'+$PID+'.incoming')
  $record|ConvertTo-Json|Set-Content -LiteralPath $temp -Encoding UTF8
  $out=Join-Path $CaseDir 'health.json'
  if(Test-Path -LiteralPath $out -PathType Leaf){[IO.File]::Replace($temp,$out,[NullString]::Value)}
  else{[IO.File]::Move($temp,$out)}
  Start-Sleep -Milliseconds 350
 }
}
function Worker{
 ValidateLab
 $s=ReadState
 VerifyInputs $s
 Check ($s.phase -ceq 'PREPARED') 'Worker transaction prepared'
 $watchName=[string]$s.watchdog_task
 $watchScript=Join-Path $labRoot 'kx_integrated_recoverer.ps1'
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$watchScript+'" -Mode '+$Mode+' -CaseDir "'+$CaseDir+'"'
 $action=New-ScheduledTaskAction -Execute $exe -Argument $args
 $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -StartWhenAvailable
 $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(55)
 Check ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $watchName -ErrorAction SilentlyContinue)) 'No stale watchdog'
 Register-ScheduledTask -TaskPath '\' -TaskName $watchName -Action $action -Principal $principal -Settings $settings -Trigger $trigger -ErrorAction Stop|Out-Null
 $null=AssertLabTask $watchName 'Recovery' 'recoverer'
 $lock=AcquireLock
 try{
  $s=ReadState
  SaveState $s 'ARMED'
  $s=ReadState
  StopFake $s
  SaveState $s 'QUIESCING'
  $s=ReadState
  Swap (Join-Path $CaseDir 'new_caddy') (Join-Path $CaseDir 'Caddyfile.MIRROR') (Join-Path $CaseDir 'forward_caddy.bak') ([string]$s.hashes.new_caddy)
  SaveState $s 'PATCHING'
  $s=ReadState
  Swap (Join-Path $CaseDir 'new_launcher') (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') (Join-Path $CaseDir 'forward_launcher.bak') ([string]$s.hashes.new_launcher)
  [IO.File]::WriteAllText((Join-Path $CaseDir 'worker.stage'),'BOTH_PATCHED',[Text.UTF8Encoding]::new($false))
  if([IO.Path]::GetFileName($CaseDir) -ceq 'CRASH_AFTER_SECOND'){
   while($true){Start-Sleep -Milliseconds 200}
  }
  SaveState $s 'STARTING'
  $s=ReadState
  StartFake $s
  Check (AwaitMock 'CANDIDATE' $s 12) 'Candidate mock service healthy'
  SaveState $s 'VERIFYING'
  $s=ReadState
  Check (AwaitMock 'CANDIDATE' $s 5) 'Candidate mock health rechecked'
  SaveState $s 'COMMITTED_VERIFIED'
  [IO.File]::WriteAllText((Join-Path $CaseDir 'worker.success'),'COMMITTED_VERIFIED',[Text.UTF8Encoding]::new($false))
 }finally{$lock.Dispose()}
}
function InitPrivateDir([string]$p){
 Check (-not(Test-Path -LiteralPath $p)) 'New LAB directory, no overwrite'
 [IO.Directory]::CreateDirectory($p)|Out-Null
 & icacls.exe $p /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) 'ACL inheritance disabled'
 & icacls.exe $p /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
 Check ($LASTEXITCODE -eq 0) 'ACL SYSTEM/Admin'
 Check ((Get-Acl -LiteralPath $p).AreAccessRulesProtected) 'Private ACL'
}
function RegisterFake($s) {
 $name=[string]$s.service_task
 $scriptPath=Join-Path $labRoot 'kx_integrated_operator.ps1'
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'" -Mode '+$Mode+' -Role Service -CaseDir "'+$CaseDir+'"'
 $action=New-ScheduledTaskAction -Execute $exe -Argument $args
 $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
 Check ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue)) 'Fake SYSTEM service task unique'
 Register-ScheduledTask -TaskPath '\' -TaskName $name -Action $action -Principal $principal -Settings $settings -ErrorAction Stop|Out-Null
 $null=AssertLabTask $name 'Service' 'operator'
 $xml=[xml](Export-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop)
 $ns=New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $n=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Count',$ns)
 Check ($null -ne $n -and [int]$n.InnerText -eq 999) 'Fake service retry count matches production'
 $n=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Interval',$ns)
 Check ($null -ne $n -and $n.InnerText -ceq 'PT1M') 'Fake service retry interval matches production'
}
function WorkerMatches([int]$id,[string]$stamp){
 $p=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$id) -ErrorAction SilentlyContinue
 return ($null -ne $p -and $p.CreationDate.ToUniversalTime().Ticks.ToString() -ceq $stamp)
}
function RunIntegratedCase([string]$name,[string]$inputs){
 $script:CaseDir=Join-Path $labRoot $name
 InitPrivateDir $CaseDir
 foreach($f in @('old_caddy','old_launcher','new_caddy','new_launcher')){
  [IO.File]::Copy((Join-Path $inputs $f),(Join-Path $CaseDir $f),$false)
 }
 [IO.File]::Copy((Join-Path $CaseDir 'old_caddy'),(Join-Path $CaseDir 'Caddyfile.MIRROR'),$false)
 [IO.File]::Copy((Join-Path $CaseDir 'old_launcher'),(Join-Path $CaseDir 'run_caddy.MIRROR.ps1'),$false)
 [IO.File]::WriteAllText((Join-Path $CaseDir 'exclusive.lock'),'K-X-LAB',[Text.UTF8Encoding]::new($false))
 $id=[guid]::NewGuid().ToString('N')
 $s=[ordered]@{
  schema=1;mode='isolated_cutover_integrated_lab';transaction_id=$id;phase='PREPARED'
  updated_utc=[DateTime]::UtcNow.ToString('o')
  service_task='VehiculoIoT-KX-INT-LAB-Service-'+$id
  watchdog_task='VehiculoIoT-KX-INT-LAB-Recovery-'+$id
  hashes=[ordered]@{
   old_caddy=Hash (Join-Path $CaseDir 'old_caddy')
   old_launcher=Hash (Join-Path $CaseDir 'old_launcher')
   new_caddy=Hash (Join-Path $CaseDir 'new_caddy')
   new_launcher=Hash (Join-Path $CaseDir 'new_launcher')
   operator_script=Hash (Join-Path $labRoot 'kx_integrated_operator.ps1')
   recover_script=Hash (Join-Path $labRoot 'kx_integrated_recoverer.ps1')
  }
 }
 $s|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $CaseDir 'txn.json') -Encoding UTF8
 $worker=$null;$registered=$false;$watchRegistered=$false;$cleanupOk=$true
 try{
  RegisterFake $s
  $registered=$true
  StartFake $s
  Check (AwaitMock 'ORIGINAL' $s 15) 'Initial fake scheduled service healthy'
  $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $scriptPath=Join-Path $labRoot 'kx_integrated_operator.ps1'
  $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'" -Mode '+$Mode+' -Role Worker -CaseDir "'+$CaseDir+'"'
  $worker=Start-Process -FilePath $exe -ArgumentList $args -WindowStyle Hidden -PassThru -ErrorAction Stop
  $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$worker.Id) -ErrorAction Stop
  $birth=$proc.CreationDate.ToUniversalTime().Ticks.ToString()
  if(-not (AwaitMarker 'worker.stage' 22)){
   if($Mode -ceq 'FixtureCI'){
    $diag=Join-Path $CaseDir 'worker.ci-error.txt'
    if(Test-Path -LiteralPath $diag -PathType Leaf){Write-Host ('CI WORKER DIAG: '+[IO.File]::ReadAllText($diag))}
   }
   throw 'NO-GO: integrated worker stage not reached'
  }
  Check $true 'Integrated worker reached second replacement'
  Check ($null -ne (Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -ErrorAction SilentlyContinue)) 'Independent watchdog registered before failure'
  $watchRegistered=$true
  if($name -ceq 'CRASH_AFTER_SECOND'){
   Check (WorkerMatches ([int]$worker.Id) $birth) 'Exact worker still alive before crash'
   $worker.Kill()
   Check ($worker.WaitForExit(5000)) 'Only owned lab worker terminated'
  }else{
   Check ($worker.WaitForExit(18000)) 'Integrated worker completed normally'
   Check ($worker.ExitCode -eq 0) 'Integrated worker exited 0'
   Check (AwaitMarker 'worker.success' 3) 'Commit state written'
  }
  Check (AwaitMarker 'watchdog.result' 125) 'Pre-armed SYSTEM watchdog fired automatically'
  $final=[IO.File]::ReadAllText((Join-Path $CaseDir 'watchdog.result'))
  if($name -ceq 'CRASH_AFTER_SECOND'){
   Check ($final -ceq 'ROLLED_BACK_VERIFIED') 'Integrated recovery restored fake service'
   Confirm (Join-Path $CaseDir 'Caddyfile.MIRROR') ([string]$s.hashes.old_caddy) 'Final original Caddy mirror'
   Confirm (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') ([string]$s.hashes.old_launcher) 'Final original launcher mirror'
   Check (AwaitMock 'ORIGINAL' $s 6) 'Fake service returned with original config'
  }else{
   Check ($final -ceq 'COMMIT_PRESERVED') 'Healthy commit preserved without rollback'
   Confirm (Join-Path $CaseDir 'Caddyfile.MIRROR') ([string]$s.hashes.new_caddy) 'Final candidate Caddy mirror'
   Confirm (Join-Path $CaseDir 'run_caddy.MIRROR.ps1') ([string]$s.hashes.new_launcher) 'Final candidate launcher mirror'
   Check (AwaitMock 'CANDIDATE' $s 6) 'Healthy candidate mock service'
  }
  $end=ReadState
  Check ((($name -ceq 'CRASH_AFTER_SECOND') -and $end.phase -ceq 'ROLLED_BACK_VERIFIED') -or
         (($name -ceq 'COMMIT_OK') -and $end.phase -ceq 'COMMITTED_VERIFIED')) 'Durable final transaction state'
  for($i=0;$i -lt 60;$i++){
   if((Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task)).State -ne 'Running'){break}
   Start-Sleep -Milliseconds 100
  }
  Check ((Get-ScheduledTaskInfo -TaskPath '\' -TaskName ([string]$s.watchdog_task)).LastTaskResult -eq 0) 'Watchdog task ended successfully'
  Write-Host ('OK: integrated '+$name+' verified, file and mock SYSTEM task recovery') -ForegroundColor Green
 }finally{
  if($null -ne $worker){
   try{if(-not $worker.HasExited){$worker.Kill();$null=$worker.WaitForExit(5000)}}catch{$cleanupOk=$false}
   $worker.Dispose()
  }
  if($watchRegistered -or $null -ne (Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -ErrorAction SilentlyContinue)){
   try{
    $t=Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -ErrorAction Stop
    if($t.State -eq 'Running'){Stop-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -ErrorAction Stop}
    Unregister-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -Confirm:$false -ErrorAction Stop
   }catch{$cleanupOk=$false;if($Mode -ceq 'FixtureCI'){Write-Host ('CI watchdog cleanup: '+$_.Exception.Message)}}
  }
  if($registered -or $null -ne (Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -ErrorAction SilentlyContinue)){
   try{
    $t=Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -ErrorAction Stop
    $t|Disable-ScheduledTask -ErrorAction Stop|Out-Null
    if((Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task)).State -eq 'Running'){
     Stop-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -ErrorAction Stop
    }
    Unregister-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -Confirm:$false -ErrorAction Stop
   }catch{$cleanupOk=$false;if($Mode -ceq 'FixtureCI'){Write-Host ('CI service cleanup: '+$_.Exception.Message)}}
  }
  if($null -ne (Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.service_task) -ErrorAction SilentlyContinue) -or
     $null -ne (Get-ScheduledTask -TaskPath '\' -TaskName ([string]$s.watchdog_task) -ErrorAction SilentlyContinue)){
   $cleanupOk=$false
  }
  if(-not $cleanupOk){throw 'NO-GO: lab scheduled task cleanup incomplete'}
 }
}
function Driver {
 $p=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Elevated admin'
 $sources=$null;$man=$null
 if($Mode -ceq 'FixtureCI'){
  Check ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'CI Windows only'
  $script:labRoot=Join-Path $env:TEMP ('KX-Integrated-CI-'+[guid]::NewGuid().ToString('N'))
 }else{
  $script:labRoot='C:\ProgramData\VehiculoIoT-KX-Installer\kx_integrated_cutover_lab_v1'
  $kit='C:\ProgramData\VehiculoIoT-KX-Installer'
  Check ((Get-Acl -LiteralPath $kit).AreAccessRulesProtected) 'Installer private ACL'
  $man=Get-Content -LiteralPath 'C:\ProgramData\VehiculoIoT-KX-State\service\install.json' -Raw |ConvertFrom-Json
  Check ($man.mode -ceq 'loopback_only_not_public' -and $man.caddy_changed -eq $false -and $man.physical_control_enabled -eq $false) 'K-V private and physical OFF'
  $release=Join-Path $kit 'kx_https_public_release_v1_offline'
  $stage=Join-Path $release 'launcher_staging_v1'
  $prep=Get-Content -LiteralPath (Join-Path $release 'preparation.json') -Raw|ConvertFrom-Json
  $staged=Get-Content -LiteralPath (Join-Path $stage 'launcher_stage_report.json') -Raw|ConvertFrom-Json
  $sources=@{
   old_caddy=Join-Path $kit 'kx_caddy_release_preflight\Caddyfile.original.copy'
   old_launcher=Join-Path $stage 'run_caddy.original.backup.ps1'
   new_caddy=Join-Path $release 'Caddyfile.kx.ready.NOT_ACTIVE'
   new_launcher=Join-Path $stage 'run_caddy.kx.pending.ps1'
  }
  Confirm $sources.old_caddy ([string]$man.original_caddy_sha256) 'Original Caddy backup'
  Confirm $sources.old_launcher $expectedLauncher 'Original launcher backup'
  Confirm $sources.new_caddy ([string]$prep.candidate_sha256) 'Caddy candidate'
  Confirm $sources.new_launcher ([string]$staged.launcher_candidate_sha256) 'Launcher candidate'
  Confirm $liveCaddy ([string]$man.original_caddy_sha256) 'Production Caddy before lab'
  Confirm $liveLauncher $expectedLauncher 'Production launcher before lab'
  foreach($n in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
   Check ((Get-ScheduledTask -TaskName $n -TaskPath '\').State -eq 'Running') ($n+' Running')
  }
 }
 InitPrivateDir $labRoot
 $srcRoot=[IO.Path]::GetDirectoryName($PSCommandPath)
 $recoverSource=Join-Path $srcRoot 'kx_integrated_recoverer_LAB_ONLY.ps1'
 Check (Test-Path -LiteralPath $recoverSource -PathType Leaf) 'Paired recoverer available'
 $operator=Join-Path $labRoot 'kx_integrated_operator.ps1'
 $recoverer=Join-Path $labRoot 'kx_integrated_recoverer.ps1'
 [IO.File]::Copy($PSCommandPath,$operator,$false)
 [IO.File]::Copy($recoverSource,$recoverer,$false)
 Check ((Hash $operator) -ceq (Hash $PSCommandPath)) 'Operator code staged unchanged'
 Check ((Hash $recoverer) -ceq (Hash $recoverSource)) 'Recoverer code staged unchanged'
 $inputDir=Join-Path $labRoot 'inputs'
 [IO.Directory]::CreateDirectory($inputDir)|Out-Null
 if($Mode -ceq 'FixtureCI'){
  [IO.File]::WriteAllText((Join-Path $inputDir 'old_caddy'),'FAKE ORIGINAL CADDY',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputDir 'old_launcher'),'FAKE ORIGINAL LAUNCHER',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputDir 'new_caddy'),'FAKE CADDY CANDIDATE',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $inputDir 'new_launcher'),'FAKE LAUNCHER CANDIDATE',[Text.UTF8Encoding]::new($false))
 }else{
  foreach($n in @('old_caddy','old_launcher','new_caddy','new_launcher')){
   [IO.File]::Copy([string]$sources[$n],(Join-Path $inputDir $n),$false)
  }
 }
 foreach($name in $known){
  Write-Host ('=== INTEGRATED LAB: '+$name+' ===') -ForegroundColor Cyan
  RunIntegratedCase $name $inputDir
 }
 if($Mode -ceq 'EC2CopyLab'){
  Confirm $liveCaddy ([string]$man.original_caddy_sha256) 'Production Caddy untouched'
  Confirm $liveLauncher $expectedLauncher 'Production launcher untouched'
  foreach($n in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
   Check ((Get-ScheduledTask -TaskName $n -TaskPath '\').State -eq 'Running') ($n+' still Running')
  }
 }
 $result=[ordered]@{
  mode='integrated_end_to_end_lab_only'
  timestamp_utc=[DateTime]::UtcNow.ToString('o')
  scenarios=@('CRASH_AFTER_SECOND','COMMIT_OK')
  independent_system_task_triggered=$true
  cross_session_lock_exercised=$true
  service_fictitious_task_tested=$true
  service_production_tested=$false
  public_https_modified=$false
  production_rollback_tested=$false
  physical_control_enabled=$false
 }
 $result|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $labRoot 'integrated_lab_report.json') -Encoding UTF8
 Write-Host '=== RESULTADO: TRANSACCION INTEGRADA CON SERVICIO FICTICIO APROBADA ===' -ForegroundColor Green
 Write-Host 'CRASH: RESTAURA 2 ARCHIVOS Y REARRANCA SERVICIO FICTICIO ORIGINAL'
 Write-Host 'COMMIT: CONSERVA CANDIDATO SANO SIN ROLLBACK INDEBIDO'
 Write-Host 'WATCHDOG SYSTEM AUTO; LOCK NTFS; TAREAS LAB ELIMINADAS'
 Write-Host 'CADDY REAL 443 Y TAREAS ORIGINALES INTACTAS'
 Write-Host 'NO AUTORIZA PUBLICACION NI DEMUESTRA RECUPERACION HTTPS REAL'
}
try {
 if($Role -ceq 'Driver'){Driver}
 elseif($Role -ceq 'Worker'){Worker}
 else{MockService}
 $success=$true
}catch{
 Write-Host ('=== NO-GO TRANSACCION INTEGRADA / '+$Role+' ===') -ForegroundColor Red
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 if($Mode -ceq 'FixtureCI'){
  if($Role -ceq 'Worker' -and -not [string]::IsNullOrWhiteSpace($CaseDir)){
   try{[IO.File]::WriteAllText((Join-Path $CaseDir 'worker.ci-error.txt'),($_.Exception.GetType().Name+': '+$_.Exception.Message))}catch{}
  }
  Write-Host ('CI DETALLE: '+$_.Exception.Message) -ForegroundColor Yellow
 }
}
if(-not $success){exit 1}
exit 0
