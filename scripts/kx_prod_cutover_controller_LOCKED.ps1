# K-X real HTTPS Caddy transaction candidate. Windows PowerShell 5.1.
# STAGED AND LOCKED. Contains proposed bounded public release logic, cannot invoke it.
# Do not modify this gate without separate system-specific acceptance and authorized window.
param(
 [ValidateSet('Review','Cutover')][string]$Action='Review',
 [string]$Bundle='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v1_NOT_ARMED'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:EnableProductionCutover=$false
$script:Step='BEGIN'
$script:Success=$false
$script:RecoveryArmed=$false
$script:LockHandle=$null
$script:Home='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v1_NOT_ARMED'
$script:Task='VehiculoIoT-Caddy'
$script:Caddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$script:Launcher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$script:RunRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
$script:PublicBase='https://100-30-4-62.nip.io'
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
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Known package path'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($PSScriptRoot),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Controller lives inside the private bundle'
 KX-Assert ((Get-Acl -LiteralPath $script:Home).AreAccessRulesProtected) 'Bundle must have protected ACL'
 $pkg=Get-Content -LiteralPath (Join-Path $script:Home 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Assert ($pkg.schema_version -eq 1 -and $pkg.mode -ceq 'prod_cutover_bundle_prepared_not_armed') 'Known prepared bundle'
 $pairs=@{
  caddy_original='Caddyfile.original'
  launcher_original='run_caddy.original.ps1'
  caddy_candidate='Caddyfile.candidate.NOT_ACTIVE'
  launcher_candidate='run_caddy.candidate.NOT_ACTIVE.ps1'
  controller='kx_prod_cutover_controller_LOCKED.ps1'
  recoverer='kx_prod_recoverer_LOCKED.ps1'
  task_xml='VehiculoIoT-Caddy.original.task.xml'
 }
 foreach($k in $pairs.Keys){KX-File (Join-Path $script:Home $pairs[$k]) ([string]$pkg.hashes.$k)}
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
 KX-HttpStatus ($script:PublicBase+'/health') '' '' 200
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
}
function KX-ExclusiveLock {
 $p=Join-Path $script:Home 'transaction.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: Exclusive cross-session lock timeout'
}
function KX-State {return Get-Content -LiteralPath (Join-Path $script:Home 'transaction.json') -Raw|ConvertFrom-Json}
function KX-SetState($s,[string]$next){
 $s.phase=$next
 $p=Join-Path $script:Home 'transaction.json'
 $tmp=$p+'.next'
 KX-Assert (-not (Test-Path -LiteralPath $tmp)) 'State temp free'
 $s|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $tmp -Encoding UTF8
 [IO.File]::Replace($tmp,$p,[NullString]::Value)
}
function KX-ArmWatchdog($state,$pkg) {
 $script:Step='ARM_RECOVERY'
 $taskName='VehiculoIoT-KX-PROD-Recovery-'+$state.transaction_id
 KX-Assert ($taskName -match '^VehiculoIoT-KX-PROD-Recovery-[a-f0-9]{32}$') 'Watchdog task identity'
 KX-Assert ($null -eq (Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)) 'No duplicate watchdog task'
 $scriptPath=Join-Path $script:Home 'kx_prod_recoverer_LOCKED.ps1'
 KX-File $scriptPath ([string]$pkg.hashes.recoverer)
 $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'" -Action Recover -Bundle "'+$script:Home+'"'
 $action=New-ScheduledTaskAction -Execute $exe -Argument $args
 $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
 $one=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(6)
 $boot=New-ScheduledTaskTrigger -AtStartup
 $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
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
 $bkp=Join-Path $script:Home ('before_patch_'+$name+'.bak')
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
 $script:LockHandle=KX-ExclusiveLock
 try{
  $state=KX-State
  KX-SetState $state 'ARMED'
  KX-StopTrackedCaddy
  $state=KX-State
  KX-SetState $state 'QUIESCING'
  KX-ReplaceCandidate (Join-Path $script:Home 'Caddyfile.candidate.NOT_ACTIVE') $script:Caddy ([string]$pkg.hashes.caddy_original) ([string]$pkg.hashes.caddy_candidate) 'Caddy'
  $state=KX-State
  KX-SetState $state 'PATCHING'
  KX-ReplaceCandidate (Join-Path $script:Home 'run_caddy.candidate.NOT_ACTIVE.ps1') $script:Launcher ([string]$pkg.hashes.launcher_original) ([string]$pkg.hashes.launcher_candidate) 'Launcher'
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
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Fixed release path'
 if($Action -ceq 'Cutover' -and -not $script:EnableProductionCutover){throw 'NO-GO: PRODUCTION_CUTOVER_LOCKED_PENDING_RELEASE_REVIEW'}
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
  $state=KX-State
  $taskName='VehiculoIoT-KX-PROD-Recovery-'+[string]$state.transaction_id
  try{
   if($taskName -match '^VehiculoIoT-KX-PROD-Recovery-[a-f0-9]{32}$'){
    Start-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    Write-Host 'Recovery task SYSTEM requested; verify status before further action.' -ForegroundColor Yellow
   }
  }catch{Write-Host 'NO-GO: System recovery trigger failed; manual operator response required' -ForegroundColor Red}
 }
}
if(-not $script:Success){exit 1}
exit 0
