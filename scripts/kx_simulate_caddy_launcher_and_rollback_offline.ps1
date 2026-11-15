# K-X: ISOLATED, NO-PRODUCTION simulation of staged Caddy launcher and NTFS rollback.
# The staged launcher runs ONLY from a disposable mirror with a stub common.ps1.
# The stub NEVER invokes Caddy or FastAPI, opens no listeners, and emits no secrets.
# Test real config read in memory; user and production tasks/config remain untouched.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$state="C:\ProgramData\VehiculoIoT-KX-State\service"
$kit=Join-Path $root "kx_https_public_release_v1_offline"
$stage=Join-Path $kit "launcher_staging_v1"
$stageReport=Join-Path $stage "launcher_stage_report.json"
$kitReport=Join-Path $kit "preparation.json"
$rotationReport=Join-Path $root "kx_proxy_proof_rotation_result.json"
$runtimeReport=Join-Path $root "kx_runtime_env_caddy_lab_result.json"
$manifestPath=Join-Path $state "install.json"
$configPath=Join-Path $state "config.json"
$originalCaddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$originalLauncher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$stageCandidate=Join-Path $stage "run_caddy.kx.pending.ps1"
$stageOriginal=Join-Path $stage "run_caddy.original.backup.ps1"
$lab=Join-Path $stage "launcher_simulation_v1"
$report=Join-Path $stage "launcher_simulation_report.json"
$mirror=Join-Path $lab "mirror\deploy\windows"
$mirrorLauncher=Join-Path $mirror "run_caddy.ps1"
$mockCommon=Join-Path $mirror "common.ps1"
$psExe=Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$expectedOriginalHash="873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1"
$originalHash=$null
$caddyHash=$null
$secret=$null
$config=$null
$labCreated=$false
$passed=$false
$clean=$true
$phase="PREFLIGHT"
$savedMock=[Environment]::GetEnvironmentVariable("KX_MOCK_CASE","Process")
$previousProof=[Environment]::GetEnvironmentVariable("KX_STAGING_PROXY_PROOF","Process")
$validOutput=$null
$deniedOutput=$null

