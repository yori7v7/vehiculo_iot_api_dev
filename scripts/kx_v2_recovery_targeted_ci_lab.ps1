# K-X focused V2 regression tests against AST-extracted REAL recovery/state functions.
# CI Windows runner ONLY. All file targets are fresh RUNNER_TEMP fixtures.
# Fake Task Scheduler / process / TCP / HTTPS functions; no real service or port operations.
# Deliberately do not execute the locked production script entrypoints.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:caseCount=0
function Assert([bool]$condition,[string]$message){
 if(-not $condition){throw ('K-X V2 CI NO-GO: '+$message)}
 Write-Host ('PASS: '+$message) -ForegroundColor Green
 $script:caseCount++
}
function MustThrow([scriptblock]$test,[string]$label){
 $didThrow=$false
 try{& $test}catch{$didThrow=$true}
 Assert $didThrow $label
}
Assert ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'Windows CI runner only'
Assert (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) 'Runner private temp provided'
$root=Join-Path $env:RUNNER_TEMP ('KX-V2-RECOVERY-CI-'+[guid]::NewGuid().ToString('N'))
Assert (-not(Test-Path -LiteralPath $root)) 'New and unique ephemeral test directory'
[IO.Directory]::CreateDirectory($root)|Out-Null

$recPath=Join-Path $PSScriptRoot 'kx_prod_recoverer_v2_LOCKED.ps1'
$ctlPath=Join-Path $PSScriptRoot 'kx_prod_cutover_controller_v2_LOCKED.ps1'
$expected=@{
 'KX-Assert'=$recPath
 'KX-Hash'=$recPath
 'KX-File'=$recPath
 'KX-Lock'=$recPath
 'KX-ReadState'=$recPath
 'KX-SaveState'=$recPath
 'KX-ReplaceWithVerifiedOriginal'=$recPath
 'KX-StopOnlyTrackedCaddy'=$recPath
 'KX-PerformRecovery'=$recPath
 'KX-SetState'=$ctlPath
}
$astCache=@{}
foreach($p in @($recPath,$ctlPath)){
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors)
 Assert (@($errors).Count -eq 0) 'Production V2 script parses in Windows PS5.1'
 $astCache[$p]=$ast
}
# Import only the individual source functions, never top-level code or entrypoints.
foreach($name in @('KX-Assert','KX-Hash','KX-File','KX-Lock','KX-ReadState',
 'KX-SaveState','KX-ReplaceWithVerifiedOriginal','KX-StopOnlyTrackedCaddy',
 'KX-PerformRecovery','KX-SetState')){
 $path=$expected[$name]
 $functions=@($astCache[$path].FindAll({
  param($n)
  $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
  $n.Name -ceq $name
 },$true))
 Assert ($functions.Count -eq 1) ('Production definition imported exactly: '+$name)
 . ([scriptblock]::Create($functions[0].Extent.Text))
}
$script:BundleRoot=$root
$script:Step='CI_FIXTURE'
$script:Task='KX-CI-FAKE-NEVER-REAL'
$script:RunRecord=Join-Path $root 'nonexistent-process-record.json'
$live=Join-Path $root 'fake-live'
[IO.Directory]::CreateDirectory($live)|Out-Null
$script:Caddy=Join-Path $live 'Caddyfile.MIRROR'
$script:Launcher=Join-Path $live 'run_caddy.MIRROR.ps1'

# Two original backups and two candidate payloads, all with FAKE text.
$oldC=Join-Path $root 'Caddyfile.original'
$oldL=Join-Path $root 'run_caddy.original.ps1'
$newC=Join-Path $root 'Caddyfile.candidate.NOT_ACTIVE'
$newL=Join-Path $root 'run_caddy.candidate.NOT_ACTIVE.ps1'
[IO.File]::WriteAllText($oldC,'K-X V2 CI ORIGINAL CADDY ONLY')
[IO.File]::WriteAllText($oldL,'K-X V2 CI ORIGINAL LAUNCHER ONLY')
[IO.File]::WriteAllText($newC,'K-X V2 CI CADDY CANDIDATE ONLY')
[IO.File]::WriteAllText($newL,'K-X V2 CI LAUNCHER CANDIDATE ONLY')
[IO.File]::WriteAllText((Join-Path $root 'transaction.lock'),'K-X CI TEST LOCK')
$pkg=[pscustomobject]@{
 hashes=[pscustomobject]@{
  caddy_original=(KX-Hash $oldC)
  launcher_original=(KX-Hash $oldL)
  caddy_candidate=(KX-Hash $newC)
  launcher_candidate=(KX-Hash $newL)
 }
}
function Write-FixtureState([string]$phase){
 $state=[ordered]@{
  schema_version=1
  transaction_id=[guid]::NewGuid().ToString('N')
  phase=$phase
 }
 $state|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $root 'transaction.json') -Encoding UTF8
}
function Write-Mirrors([bool]$candidateC,[bool]$candidateL){
 [IO.File]::Copy($(if($candidateC){$newC}else{$oldC}),$script:Caddy,$true)
 [IO.File]::Copy($(if($candidateL){$newL}else{$oldL}),$script:Launcher,$true)
}
function Read-Phase {return (Get-Content -LiteralPath (Join-Path $root 'transaction.json') -Raw|ConvertFrom-Json).phase}
Write-FixtureState 'ARMED'
Write-Mirrors $false $false

