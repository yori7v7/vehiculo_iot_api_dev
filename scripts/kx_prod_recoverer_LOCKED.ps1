# K-X production HTTPS rollback candidate, Windows PowerShell 5.1.
# STAGED AND LOCKED: contains proposed real recovery logic, but cannot mutate production.
# Never copy secrets to the release bundle. Dedicated SYSTEM task required for eventual release.
param(
 [ValidateSet('Review','Recover')][string]$Action='Review',
 [string]$Bundle='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v1_NOT_ARMED'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:EnableProductionRecovery=$false  # release gate: must remain FALSE in this draft
$script:Step='BEGIN'
$script:Success=$false
$script:Home='C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v1_NOT_ARMED'
$script:Caddy='C:\ProgramData\VehiculoIoT\Caddyfile'
$script:Launcher='C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$script:Task='VehiculoIoT-Caddy'
$script:RunRecord='C:\ProgramData\VehiculoIoT\run\caddy.json'
$script:PublicBase='https://100-30-4-62.nip.io'

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
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Fixed bundle path'
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($PSScriptRoot),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Recovery runs from installed bundle'
 KX-Assert (Test-Path -LiteralPath $script:Home -PathType Container) 'Bundle folder'
 KX-Assert ((Get-Acl -LiteralPath $script:Home).AreAccessRulesProtected) 'Bundle protected ACL'
 $pkg=Get-Content -LiteralPath (Join-Path $script:Home 'package.json') -Raw -ErrorAction Stop|ConvertFrom-Json
 KX-Assert ($pkg.schema_version -eq 1 -and $pkg.mode -ceq 'prod_cutover_bundle_prepared_not_armed') 'Immutable release preparation manifest'
 foreach($t in @('caddy_original','launcher_original','caddy_candidate','launcher_candidate','task_xml','controller','recoverer')){
  KX-Assert (($pkg.hashes.PSObject.Properties.Name -contains $t)) 'Required hash field'
 }
 $names=@{
  caddy_original='Caddyfile.original'
  launcher_original='run_caddy.original.ps1'
  caddy_candidate='Caddyfile.candidate.NOT_ACTIVE'
  launcher_candidate='run_caddy.candidate.NOT_ACTIVE.ps1'
  task_xml='VehiculoIoT-Caddy.original.task.xml'
  controller='kx_prod_cutover_controller_LOCKED.ps1'
  recoverer='kx_prod_recoverer_LOCKED.ps1'
 }
 foreach($key in $names.Keys){KX-File (Join-Path $script:Home $names[$key]) ([string]$pkg.hashes.$key) $key}
 KX-Assert ([string]$pkg.hashes.launcher_original -ceq '873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1') 'Original launcher identity'
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
 $null=KX-TaskSnapshot
 $r=Get-Content -LiteralPath $script:RunRecord -Raw -ErrorAction Stop|ConvertFrom-Json
 $super=KX-GetTracked $r.supervisor
 $child=KX-GetTracked $r.child
 $ports=@(KX-Listeners 443)
 $owners=@($ports | Select-Object -ExpandProperty OwningProcess -Unique)
 KX-Assert ($owners.Count -le 1) 'No multiple HTTPS owners'
 if($ports.Count -gt 0) {
  KX-Assert ($null -ne $super -and $null -ne $child) 'Tracked Caddy parent and child'
  KX-Assert ([int]$child.ParentProcessId -eq [int]$super.ProcessId) 'Tracked parent-child relation'
  KX-Assert ([IO.Path]::GetFileName([string]$child.ExecutablePath) -ceq 'caddy.exe') 'Tracked caddy.exe child'
  KX-Assert ([int]$owners[0] -eq [int]$child.ProcessId) 'HTTPS owner is tracked Caddy'
 }
 # No name-based process termination. Disable retries FIRST (999 / PT1M).
 Disable-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop|Out-Null
 if($null -ne $super) {
  & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $super.ProcessId /T /F 2>&1|Out-Null
 }
 $t=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
 if($t.State -eq 'Running'){Stop-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop}
 for($i=0;$i -lt 80;$i++){
  if(@(KX-Listeners 443).Count -eq 0 -and
    $null -eq (Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction SilentlyContinue)){return}
  Start-Sleep -Milliseconds 250
 }
 throw 'NO-GO: Caddy process or HTTPS listener remains'
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
 $backup=Join-Path $script:Home ($label+'.restored-from.'+$id+'.bak')
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
 $good=$false
 for($i=0;$i -lt 50;$i++){
  try{
   $p443=@(KX-Listeners 443)
   $t=Get-ScheduledTask -TaskPath '\' -TaskName $script:Task -ErrorAction Stop
   if($t.State -eq 'Running' -and $p443.Count -gt 0 -and
      (KX-PublicGet '/health') -eq 200 -and (KX-PublicGet '/openapi.json') -eq 200){
      $good=$true;break
   }
  }catch{}
  Start-Sleep -Milliseconds 500
 }
 KX-Assert $good 'Original HTTPS legacy GET health'
}
function KX-Lock {
 $script:Step='LOCK'
 $file=Join-Path $script:Home 'transaction.lock'
 for($i=0;$i -lt 200;$i++){
  try{return [IO.File]::Open($file,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch [IO.IOException]{Start-Sleep -Milliseconds 100}
 }
 throw 'NO-GO: Transaction lock was not acquired'
}
function KX-ReadState {
 return Get-Content -LiteralPath (Join-Path $script:Home 'transaction.json') -Raw -ErrorAction Stop|ConvertFrom-Json
}
function KX-SaveState($state,[string]$next) {
 $state.phase=$next
 $p=Join-Path $script:Home 'transaction.json'
 $tmp=$p+'.next'
 KX-Assert (-not (Test-Path -LiteralPath $tmp)) 'State temp available'
 $state|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $tmp -Encoding UTF8
 [IO.File]::Replace($tmp,$p,[NullString]::Value)
}
function KX-PerformRecovery($pkg) {
 $script:Step='BEGIN_RECOVERY'
 $handle=KX-Lock
 try{
  $state=KX-ReadState
  KX-Assert ($state.schema_version -eq 1 -and
   [string]$state.transaction_id -match '^[a-f0-9]{32}$') 'Transaction state version'
  KX-Assert ($state.phase -in @('ARMED','QUIESCING','PATCHING','STARTING','VERIFYING','ROLLBACK_IN_PROGRESS')) 'Transaction eligible for recovery'
  KX-StopOnlyTrackedCaddy
  KX-SaveState $state 'ROLLBACK_IN_PROGRESS'
  KX-ReplaceWithVerifiedOriginal (Join-Path $script:Home 'Caddyfile.original') $script:Caddy ([string]$pkg.hashes.caddy_original) ([string]$pkg.hashes.caddy_candidate) 'Caddyfile'
  KX-ReplaceWithVerifiedOriginal (Join-Path $script:Home 'run_caddy.original.ps1') $script:Launcher ([string]$pkg.hashes.launcher_original) ([string]$pkg.hashes.launcher_candidate) 'Launcher'
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
 KX-Assert ([string]::Equals([IO.Path]::GetFullPath($Bundle).TrimEnd('\'),$script:Home,[StringComparison]::OrdinalIgnoreCase)) 'Known fixed bundle'
 if($Action -ceq 'Recover') {
  if(-not $script:EnableProductionRecovery){throw 'NO-GO: PRODUCTION_RECOVERY_LOCKED_PENDING_RELEASE_REVIEW'}
 }
 $pkg=KX-RequireBundle
 if($Action -ceq 'Review'){
  KX-File $script:Caddy ([string]$pkg.hashes.caddy_original) 'Production Caddy still original'
  KX-File $script:Launcher ([string]$pkg.hashes.launcher_original) 'Production launcher still original'
  $null=KX-TaskSnapshot
  Write-Host '=== K-X RECOVERER: REVIEW READY, LIVE RECOVERY LOCKED ===' -ForegroundColor Green
 }else{
  KX-Assert ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ceq 'S-1-5-18') 'Recovery requires SYSTEM'
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