function Check([bool]$good,[string]$label){
 if(-not $good){throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function AssertNormal([string]$p,[string]$label){
 Check (Test-Path -LiteralPath $p) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $p -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Ruta normal: "+$label)
}
function Listen([int]$port){return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)}
function Test-SimulatedRun([string]$testCase,[string]$expectedLine){
 [Environment]::SetEnvironmentVariable("KX_MOCK_CASE",$testCase,"Process")
 try{
  $output=@(& $psExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $mirrorLauncher -StateDirectory "C:\ProgramData\VehiculoIoT" 2>&1)
  $exitCode=$LASTEXITCODE
  $body=($output|ForEach-Object {[string]$_}) -join [Environment]::NewLine
  Check ($exitCode -eq 0) ("Child powershell virtual returns 0: "+$testCase)
  Check (-not $body.Contains($secret)) ("No secret in child output: "+$testCase)
  Check ($body.Contains($expectedLine)) ("Stub captured expected status: "+$testCase)
  Check ($body -notmatch "STUB_(?:VALID|DENIED)_PROOF=YES.*STUB_(?:VALID|DENIED)_PROOF=YES") ("No duplicate launches: "+$testCase)
  $output=$null;$body=$null
 } finally {
  [Environment]::SetEnvironmentVariable("KX_MOCK_CASE",$savedMock,"Process")
 }
}

Write-Host ""
Write-Host "=== K-X: ENSAYO AISLADO DEL LANZADOR CADDY Y ROLLBACK ===" -ForegroundColor Cyan
try{
 $admin=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$state,$kit,$stage,$stageReport,$kitReport,$rotationReport,
  $runtimeReport,$manifestPath,$configPath,$originalCaddy,$originalLauncher,
  $stageCandidate,$stageOriginal,$psExe)){
  AssertNormal $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $kit).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $stage).AreAccessRulesProtected) "Kit y staging privados"
 Check (-not (Test-Path -LiteralPath $lab)) "Simulacion nueva disponible"
 Check (-not (Test-Path -LiteralPath $report)) "Informe de simulacion nuevo disponible"
 Check ([string]::IsNullOrEmpty($previousProof)) "Variable de token ausente de consola Administrador"
 Check ([string]::IsNullOrEmpty($savedMock)) "Sin modo mock preexistente"

 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $r=Get-Content -LiteralPath $rotationReport -Raw|ConvertFrom-Json
 $v=Get-Content -LiteralPath $runtimeReport -Raw|ConvertFrom-Json
 $sr=Get-Content -LiteralPath $stageReport -Raw|ConvertFrom-Json
 $kr=Get-Content -LiteralPath $kitReport -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and
  $m.caddy_changed -eq $false -and $m.physical_control_enabled -eq $false) "K-V virtual sin publicar"
 Check ($r.mode -eq "proxy_proof_rotated_kv_loopback_only" -and
  $r.old_proxy_rejected -eq 403 -and $r.new_proxy_authenticated -eq 200 -and
  $r.stale_profile_autosave_deleted -eq $true) "Rotacion de token certificada"
 Check ($v.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $v.real_proxy_proof_saved_to_file -eq $false -and
  $v.runtime_env_placeholder_in_adapted_json -eq $true) "Prueba Caddy local aprobada"
 Check ($kr.mode -eq "offline_public_https_candidate_never_activated" -and
  $kr.new_public_routes_enabled -eq $false -and $kr.production_caddy_changed -eq $false) "Caddyfile candidato inactivo"
 Check ($sr.mode -eq "launcher_candidate_staged_offline_not_installed" -and
  $sr.launcher_active_file_modified -eq $false -and
  $sr.launch_task_modified -eq $false) "Lanzador candidato no instalado"
 $originalHash=(Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash
 $caddyHash=(Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash
 Check ($originalHash -eq $expectedOriginalHash -and
  $originalHash -eq $sr.launcher_original_sha256 -and
  $originalHash -eq (Get-FileHash -LiteralPath $stageOriginal -Algorithm SHA256).Hash) "Lanzador original y respaldo coinciden"
 Check ((Get-FileHash -LiteralPath $stageCandidate -Algorithm SHA256).Hash -eq
  $sr.launcher_candidate_sha256) "Lanzador candidato coincide con staging"
 Check ($caddyHash -eq $m.original_caddy_sha256 -and
  $caddyHash -eq $kr.production_sha256) "Caddy publico intacto"
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 Check ($task.State -eq "Running" -and @($task.Actions).Count -eq 1 -and
  ([string]$task.Actions[0].Arguments).Contains($originalLauncher)) "Tarea Caddy original inalterada"
 foreach($name in @("VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea funcionando: "+$name)
 }
 Check (@(Listen 9481).Count -eq 0) "Sin Caddy de laboratorio"
 Check (@(Listen 443).Count -gt 0) "Caddy productivo 443 escucha"
 $kv=@(Listen 9444)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V loopback 9444"
 $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
 Check ($config.mode -eq "virtual_loopback_only" -and
  $config.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$') "Credencial K-V valida, no mostrar"
 $secret=[string]$config.proxy_proof
 Check (-not (Get-Content -LiteralPath $stageCandidate -Raw).Contains($secret)) "Candidato sin token literal"

 Write-Host ""
 Write-Host "=== PREPARANDO ESPEJO DE POWERHELL CON STUB, SIN CADDY ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $lab -ErrorAction Stop | Out-Null
 $labCreated=$true
 & icacls.exe $lab /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia quitada"
 & icacls.exe $lab /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Lab solo SYSTEM/Administradores"
 Check ((Get-Acl -LiteralPath $lab).AreAccessRulesProtected) "ACL de espejo privada"
 New-Item -ItemType Directory -Path $mirror -Force -ErrorAction Stop | Out-Null
 [IO.File]::Copy($stageCandidate,$mirrorLauncher,$false)
 Check ((Get-FileHash -LiteralPath $mirrorLauncher -Algorithm SHA256).Hash -eq
  $sr.launcher_candidate_sha256) "Candidato copiado al espejo, no a produccion"

 $mockCode=@'
# MOCK common.ps1: strictly no Start-Process, no network or task changes.
function Get-VehicleStateDirectory {
 param([string]$StateDirectory)
 return 'C:\ProgramData\VehiculoIoT'
}
function Get-VehicleConfiguration {
 param([string]$StateDirectory)
 return [pscustomobject]@{
  caddyfile_path='C:\ProgramData\VehiculoIoT\Caddyfile'
  caddy_path='C:\ProgramData\VehiculoIoT\bin\caddy.exe'
 }
}
function Set-VehicleCaddyEnvironment {
 param([string]$StateDirectory)
 # Intentionally NO-OP: environment is inspected but Caddy never started.
}
function Get-Acl {
 param([string]$LiteralPath)
 if($env:KX_MOCK_CASE -ceq 'DENY_ACL' -and
  $LiteralPath -ceq 'C:\ProgramData\VehiculoIoT-KX-State\service\config.json') {
  throw 'MOCK_ACL_DENIAL'
 }
 return Microsoft.PowerShell.Security\Get-Acl -LiteralPath $LiteralPath
}
function Invoke-VehicleProcess {
 param([string]$StateDirectory,[string]$Component,
       [string]$Executable,[string[]]$Arguments)
 if($Component -cne 'caddy' -or $Arguments.Count -lt 5 -or
  $Arguments[0] -cne 'run' -or
  $Arguments[1] -cne '--config') {
  Write-Output 'STUB_BAD_ARGUMENTS'
  return 25
 }
 if($env:KX_MOCK_CASE -ceq 'VALID') {
  $c=Get-Content -LiteralPath 'C:\ProgramData\VehiculoIoT-KX-State\service\config.json' -Raw | ConvertFrom-Json
  if($env:KX_STAGING_PROXY_PROOF -cne [string]$c.proxy_proof) {
   Write-Output 'STUB_VALID_PROOF=NO'
   return 26
  }
  Write-Output 'STUB_VALID_PROOF=YES'
  return 0
 }
 if($env:KX_MOCK_CASE -ceq 'DENY_ACL') {
  if($env:KX_STAGING_PROXY_PROOF -cne 'KX_INVALID_PROOF_SERVICE_UNAVAILABLE_DO_NOT_USE'){
   Write-Output 'STUB_DENIED_PROOF=NO'
   return 27
  }
  Write-Output 'STUB_DENIED_PROOF=YES'
  return 0
 }
 Write-Output 'STUB_BAD_CASE'
 return 28
}
function Write-VehicleFailureLog {param([string]$StateDirectory,[string]$Component)}
'@
 Check (-not $mockCode.Contains($secret) -and
  -not $mockCode.Contains("Start-Process")) "Stub sin secretos y sin procesos reales"
 [IO.File]::WriteAllText($mockCommon,$mockCode,([Text.UTF8Encoding]::new($false)))

 Write-Host ""
 Write-Host "=== EJECUTANDO LANZADOR ESPEJO CON COMMON SIMULADO ===" -ForegroundColor Cyan
 $phase="MOCK_EXECUTION"
 Test-SimulatedRun "VALID" "STUB_VALID_PROOF=YES"
 Test-SimulatedRun "DENY_ACL" "STUB_DENIED_PROOF=YES"
 Check (@(Listen 9481).Count -eq 0) "No se inicio Caddy de laboratorio"
 Check (@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'").Count -eq 1) "Ningun Caddy adicional en ejecucion"

 Write-Host ""
 Write-Host "=== ENSAYO NTFS DE ACTIVACION Y ROLLBACK SOLO EN COPIAS ===" -ForegroundColor Cyan
 $phase="ROLLBACK_DUMMY"
 $fakeLive=Join-Path $lab "run_caddy.DUMMY_ACTIVE.ps1"
 $fakeCandidate=Join-Path $lab "run_caddy.DUMMY_TO_ACTIVATE.ps1"
 $backedOld=Join-Path $lab "run_caddy.DUMMY_OLD.backup"
 $fakeRollback=Join-Path $lab "run_caddy.DUMMY_TO_ROLLBACK.ps1"
 $afterRollback=Join-Path $lab "run_caddy.DUMMY_NEW.backup"
 [IO.File]::Copy($stageOriginal,$fakeLive,$false)
 [IO.File]::Copy($stageCandidate,$fakeCandidate,$false)
 Check ((Get-FileHash -LiteralPath $fakeLive -Algorithm SHA256).Hash -eq $originalHash) "Copia de lanzador original verificada"
 [IO.File]::Replace($fakeCandidate,$fakeLive,$backedOld)
 Check ((Get-FileHash -LiteralPath $fakeLive -Algorithm SHA256).Hash -eq $sr.launcher_candidate_sha256) "Activacion FICTICIA dentro de staging"
 Check ((Get-FileHash -LiteralPath $backedOld -Algorithm SHA256).Hash -eq $originalHash) "Backup NTFS FICTICIO conserva original"
 [IO.File]::Copy($backedOld,$fakeRollback,$false)
 [IO.File]::Replace($fakeRollback,$fakeLive,$afterRollback)
 Check ((Get-FileHash -LiteralPath $fakeLive -Algorithm SHA256).Hash -eq $originalHash) "Rollback FICTICIO restaura hash original"
 Check ((Get-FileHash -LiteralPath $afterRollback -Algorithm SHA256).Hash -eq $sr.launcher_candidate_sha256) "Backup temporal conserva candidato FICTICIO"
 Check ((Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash -eq $originalHash) "Lanzador REAL sin cambios"
 Check ((Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash -eq $caddyHash) "Caddyfile REAL sin cambios"

 $passed=$true
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ENSAYO AISLADO LANZADOR ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "MENSAJE ORIGINAL OMITIDO PARA EVITAR SECRETOS"
 Write-Host "NO CAMBIAR CADDY NI TAREAS"
}
finally{
 [Environment]::SetEnvironmentVariable("KX_MOCK_CASE",$savedMock,"Process")
 [Environment]::SetEnvironmentVariable("KX_STAGING_PROXY_PROOF",$previousProof,"Process")
 $secret=$null;$config=$null
 Write-Host ""
 Write-Host "=== LIMPIEZA DEL ESPEJO Y COPIAS ===" -ForegroundColor Cyan
 if($labCreated -and (Test-Path -LiteralPath $lab)){
  try{Remove-Item -LiteralPath $lab -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Espejo y archivos ficticios eliminados" -ForegroundColor Green
  }catch{
   $clean=$false
   Write-Host "NO-GO: Lab de espejo no eliminado" -ForegroundColor Red
  }
 }
 if($null -ne $originalHash -and (Test-Path -LiteralPath $originalLauncher)){
  if((Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash -eq $originalHash){
   Write-Host "OK: Lanzador productivo original intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Lanzador productivo modificado" -ForegroundColor Red}
 }
 if($null -ne $caddyHash -and (Test-Path -LiteralPath $originalCaddy)){
  if((Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash -eq $caddyHash){
   Write-Host "OK: Caddyfile productivo intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Caddyfile productivo modificado" -ForegroundColor Red}
 }
 if($passed -and $clean){
  try{
   [ordered]@{
    schema_version=1
    mode="isolated_launcher_and_rollback_simulation_not_production"
    utc=[DateTime]::UtcNow.ToString("o")
    real_config_read_only=$true
    valid_proof_passed_in_memory=$true
    deny_acl_mock_uses_invalid_proof=$true
    actual_caddy_process_started=$false
    fake_launcher_patch_and_rollback_passed=$true
    original_launcher_sha256=$originalHash
    production_caddy_sha256=$caddyHash
    production_launcher_changed=$false
    scheduled_tasks_changed=$false
    public_kv_route_activated=$false
    physical_control_enabled=$false
   }|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $report -Encoding UTF8 -ErrorAction Stop
   Write-Host ""
   Write-Host "=== RESULTADO: LANZADOR Y ROLLBACK AISLADOS APROBADOS ===" -ForegroundColor Green
   Write-Host "LANZADOR STUB: TOKEN CORRECTO EN MEMORIA"
   Write-Host "FALLO DE ACL SIMULADO: TOKEN INVALIDO (FAIL CLOSED)"
   Write-Host "REEMPLAZO / ROLLBACK NTFS: PASS SOLO ARCHIVOS FICTICIOS"
   Write-Host "LAB ESPEJO: ELIMINADO"
   Write-Host "CADDY REAL: NO ARRANCADO NI REINICIADO"
   Write-Host "CADDYFILE Y LANZADOR PRODUCTIVOS: INTACTOS"
   Write-Host "K-V PUBLICO: NO ACTIVADO"
   Write-Host "CONTROL FISICO: OFF"
  }catch{
   Write-Host "NO-GO: reporte de simulacion no guardado" -ForegroundColor Red
  }
 }else{
  Write-Host "=== RESULTADO: ENSAYO NO APROBADO O LIMPIEZA INCOMPLETA ===" -ForegroundColor Red
 }
 Write-Host "SIN RELOAD, RESTART, HTTP, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X SIMULACION LANZADOR ===" -ForegroundColor Cyan
}
