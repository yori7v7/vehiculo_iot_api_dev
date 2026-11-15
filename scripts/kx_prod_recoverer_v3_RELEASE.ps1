# K-X production HTTPS rollback candidate, Windows PowerShell 5.1.
# RELEASE CANDIDATE: invoked only under SYSTEM by verified transaction watchdog task.
# Never copy secrets to the release bundle. Dedicated SYSTEM task required for eventual release.
param(
 [ValidateSet('Review','Recover')][string]$Action='Review',
 [string]$Bundle='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v3_RELEASE_READY'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:EnableProductionRecovery=$true  # release guarded: Action Recover requires SID SYSTEM and manifest match
$script:Step='BEGIN'
$script:Success=$false
$script:BundleRoot='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v3_RELEASE_READY'
$script:Caddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$script:Launcher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$script:Task='VehiculoIoT-Caddy'
$script:RunRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
$script:PublicBase='https://100-30-4-62.nip.io'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function KX-Assert([bool]$truth,[string]$label) {
 if(-not $truth){throw ('NO-GO: '+$label)}
}
function KX-Hash([string]$path) {
 return (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash
}
function KX-File([string]$path,[string]$expected,[string]$label) {
 KX-Assert (Test-Path -LiteralPath $path -PathType Leaf) ($label+' present')
 KX-Assert (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ($label+' no reparse')
 KX-Assert ((KX-Hash $path) -ceq $expected) ($label+' hash')
}
function KX-RequireBundle {
 $script:Step='BUNDLE'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Fixed bundle path'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($PSScriptRoot),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Recovery runs from installed bundle'
 KX-Assert (Test-Path -LiteralPath $script:BundleRoot -PathType Container) 'Bundle folder'
 KX-Assert ((Get-Acl -LiteralPath $script:BundleRoot).AreAccessRulesProtected) 'Bundle protected ACL'
 $pkg=Get-Content -LiteralPath (Join-Path $script:BundleRoot 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Assert ($pkg.schema_version -eq 1 -and $pkg.mode -ceq 'prod_cutover_bundle_v3_release_ready') 'Immutable release preparation manifest'
 foreach($t in @('caddy_original','launcher_original','caddy_candidate','launcher_candidate','task_xml','controller','recoverer')){
  KX-Assert (($pkg.hashes.PSObject.Properties.Name -contains $t)) 'Required hash field'
 }
 $names=@{
  caddy_original='Caddyfile.original'
  launcher_original='run_caddy.original.ps1'
  caddy_candidate='Caddyfile.candidate.NOT_ACTIVE'
  launcher_candidate='run_caddy.candidate.NOT_ACTIVE.ps1'
  task_xml='VehiculoIoT-Caddy.original.task.xml'
  controller='kx_prod_cutover_controller_v3_RELEASE.ps1'
  recoverer='kx_prod_recoverer_v3_RELEASE.ps1'
 }
 foreach($key in $names.Keys){KX-File (Join-Path $script:BundleRoot $names[$key]) ([string]$pkg.hashes.$key) $key}
 KX-Assert ([string]$pkg.hashes.launcher_original -ceq '873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1') 'Original launcher identity'
 KX-Assert ($pkg.release_enabled -eq $true -and $pkg.recovery_enabled -eq $true) 'Release must explicitly arm both executables'
 return $pkg
}
function KX-TaskSnapshot {
 $script:Step='CADDY_TASK'
 $t=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 $actions=@($t.Actions)
 KX-Assert ($actions.Count -eq 1) 'Exactly one Caddy task action'
 KX-Assert ([string]$actions[0].Arguments -like ('*'+$script:Launcher+'*')) 'Original launcher path retained by task'
 KX-Assert (@('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -contains [string]$t.Principal.UserId) 'Original SYSTEM principal'
 [xml]$xml=Export-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 $ns=New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $count=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Count',$ns)
 $interval=$xml.SelectSingleNode('//t:Settings/t:RestartOnFailure/t:Interval',$ns)
 KX-Assert ($null -ne $count -and $null -ne $interval) 'Retry nodes present'
 KX-Assert ([int]$count.InnerText -eq 999 -and $interval.InnerText -ceq 'PT1M') 'Original retry settings'
 return $t
}
function KX-GetTracked($entry) {
 if($null -eq $entry){return $null}
 $p=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$entry.process_id) -ErrorAction SilentlyContinue
 if($null -eq $p){return $null}
 KX-Assert ($p.CreationDate.ToUniversalTime().Ticks.ToString() -ceq [string]$entry.creation_ticks) 'Process creation ticks match'
 KX-Assert ([string]::Equals([string]$p.ExecutablePath,[string]$entry.executable_path,[StringComparison]::OrdinalIgnoreCase)) 'Process executable match'
 KX-Assert ((Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop).Sid -ceq 'S-1-5-18') 'Process belongs to SYSTEM'
 return $p
}
function KX-Listeners([int]$p) {return @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)}
function KX-StopOnlyTrackedCaddy {
 $script:Step='STOP_CADDY_EXACT'
 $taskRef=KX-TaskSnapshot
 $ports=@(KX-Listeners 443)
 $owners=@($ports | Select-Object -ExpandProperty OwningProcess -Unique)
 $caddies=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop)
 KX-Assert ($owners.Count -le 1 -and $caddies.Count -le 1) 'Single known HTTPS owner and Caddy process maximum'

 $super=$null;$child=$null
 if(Test-Path -LiteralPath $script:RunRecord -PathType Leaf){
  KX-Assert (((Get-Item -LiteralPath $script:RunRecord -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Runtime record is not a link'
  $rec=Get-Content -LiteralPath $script:RunRecord -Raw -ErrorAction Stop|ConvertFrom-Json
  $super=KX-GetTracked $rec.supervisor
  $child=KX-GetTracked $rec.child
 }
 if($ports.Count -gt 0 -or $caddies.Count -gt 0){
  KX-Assert ($null -ne $super -and $null -ne $child) 'Caddy alive but no fully verified supervisor/child'
  KX-Assert ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Exact supervisor parent'
  KX-Assert ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Tracked original Caddy'
  KX-Assert ($caddies.Count -eq 1 -and [int]$caddies[0].ProcessId -eq [int]$child.ProcessId) 'No untracked Caddy'
  if($ports.Count -gt 0){
   KX-Assert ($owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId) 'HTTPS owned by tracked Caddy'
  }
 }else{
  # A verified task is safe to stop even if its supervisor record disappeared after exit.
  # There must be NO remaining Caddy or HTTPS listener; do not touch an unknown process.
  KX-Assert ($caddies.Count -eq 0 -and $ports.Count -eq 0) 'Caddy/listener absent before safe task stop'
 }
 # Disable retry count 999 before ANY kill or stop.
 Disable-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop|Out-Null
 if($null -ne $super){
  # Terminate only the previously verified original SYSTEM supervisor PID tree.
  & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $super.ProcessId /T /F 2>&1|Out-Null
 }
 $taskNow=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 if($taskNow.State -eq 'Running'){Stop-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop}
 for($i=0;$i -lt 80;$i++){
  if(@(KX-Listeners 443).Count -eq 0 -and
   @(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction SilentlyContinue).Count -eq 0){return}
  Start-Sleep -Milliseconds 250
 }
 throw 'NO-GO: Caddy or HTTPS 443 still running after bounded stop'
}
function KX-ReplaceWithVerifiedOriginal([string]$source,[string]$target,[string]$old,[string]$candidate,[string]$label) {
 $script:Step='RESTORE_'+$label
 KX-File $source $old ('Private original '+$label)
 KX-Assert (Test-Path -LiteralPath $target -PathType Leaf) 'Production target exists'
 $existing=KX-Hash $target
 if($existing -ceq $old){return}
 KX-Assert ($existing -ceq $candidate) 'Production target has only recognized candidate hash'
 $id=[guid]::NewGuid().ToString('N')
 $incoming=$target+'.kxrestore.'+$id+'.incoming'
 $backup=Join-Path $script:BundleRoot ($label+'.restored-from.'+$id+'.bak')
 KX-Assert (-not(Test-Path -LiteralPath $incoming) -and -not(Test-Path -LiteralPath $backup)) 'No colliding recovery files'
 [IO.File]::Copy($source,$incoming,$false)
 KX-File $incoming $old ('Incoming original '+$label)
 [IO.File]::Replace($incoming,$target,$backup)
 KX-File $target $old ('Restored '+$label)
}
function KX-PublicGet([string]$path) {
 $req=[Net.HttpWebRequest]::Create($script:PublicBase+$path)
 $req.Method='GET'
 $req.AllowAutoRedirect=$false
 $req.Timeout=8000
 $req.Proxy=$null
 $response=$null
 try{
  $response=$req.GetResponse()
  return [int]$response.StatusCode
 }finally{if($null -ne $response){$response.Close()}}
}
function KX-RequireLegacyHealth {
 $script:Step='ORIGINAL_HEALTH'
 $healthy=$false
 for($i=0;$i -lt 70;$i++){
  try{
   $t=KX-TaskSnapshot
   $caddyHash=KX-Hash $script:Caddy
   $launcherHash=KX-Hash $script:Launcher
   $pkg=Get-Content -LiteralPath (Join-Path $script:BundleRoot 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
   $record=Get-Content -LiteralPath $script:RunRecord -Raw -ErrorAction Stop|ConvertFrom-Json
   $super=KX-GetTracked $record.supervisor
   $child=KX-GetTracked $record.child
   $ports=@(KX-Listeners 443)
   $owners=@($ports | Select-Object -ExpandProperty OwningProcess -Unique)
   $allCaddy=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop)
   if($t.State -eq 'Running' -and
      $caddyHash -ceq [string]$pkg.hashes.caddy_original -and
      $launcherHash -ceq [string]$pkg.hashes.launcher_original -and
      $null -ne $super -and $null -ne $child -and
      [int]$child.ParentProcessId -eq [int]$super.ProcessId -and
      $allCaddy.Count -eq 1 -and [int]$allCaddy[0].ProcessId -eq [int]$child.ProcessId -and
      $owners.Count -eq 1 -and [int]$owners[0] -eq [int]$child.ProcessId -and
      (KX-PublicGet '/health') -eq 200 -and (KX-PublicGet '/openapi.json') -eq 200){
      $healthy=$true;break
   }
  }catch{}
  Start-Sleep -Milliseconds 500
 }
 KX-Assert $healthy 'Original task+SYSTEM owner+file hash+HTTPS/TLS GET health'
}
function KX-Lock {
 $script:Step='LOCK'
 $file=Join-Path $script:BundleRoot 'transaction.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($file,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: Transaction lock was not acquired'
}
function KX-ReadState {
 return Get-Content -LiteralPath (Join-Path $script:BundleRoot 'transaction.json') -Raw -ErrorAction Stop|ConvertFrom-Json
}
function KX-SaveState($state,[string]$next) {
 $state.phase=$next
 $p=Join-Path $script:BundleRoot 'transaction.json'
 # Per-write GUID prevents a crashed executor from blocking the independent SYSTEM recoverer.
 $tmp=$p+'.next.'+[guid]::NewGuid().ToString('N')
 try{
  KX-Assert (-not(Test-Path -LiteralPath $tmp)) 'Unique transaction state temp'
  $state|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $tmp -Encoding UTF8 -ErrorAction Stop
  [IO.File]::Replace($tmp,$p,[NullString]::Value)
 }finally{
  if(Test-Path -LiteralPath $tmp -PathType Leaf){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
 }
}
function KX-PerformRecovery($pkg) {
 $script:Step='BEGIN_RECOVERY'
 $handle=KX-Lock
 try{
  $state=KX-ReadState
  KX-Assert ($state.schema_version -eq 1 -and
   [string]$state.transaction_id -match '^[a-f0-9]{32}$') 'Transaction identity'
  # Idempotent terminal states must NEVER result in killing committed Caddy.
  if($state.phase -ceq 'PREPARED'){return}
  if($state.phase -ceq 'COMMITTED_VERIFIED'){
   KX-File $script:Caddy ([string]$pkg.hashes.caddy_candidate) 'Verified committed Caddy'
   KX-File $script:Launcher ([string]$pkg.hashes.launcher_candidate) 'Verified committed launcher'
   KX-Assert ((Get-ScheduledTask -TaskPath '\' -TaskName $script:Task).State -eq 'Running') 'Committed Caddy still scheduled'
   KX-Assert ((KX-PublicGet '/health') -eq 200 -and (KX-PublicGet '/openapi.json') -eq 200) 'Committed service still healthy'
   return
  }
  if($state.phase -ceq 'ROLLED_BACK_VERIFIED'){
   KX-File $script:Caddy ([string]$pkg.hashes.caddy_original) 'Verified previously rolled back Caddy'
   KX-File $script:Launcher ([string]$pkg.hashes.launcher_original) 'Verified previously rolled back launcher'
   KX-RequireLegacyHealth
   return
  }
  KX-Assert ($state.phase -in @('ARMED','QUIESCING','PATCHING','STARTING','VERIFYING','ROLLBACK_IN_PROGRESS')) 'Recoverable nonterminal state'
  KX-StopOnlyTrackedCaddy
  KX-SaveState $state 'ROLLBACK_IN_PROGRESS'
  KX-ReplaceWithVerifiedOriginal (Join-Path $script:BundleRoot 'Caddyfile.original') $script:Caddy ([string]$pkg.hashes.caddy_original) ([string]$pkg.hashes.caddy_candidate) 'Caddyfile'
  KX-ReplaceWithVerifiedOriginal (Join-Path $script:BundleRoot 'run_caddy.original.ps1') $script:Launcher ([string]$pkg.hashes.launcher_original) ([string]$pkg.hashes.launcher_candidate) 'Launcher'
  $script:Step='START_ORIGINAL'
  $null=KX-TaskSnapshot
  Enable-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop|Out-Null
  Start-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
  KX-RequireLegacyHealth
  $state=KX-ReadState
  KX-SaveState $state 'ROLLED_BACK_VERIFIED'
 }finally{$handle.Dispose()}
}
try {
 KX-Assert ($PSVersionTable.PSVersion.Major -eq 5) 'PowerShell 5.x'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:BundleRoot,[StringComparison]::OrdinalIgnoreCase)) 'Known fixed bundle'
 if($Action -ceq 'Recover') {
  if(-not $script:EnableProductionRecovery){throw 'NO-GO: RELEASE_RECOVERY_DISABLED'}
  KX-Assert ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ceq 'S-1-5-18') 'Only SYSTEM may invoke production recovery'
 }
 $pkg=KX-RequireBundle
 if($Action -ceq 'Review'){
  KX-File $script:Caddy ([string]$pkg.hashes.caddy_original) 'Production Caddy still original'
  KX-File $script:Launcher ([string]$pkg.hashes.launcher_original) 'Production launcher still original'
  $null=KX-TaskSnapshot
  Write-Host '=== K-X RECOVERER: REVIEW READY, LIVE RECOVERY LOCKED ===' -ForegroundColor Green
 }else{
  KX-PerformRecovery $pkg
  Write-Host 'K-X RECOVERY FINISHED: verify operator evidence' -ForegroundColor Green
 }
 $script:Success=$true
}catch{
 Write-Host ('=== NO-GO K-X RECOVERER / '+$script:Step+' ===') -ForegroundColor Red
 Write-Host ('TIPO: '+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host 'Sin detalles sensibles. No ejecutar el cutover.' -ForegroundColor Yellow
}
if(-not $script:Success){exit 1}
exit 0