# Two different production implementations use unique temporary state names.
$orphan=Join-Path $root 'transaction.json.next'
$orphanGuid=Join-Path $root 'transaction.json.next.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
[IO.File]::WriteAllText($orphan,'PARTIAL-CRASH-SIMULATED')
[IO.File]::WriteAllText($orphanGuid,'PARTIAL-CRASH-GUID-SIMULATED')
$s=KX-ReadState
KX-SaveState $s 'PATCHING'
Assert ((Read-Phase) -ceq 'PATCHING') 'Recoverer state replacement survives abandoned .next files'
Assert (([IO.File]::ReadAllText($orphan)) -ceq 'PARTIAL-CRASH-SIMULATED') 'No deletion or trust of abandoned state temp'
$s=KX-ReadState
KX-SetState $s 'VERIFYING'
Assert ((Read-Phase) -ceq 'VERIFYING') 'Controller state replacement survives abandoned .next files'
$other=@(Get-ChildItem -LiteralPath $root -File -Filter 'transaction.json.next.*' |
 Where-Object {$_.Name -cne 'transaction.json.next.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'})
Assert ($other.Count -eq 0) 'No temporary files leaked by completed state writes'

# Override native operating system interactions for the source KX-StopOnlyTrackedCaddy:
# these PowerShell function mocks run in test scope and must never call real Task Scheduler/CIM.
$script:fakeTaskState='Ready'
$script:fakeCaddies=@()
$script:fakePortOwner=$null
$script:disableCalls=0
$script:stopTaskCalls=0
function KX-TaskSnapshot {return [pscustomobject]@{State=$script:fakeTaskState}}
function KX-Listeners([int]$p) {
 if($p -eq 443 -and $null -ne $script:fakePortOwner){
  return [pscustomobject]@{OwningProcess=[int]$script:fakePortOwner}
 }
 return @()
}
function Get-CimInstance {
 param([string]$ClassName,[string]$Filter,[string]$ErrorAction)
 if($ClassName -ceq 'Win32_Process' -and $Filter -like "Name='caddy.exe'"){
  return $script:fakeCaddies
 }
 return $null
}
function Get-ScheduledTask {
 param([string]$TaskPath,[string]$TaskName,[string]$ErrorAction)
 if($TaskName -cne $script:Task){throw 'CI guard: a non-fake scheduled task was requested'}
 return [pscustomobject]@{State=$script:fakeTaskState}
}
function Disable-ScheduledTask {
 param([string]$TaskPath,[string]$TaskName,[string]$ErrorAction)
 if($TaskName -cne $script:Task){throw 'CI guard: non-fake task disable'}
 $script:disableCalls++
 return [pscustomobject]@{State='Disabled'}
}
function Stop-ScheduledTask {
 param([string]$TaskPath,[string]$TaskName,[string]$ErrorAction)
 if($TaskName -cne $script:Task){throw 'CI guard: non-fake task stop'}
 $script:stopTaskCalls++
}
function Start-Sleep {param([int]$Milliseconds) }
Assert (-not(Test-Path -LiteralPath $script:RunRecord)) 'Simulated missing Caddy runtime record'
KX-StopOnlyTrackedCaddy
Assert ($script:disableCalls -eq 1 -and $script:stopTaskCalls -eq 0) 'No processes, missing record: fake stop is bounded and clean'
$script:fakeTaskState='Running'
$before=$script:disableCalls
MustThrow {KX-StopOnlyTrackedCaddy} 'Missing record + running task fails closed before any disable'
Assert ($script:disableCalls -eq $before) 'Unsafe orphaned task was not disabled'
$script:fakeTaskState='Ready'
$script:fakeCaddies=@([pscustomobject]@{ProcessId=73914})
MustThrow {KX-StopOnlyTrackedCaddy} 'Unknown Caddy process without identity fails closed'
Assert ($script:disableCalls -eq $before) 'Unknown Caddy PID was not touched'
$script:fakeCaddies=@()
$script:fakePortOwner=73914
MustThrow {KX-StopOnlyTrackedCaddy} 'Unknown port 443 owner fails closed'
Assert ($script:disableCalls -eq $before) 'Unknown HTTPS owner was not touched'
$script:fakePortOwner=$null

