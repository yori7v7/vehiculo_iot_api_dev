# K-X real HTTPS Caddy transaction candidate. Windows PowerShell 5.1.
# RELEASE CANDIDATE. Requires -Action Cutover -AuthorizeRealCutover and a verified SYSTEM watchdog.
# Do not modify this gate without separate system-specific acceptance and authorized window.
param(
 [ValidateSet('Review','Cutover')][string]$Action='Review',
 [switch]$AuthorizeRealCutover,
 [string]$Bundle='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v4_RELEASE_READY'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:EnableProductionCutover=$true
$script:Step='BEGIN'
$script:Success=$false
$script:RecoveryArmed=$false
$script:LockHandle=$null
$script:BundleRoot='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v4_RELEASE_READY'
$script:Task='VehiculoIoT-Caddy'
$script:Caddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$script:Launcher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$script:RunRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
$script:PublicBase='https://100-30-4-62.nip.io'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$script:KxState='C:\ProgramData\VehiculoIoT-KX-State\service'
function KX-Assert([bool]$condition,[string]$label) {
 if(-not $condition){throw ('NO-GO: '+$label)}
}
function KX-Hash([string]$p) {return (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash}
function KX-File([string]$p,[string]$hash) {
 KX-Assert (Test-Path -LiteralPath $p -PathType Leaf) 'Expected file absent'
 KX-Assert (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'File redirected'
 KX-Assert ((KX-Hash $p) -ceq $hash) 'Unexpected file hash'
}
function KX-Package {
 $script:Step='PACKAGE'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Known package path'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($PSScriptRoot),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Controller lives inside the private bundle'
 KX-Assert ((Get-Acl -LiteralPath $script:BundleRoot).AreAccessRulesProtected) 'Bundle must have protected ACL'
 $pkg=Get-Content -LiteralPath (Join-Path $script:BundleRoot 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Assert ($pkg.schema_version -eq 1 -and $pkg.mode -ceq 'prod_cutover_bundle_v4_release_ready') 'Known prepared bundle'
 KX-Assert ($pkg.release_enabled -eq $true -and $pkg.recovery_enabled -eq $true) 'Both release components explicitly approved in manifest'
 $pairs=@{
  caddy_original='Caddyfile.original'
  launcher_original='run_caddy.original.ps1'
  caddy_candidate='Caddyfile.candidate.NOT_ACTIVE'
  launcher_candidate='run_caddy.candidate.NOT_ACTIVE.ps1'
  controller='kx_prod_cutover_controller_v4_RELEASE.ps1'
  recoverer='kx_prod_recoverer_v4_RELEASE.ps1'
  task_xml='VehiculoIoT-Caddy.original.task.xml'
 }
 foreach($k in $pairs.Keys){KX-File (Join-Path $script:BundleRoot $pairs[$k]) ([string]$pkg.hashes.$k)}
 return $pkg
}
function KX-CurrentTask {
 $script:Step='TASK'
 $t=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 $actions=@($t.Actions)
 KX-Assert ($actions.Count -eq 1 -and
   ([string]$actions[0].Arguments).Contains($script:Launcher)) 'Original Caddy task action'
 KX-Assert (@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$t.Principal.UserId) 'SYSTEM task principal'
 [xml]$xml=Export-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 $ns=New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $count=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Count',$ns)
 $interval=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Interval',$ns)
 KX-Assert ($null -ne $count -and $null -ne $interval) 'Retry config present'
 KX-Assert ([int]$count.InnerText -eq 999 -and $interval.InnerText -ceq 'PT1M') 'Original 999/PT1M task retry policy'
 return $t
}
function KX-Listener([int]$port) {return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)}
function KX-MatchRecord($rec) {
 if($null -eq $rec){return $null}
 $p=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$rec.process_id) -ErrorAction SilentlyContinue
 if($null -eq $p){return $null}
 KX-Assert ($p.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$rec.creation_ticks) 'Tracked process creation ticks'
 KX-Assert ([string]::Equals([string]$p.ExecutablePath,[string]$rec.executable_path,[StringComparison]::OrdinalIgnoreCase)) 'Tracked process executable'
 KX-Assert ((Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid).Sid -ceq 'S-1-5-18') 'Tracked process SYSTEM owner'
 return $p
}
function KX-RequireBaseline($pkg) {
 $script:Step='LIVE_BASELINE'
 KX-File $script:Caddy ([string]$pkg.hashes.caddy_original)
 KX-File $script:Launcher ([string]$pkg.hashes.launcher_original)
 foreach($name in @('VehiculoIoT-Caddy','VehiculoIoT-FastAPI','VehiculoIoT-Admission-Virtual')){
  KX-Assert ((Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop).State -eq 'Running') 'Production task not running'
 }
 $null=KX-CurrentTask
 $manifest=Get-Content -LiteralPath (Join-Path $script:KxState 'install.json') -Raw|ConvertFrom-Json
 KX-Assert ($manifest.mode -ceq 'loopback_only_not_public' -and
  $manifest.caddy_changed -eq $false -and $manifest.physical_control_enabled -eq $false) 'Sidecar still private and physical OFF'
 $r=Get-Content -LiteralPath $script:RunRecord -Raw|ConvertFrom-Json
 $super=KX-MatchRecord $r.supervisor
 $child=KX-MatchRecord $r.child
 KX-Assert ($null -ne $super -and $null -ne $child) 'Caddy supervisor and child'
 KX-Assert ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Supervisor parent/child link'
 KX-Assert ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Caddy child exe'
 $l=@(KX-Listener 443)
 $owners=@($l|Select-Object -ExpandProperty OwningProcess -Unique)
 KX-Assert ($owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) '443 belongs to tracked child'
 $kv=@(KX-Listener 9444)
 KX-Assert ($kv.Count -eq 1 -and $kv[0].LocalAddress -ceq '127.0.0.1') 'K-V loopback'
 $legacy=@(KX-Listener 8000)
 KX-Assert ($legacy.Count -gt 0 -and @($legacy|Where-Object {$_.LocalAddress -notin @('127.0.0.1','::1')}).Count -eq 0) 'Legacy loopback'
 KX-Assert (@(KX-Listener 9481).Count -eq 0) 'No leftover test listener'
 KX-Assert ((Get-ScheduledTask -TaskPath '\' -TaskName 'VehiculoIoT-Caddy').State -eq 'Running') 'Caddy task still running'
}
function KX-HttpStatus([string]$uri,[string]$origin,[string]$key,[int]$expected,[bool]$checkBody=$false) {
 Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
 $handler=[Net.Http.HttpClientHandler]::new()
 $handler.UseProxy=$false
 $handler.UseCookies=$false
 $handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler)
 $client.Timeout=[TimeSpan]::FromSeconds(8)
 $req=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,[Uri]$uri)
 $resp=$null
 try{
  if(-not [string]::IsNullOrEmpty($origin)){
   KX-Assert ($req.Headers.TryAddWithoutValidation('Origin',$origin)) 'Origin header available'
  }
  if(-not [string]::IsNullOrEmpty($key)){
   KX-Assert ($req.Headers.TryAddWithoutValidation('X-API-Key',$key)) 'Admin authentication header available'
  }
  $resp=$client.SendAsync($req).GetAwaiter().GetResult()
  KX-Assert ([int]$resp.StatusCode -eq $expected) 'Expected HTTPS GET status'
  if($checkBody){
   KX-Assert ($null -ne $resp.Headers.CacheControl -and $resp.Headers.CacheControl.NoStore) 'K-V no-store'
   $data=$resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()|ConvertFrom-Json
   KX-Assert ($data.simulado -eq $true -and $data.control_fisico -eq $false -and $data.canDrive -eq $false) 'K-V remains virtual'
   KX-Assert ($data.turno_activo -eq $false -and @($data.solicitudes).Count -eq 0) 'No active virtual tickets'
  }
 }finally{
  if($null -ne $resp){$resp.Dispose()}
  $req.Dispose()
  $client.Dispose()
  $handler.Dispose()
 }
}
function KX-HealthOriginal {
 $script:Step='ORIGINAL_PUBLIC_GET'
 KX-HttpStatus ($script:PublicBase+'/') '' '' 200
 KX-HttpStatus ($script:PublicBase+'/openapi.json') '' '' 200
}
function KX-HealthCandidate($pkg){
 $script:Step='CANDIDATE_PUBLIC_GET'
 $healthy=$false
 for($attempt=0;$attempt -lt 36;$attempt++){
  try{
   $task=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
   if($task.State -eq 'Running' -and @(KX-Listener 443).Count -ge 1){
    KX-HealthOriginal
    $healthy=$true;break
   }
  }catch{}
  Start-Sleep -Milliseconds 500
 }
 KX-Assert $healthy 'Caddy candidate HTTPS legacy not healthy'
 $secretData=$null
 try{
  $secretData=Get-Content -LiteralPath (Join-Path $script:KxState 'config.json') -Raw -Encoding UTF8|ConvertFrom-Json
  KX-Assert ($secretData.mode -ceq 'virtual_loopback_only' -and
   [string]$secretData.admin_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
   [string]$secretData.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
   $secretData.proxy_proof -cne $secretData.admin_proof) 'K-V authentication source private'
  $admin=[string]$secretData.admin_proof
  $uri=$script:PublicBase+'/admin/vehiculos/1/control-publico/solicitudes'
  KX-HttpStatus $uri 'https://yori7v7.github.io' $admin 200 $true
  KX-HttpStatus $uri 'https://yori7v7.github.io' '' 401
  KX-HttpStatus $uri 'https://yori7v7.github.io' 'KX_INVALID_ADMIN_PROOF' 403
  KX-HttpStatus $uri 'https://example.invalid' $admin 403
 }finally{$admin=$null;$secretData=$null}
  # HTTP alone is insufficient: verify exact live candidate and SYSTEM Caddy owner.
  KX-Assert ((KX-Hash $script:Caddy) -ceq [string]$pkg.hashes.caddy_candidate) 'Caddy candidate SHA256 remains exact'
  KX-Assert ((KX-Hash $script:Launcher) -ceq [string]$pkg.hashes.launcher_candidate) 'Launcher candidate SHA256 remains exact'
  $record=Get-Content -LiteralPath $script:RunRecord -Raw -ErrorAction Stop|ConvertFrom-Json
  $super=KX-MatchRecord $record.supervisor
  $child=KX-MatchRecord $record.child
  KX-Assert ($null -ne $super -and $null -ne $child) 'Candidate SYSTEM supervisor and Caddy child'
  KX-Assert ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Candidate parent-child identity'
  KX-Assert ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Expected Caddy process image'
  $allCaddy=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop)
  $owners=@(KX-Listener 443|Select-Object -ExpandProperty OwningProcess -Unique)
  KX-Assert ($allCaddy.Count -eq 1 -and [int]$allCaddy[0].ProcessId -eq [int]$child.ProcessId -and
   $owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) '443 owned by verified candidate SYSTEM Caddy child'
  KX-Assert (@(KX-Listener 2019|Where-Object{$_.LocalAddress -notin @('127.0.0.1','::1')}).Count -eq 0) 'Caddy admin not exposed'
  $kv=@(KX-Listener 9444)
  KX-Assert ($kv.Count -eq 1 -and $kv[0].LocalAddress -ceq '127.0.0.1') 'K-V remains loopback'
}
function KX-ExclusiveLock {
 $p=Join-Path $script:BundleRoot 'transaction.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: Exclusive cross-session lock timeout'
}
function KX-State {return Get-Content -LiteralPath (Join-Path $script:BundleRoot 'transaction.json') -Raw|ConvertFrom-Json}
function KX-SetState($s,[string]$next){
 $s.phase=$next
 $p=Join-Path $script:BundleRoot 'transaction.json'
 # Unique staging name survives an executor crash without blocking independent recovery.
 $tmp=$p+'.next.'+[guid]::NewGuid().ToString('N')
 try{
  KX-Assert (-not (Test-Path -LiteralPath $tmp)) 'Unique transaction state temp'
  $s|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $tmp -Encoding UTF8 -ErrorAction Stop
  [IO.File]::Replace($tmp,$p,[NullString]::Value)
 }finally{
  if(Test-Path -LiteralPath $tmp -PathType Leaf){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
 }
}
function KX-ArmWatchdog($state,$pkg) {
 $script:Step='ARM_RECOVERY'
 $taskName='VehiculoIoT-KX-PROD-Recovery-'+$state.transaction_id
 KX-Assert ($taskName -match '^VehiculoIoT-KX-PROD-Recovery-[a-f0-9]{32}$') 'Watchdog task identity'
 KX-Assert ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)) 'No duplicate watchdog task'
 $scriptPath=Join-Path $script:BundleRoot 'kx_prod_recoverer_v4_RELEASE.ps1'
 KX-File $scriptPath ([string]$pkg.hashes.recoverer)
 # A real cutover must never be paired with a locked, nonfunctional independent recoverer.
 $recovererText=[IO.File]::ReadAllText($scriptPath)
 KX-Assert ($recovererText.Contains('$script:EnableProductionRecovery=$true') -and
  -not $recovererText.Contains('$script:EnableProductionRecovery=$false')) 'Only a separately approved, enabled SYSTEM recoverer may be armed'
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $watchdogArgs='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'" -Action Recover -Bundle "'+$script:BundleRoot+'"'
 $action=New-ScheduledTaskAction -Execute $exe -Argument $watchdogArgs
 $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
 $one=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(6)
 $boot=New-ScheduledTaskTrigger -AtStartup
 $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
 Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Trigger @($one,$boot) -ErrorAction Stop|Out-Null
 $task=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
 KX-Assert ($task.State -ne 'Disabled' -and @($task.Actions).Count -eq 1) 'Watchdog task registered'
 KX-Assert (@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$task.Principal.UserId) 'Watchdog SYSTEM owner'
 return $taskName
}
function KX-StopTrackedCaddy {
 $script:Step='STOP_TRACKED_CADDY'
 $null=KX-CurrentTask
 $record=Get-Content -LiteralPath $script:RunRecord -Raw|ConvertFrom-Json
 $super=KX-MatchRecord $record.supervisor
 $child=KX-MatchRecord $record.child
 $owners=@(KX-Listener 443|Select-Object -ExpandProperty OwningProcess -Unique)
 KX-Assert ($null -ne $super -and $null -ne $child -and
  $owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) 'Only tracked Caddy can be stopped'
 KX-Assert ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Tracked exact process tree'
 Disable-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop|Out-Null
 & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $super.ProcessId /T /F 2>&1|Out-Null
 $t=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 if($t.State -eq 'Running'){Stop-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop}
 for($i=0;$i -lt 80;$i++){
  if(@(KX-Listener 443).Count -eq 0 -and
    @((Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction SilentlyContinue)).Count -eq 0){return}
  Start-Sleep -Milliseconds 250
 }
 throw 'NO-GO: Caddy 443 did not stop cleanly'
}
function KX-ReplaceCandidate([string]$src,[string]$target,[string]$expectedOld,[string]$expectedNew,[string]$name){
 $script:Step='PATCH_'+$name
 KX-File $src $expectedNew
 KX-File $target $expectedOld
 $tmp=$target+'.kxnext.'+[guid]::NewGuid().ToString('N')
 $bkp=Join-Path $script:BundleRoot ('before_patch_'+$name+'.bak')
 KX-Assert (-not(Test-Path -LiteralPath $tmp) -and -not(Test-Path -LiteralPath $bkp)) 'Patch temps are unused'
 [IO.File]::Copy($src,$tmp,$false)
 KX-File $tmp $expectedNew
 [IO.File]::Replace($tmp,$target,$bkp)
 KX-File $target $expectedNew
 KX-File $bkp $expectedOld
}
function KX-ExecuteTransaction($pkg) {
 $script:Step='TRANSACTION'
 $state=KX-State
 KX-Assert ($state.schema_version -eq 1 -and $state.phase -ceq 'PREPARED' -and
  [string]$state.transaction_id -match '^[a-f0-9]{32}$') 'Prepared unique transaction'
 KX-RequireBaseline $pkg
 KX-HealthOriginal
 $wd=KX-ArmWatchdog $state $pkg
 $script:RecoveryArmed=$true
 # Exercise the exact SYSTEM watchdog entrypoint while state is PREPARED and no
 # live file or task has changed. The recoverer must exit 0 without actions.
 $script:Step='WATCHDOG_SYSTEM_PROBE'
 $probeStarted=[DateTime]::Now.AddSeconds(-2)
 Start-ScheduledTask -TaskPath '\' -TaskName $wd -ErrorAction Stop
 $probeOK=$false
 for($n=0;$n -lt 120;$n++){
  $info=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $wd -ErrorAction Stop
  $taskNow=Get-ScheduledTask -TaskPath '\' -TaskName $wd -ErrorAction Stop
  if($info.LastRunTime -ge $probeStarted -and
     $taskNow.State -ne 'Running' -and
     $info.LastTaskResult -eq 0){$probeOK=$true;break}
  Start-Sleep -Milliseconds 250
 }
 KX-Assert $probeOK 'Independent recovery task must pass SYSTEM PREPARED no-op before cutover'
 KX-Assert ((KX-State).phase -ceq 'PREPARED') 'SYSTEM preflight never changes transaction phase'
 $script:LockHandle=KX-ExclusiveLock
 try{
  $state=KX-State
  KX-SetState $state 'ARMED'
  KX-StopTrackedCaddy
  $state=KX-State
  KX-SetState $state 'QUIESCING'
  KX-ReplaceCandidate (Join-Path $script:BundleRoot 'Caddyfile.candidate.NOT_ACTIVE') $script:Caddy ([string]$pkg.hashes.caddy_original) ([string]$pkg.hashes.caddy_candidate) 'Caddy'
  $state=KX-State
  KX-SetState $state 'PATCHING'
  KX-ReplaceCandidate (Join-Path $script:BundleRoot 'run_caddy.candidate.NOT_ACTIVE.ps1') $script:Launcher ([string]$pkg.hashes.launcher_original) ([string]$pkg.hashes.launcher_candidate) 'Launcher'
  $state=KX-State
  KX-SetState $state 'STARTING'
  $null=KX-CurrentTask
  Enable-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop|Out-Null
  Start-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
  $state=KX-State
  KX-SetState $state 'VERIFYING'
  KX-HealthCandidate $pkg
  $state=KX-State
  KX-SetState $state 'COMMITTED_VERIFIED'
 }finally{
  if($null -ne $script:LockHandle){$script:LockHandle.Dispose();$script:LockHandle=$null}
 }
 $script:Step='DISARM_WATCHDOG'
 Unregister-ScheduledTask -TaskPath '\' -TaskName $wd -Confirm:$false -ErrorAction Stop
 KX-Assert ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $wd -ErrorAction SilentlyContinue)) 'Watchdog successfully removed after verified commit'
 $script:RecoveryArmed=$false
}
try {
 KX-Assert ($PSVersionTable.PSVersion.Major -eq 5) 'PowerShell 5'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Fixed release path'
 if($Action -ceq 'Cutover'){
  if(-not $script:EnableProductionCutover){throw 'NO-GO: PRODUCTION_RELEASE_NOT_ENABLED'}
  KX-Assert ([bool]$AuthorizeRealCutover) 'Real HTTPS cutover requires explicit -AuthorizeRealCutover switch'
 }else{
  KX-Assert (-not [bool]$AuthorizeRealCutover) 'Review mode never accepts cutover authorization'
 }
 $pkg=KX-Package
 if($Action -ceq 'Review'){
  KX-RequireBaseline $pkg
  $state=KX-State
  KX-Assert ($state.phase -ceq 'PREPARED') 'No live transaction armed'
  Write-Host '=== K-X CONTROLLER REVIEW: READY, HTTPS CUTOVER LOCKED ===' -ForegroundColor Green
 }else{
  $identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  KX-Assert ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Admin elevated'
  KX-ExecuteTransaction $pkg
  Write-Host '=== K-X CUTOVER COMMITTED: PUBLIC CHECKS PASSED ===' -ForegroundColor Green
 }
 $script:Success=$true
}catch{
 Write-Host ('=== NO-GO K-X CONTROLLER / '+$script:Step+' ===') -ForegroundColor Red
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host 'Detalle privado omitido. No exponer secretos ni reiniciar servicios ajenos.' -ForegroundColor Yellow
 if($null -ne $script:LockHandle){try{$script:LockHandle.Dispose()}catch{};$script:LockHandle=$null}
 if($script:RecoveryArmed){
  try{
   $state=KX-State
   if($state.phase -ceq 'COMMITTED_VERIFIED'){
    Write-Host 'POST-COMMIT: do not force rollback because watchdog cleanup failed.' -ForegroundColor Yellow
   }elseif($state.phase -in @('ARMED','QUIESCING','PATCHING','STARTING','VERIFYING','ROLLBACK_IN_PROGRESS')){
    $taskName='VehiculoIoT-KX-PROD-Recovery-'+[string]$state.transaction_id
    if($taskName -match '^VehiculoIoT-KX-PROD-Recovery-[a-f0-9]{32}$'){
     Start-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
     Write-Host 'SYSTEM recovery requested; verify status.' -ForegroundColor Yellow
    }
   }elseif($state.phase -ceq 'PREPARED'){
    $taskName='VehiculoIoT-KX-PROD-Recovery-'+[string]$state.transaction_id
    if($taskName -match '^VehiculoIoT-KX-PROD-Recovery-[a-f0-9]{32}$'){
     Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false -ErrorAction Stop
     Write-Host 'Recovery task cleaned; production PREPARED unchanged.' -ForegroundColor Yellow
    }
   }else{
    Write-Host 'NO-GO: unknown state; recovery not dispatched.' -ForegroundColor Yellow
   }
  }catch{Write-Host 'NO-GO: recovery dispatch failed; operator incident response required.' -ForegroundColor Red}
 }
}
if(-not $script:Success){exit 1}
exit 0