# Now exercise actual KX-PerformRecovery transitions with fake service operations.
# Only fixed fake files under RUNNER_TEMP are changed.
$script:stopCalls=0
$script:healthCalls=0
$script:enableCalls=0
$script:startCalls=0
function KX-StopOnlyTrackedCaddy {$script:stopCalls++}
function KX-RequireLegacyHealth {$script:healthCalls++}
function KX-PublicGet {param([string]$path);return 200}
function Enable-ScheduledTask {
 param([string]$TaskPath,[string]$TaskName,[string]$ErrorAction)
 if($TaskName -cne $script:Task){throw 'CI guard: non-fake enable'}
 $script:enableCalls++
}
function Start-ScheduledTask {
 param([string]$TaskPath,[string]$TaskName,[string]$ErrorAction)
 if($TaskName -cne $script:Task){throw 'CI guard: non-fake start'}
 $script:startCalls++
}
function Observe-NoShutdown([string]$label,[int]$oldStops,[int]$oldStarts){
 Assert ($script:stopCalls -eq $oldStops -and $script:startCalls -eq $oldStarts) $label
}
Write-FixtureState 'PREPARED'
Write-Mirrors $false $false
$a=$script:stopCalls;$b=$script:startCalls
KX-PerformRecovery $pkg
Assert ((Read-Phase) -ceq 'PREPARED') 'PREPARED stays unmodified'
Observe-NoShutdown 'PREPARED watchdog never stops or restarts Caddy' $a $b

Write-FixtureState 'COMMITTED_VERIFIED'
Write-Mirrors $true $true
$script:fakeTaskState='Running'
$a=$script:stopCalls;$b=$script:startCalls
KX-PerformRecovery $pkg
Assert ((Read-Phase) -ceq 'COMMITTED_VERIFIED') 'COMMITTED_VERIFIED remains terminal'
Assert ((KX-Hash $script:Caddy) -ceq $pkg.hashes.caddy_candidate -and
 (KX-Hash $script:Launcher) -ceq $pkg.hashes.launcher_candidate) 'Committed candidate hashes preserved'
Observe-NoShutdown 'Healthy commit does NOT trigger rollback or restart' $a $b

# Tampered committed artifact fails closed, not reverted behind the operator's back.
[IO.File]::WriteAllText($script:Caddy,'TAMPERED-FAKE-CADDY')
$a=$script:stopCalls;$b=$script:startCalls
MustThrow {KX-PerformRecovery $pkg} 'Invalid committed hash is reported, not silently repaired'
Observe-NoShutdown 'Invalid committed state does not kill the running service' $a $b

Write-FixtureState 'ROLLED_BACK_VERIFIED'
Write-Mirrors $false $false
$a=$script:stopCalls;$b=$script:startCalls;$h=$script:healthCalls
KX-PerformRecovery $pkg
Assert ((Read-Phase) -ceq 'ROLLED_BACK_VERIFIED' -and
 $script:healthCalls -eq ($h+1)) 'ROLLED_BACK_VERIFIED rechecks the original without changing state'
Observe-NoShutdown 'Verified prior rollback does not duplicate restart' $a $b

Write-FixtureState 'PATCHING'
Write-Mirrors $true $false
$script:fakeTaskState='Ready'
$a=$script:stopCalls;$b=$script:startCalls
KX-PerformRecovery $pkg
Assert ((Read-Phase) -ceq 'ROLLED_BACK_VERIFIED') 'Partial two-file patch yields durable rolled-back state'
Assert ((KX-Hash $script:Caddy) -ceq $pkg.hashes.caddy_original -and
 (KX-Hash $script:Launcher) -ceq $pkg.hashes.launcher_original) 'Partial two-file patch restores original hashes'
Assert ($script:stopCalls -eq ($a+1) -and $script:startCalls -eq ($b+1)) 'Partial rollback orchestrates one stop and one fake start'

Write-FixtureState 'ROLLBACK_IN_PROGRESS'
Write-Mirrors $false $true
$a=$script:stopCalls;$b=$script:startCalls
KX-PerformRecovery $pkg
Assert ((Read-Phase) -ceq 'ROLLED_BACK_VERIFIED') 'Interrupted rollback retries and reaches terminal state'
Assert ((KX-Hash $script:Caddy) -ceq $pkg.hashes.caddy_original -and
 (KX-Hash $script:Launcher) -ceq $pkg.hashes.launcher_original) 'Interrupted rollback restores other half'
Assert ($script:stopCalls -eq ($a+1) -and $script:startCalls -eq ($b+1)) 'Restarted rollback uses one bounded fake recovery path'

Write-Host '=== RESULTADO: K-X V2 REGRESION DE RECUPERACION EN CI APROBADA ===' -ForegroundColor Green
Write-Host ('ASSERTIONS PASS: '+$script:caseCount)
Write-Host 'TEMPORALES HUERFANOS, SIN REGISTRO, DUENO 443 DESCONOCIDO, COMMIT Y ROLLBACK: CUBIERTOS'
Write-Host 'SOLO FIXTURES: NO TAREAS REAL, SIN HTTPS, SIN AWS, SIN EC2'
