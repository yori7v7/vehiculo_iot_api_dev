# K-X: Test the exact staged Caddy proof reader under real NT AUTHORITY\SYSTEM.
# Temporary one-shot task ONLY. No Caddy/legacy/K-V task changes, no HTTP, no motors.
# The worker & child scripts write only pass/fail metadata. Secret never on command line or disk.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$release=Join-Path $root "kx_https_public_release_v1_offline"
$stage=Join-Path $release "launcher_staging_v1"
$stageReport=Join-Path $stage "launcher_stage_report.json"
$simReport=Join-Path $stage "launcher_simulation_report.json"
$launcher=Join-Path $stage "run_caddy.kx.pending.ps1"
$activeLauncher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$liveCaddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestPath="C:\ProgramData\VehiculoIoT-KX-State\service\install.json"
$configPath="C:\ProgramData\VehiculoIoT-KX-State\service\config.json"
$psExe=Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$proofReport=Join-Path $stage "system_proof_dryrun_result.json"
$lab=Join-Path $stage "system_proof_dryrun_lab"
$workerFile=Join-Path $lab "system_worker.ps1"
$childFile=Join-Path $lab "inheritance_child.ps1"
$workerResult=Join-Path $lab "worker_result.json"
$taskName="VehiculoIoT-KX-SystemDryRun-"+[guid]::NewGuid().ToString("N")
$taskCreated=$false
$labCreated=$false
$passed=$false
$clean=$true
$caddyHash=$null
$launcherHash=$null
$configHash=$null
$phase="PREFLIGHT"

function Check([bool]$ok,[string]$label){
 if(-not $ok){throw "NO-GO: "+$label}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function AssertNormal([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$label)
}
function Listeners([int]$port){return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)}
Write-Host ""
Write-Host "=== K-X: TEST SYSTEM REAL CON PROXY PROOF SOLO MEMORIA ===" -ForegroundColor Cyan
try{
 $current=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$release,$stage,$stageReport,$simReport,$launcher,
  $activeLauncher,$liveCaddy,$manifestPath,$configPath,$psExe)){
  AssertNormal $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $stage).AreAccessRulesProtected) "Kit y staging privados"
 Check (-not (Test-Path -LiteralPath $lab)) "Laboratorio SYSTEM nuevo disponible"
 Check (-not (Test-Path -LiteralPath $proofReport)) "Reporte SYSTEM nuevo disponible"
 Check ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue)) "Nombre de tarea temporal nuevo"
 Check ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable(
  "KX_STAGING_PROXY_PROOF","Process"))) "Token ausente del entorno de Administrador"

 $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $stageData=Get-Content -LiteralPath $stageReport -Raw|ConvertFrom-Json
 $sim=Get-Content -LiteralPath $simReport -Raw|ConvertFrom-Json
 Check ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false) "K-V permanece virtual y no publicado"
 Check ($stageData.mode -eq "launcher_candidate_staged_offline_not_installed" -and
  $stageData.launcher_active_file_modified -eq $false -and
  $stageData.launch_task_modified -eq $false) "Candidato todavia no instalado"
 Check ($sim.mode -eq "isolated_launcher_and_rollback_simulation_not_production" -and
  $sim.valid_proof_passed_in_memory -eq $true -and
  $sim.deny_acl_mock_uses_invalid_proof -eq $true -and
  $sim.fake_launcher_patch_and_rollback_passed -eq $true) "Simulacion anterior validada"
 Check ((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq
  $stageData.launcher_candidate_sha256) "Lector de prueba tiene hash exacto"
 $launcherHash=(Get-FileHash -LiteralPath $activeLauncher -Algorithm SHA256).Hash
 $caddyHash=(Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash
 $configHash=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
 Check ($launcherHash -eq $stageData.launcher_original_sha256 -and
  $caddyHash -eq $manifest.original_caddy_sha256) "Lanzador y Caddy de produccion intactos"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea original: "+$name)
 }
 $kv=@(Listeners 9444)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V solo loopback"
 Check (@(Listeners 443).Count -gt 0) "HTTPS original 443 activo"
 Check (@(Listeners 9481).Count -eq 0) "Sin laboratorio Caddy activo"

 Write-Host ""
 Write-Host "=== CREANDO SCRIPTS TEMPORALES SIN CREDENCIALES ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $lab -ErrorAction Stop|Out-Null
 $labCreated=$true
 & icacls.exe $lab /inheritance:r |Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia de laboratorio retirada"
 & icacls.exe $lab /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' |Out-Null
 Check ($LASTEXITCODE -eq 0) "Laboratorio solo SYSTEM y Administradores"
 Check ((Get-Acl -LiteralPath $lab).AreAccessRulesProtected) "Directorio temporal con ACL privada"

 $workerSource=@'
# K-X SYSTEM worker. Only the named safe function is extracted from the staged script.
param([string]$Candidate,[string]$CandidateHash,[string]$Child,[string]$Output)
$ErrorActionPreference="Stop"
$phase="IDENTITY"
$proof=$null
$baseline=$null
$caddyBaseline=$null
$childProcess=$null
$ok=$false
try {
 $id=[Security.Principal.WindowsIdentity]::GetCurrent()
 if($id.User.Value -cne "S-1-5-18"){throw "IDENTITY"}
 $phase="VALIDATE"
 $labDir=Split-Path -Parent $Output
 if(-not $Child.StartsWith($labDir+"\",[StringComparison]::OrdinalIgnoreCase)){throw "PATH"}
 if(-not $Candidate.StartsWith("C:\ProgramData\VehiculoIoT-KX-Installer\",[StringComparison]::OrdinalIgnoreCase)){throw "PATH"}
 if((Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash -cne $CandidateHash){throw "HASH"}
 $baseline=(Get-FileHash -LiteralPath "C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1" -Algorithm SHA256).Hash
 $caddyBaseline=(Get-FileHash -LiteralPath "C:\ProgramData\VehiculoIoT\Caddyfile" -Algorithm SHA256).Hash
 $tokens=$null;$errors=$null
 $ast=[System.Management.Automation.Language.Parser]::ParseFile($Candidate,[ref]$tokens,[ref]$errors)
 if(@($errors).Count -gt 0){throw "PARSER"}
 $definitions=@($ast.FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
   $node.Name -ceq "Get-KXValidatedVirtualProxyProof"
 },$true))
 if($definitions.Count -ne 1){throw "FUNCTION"}
 # This is EXACTLY the function from the pinned launcher, not its top-level startup path.
 . ([ScriptBlock]::Create($definitions[0].Extent.Text))
 $phase="PROOF_READ"
 $proof=Get-KXValidatedVirtualProxyProof
 if($proof -cnotmatch '^[A-Za-z0-9_-]{64}$'){throw "PROOF"}
 if(-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable(
  "KX_STAGING_PROXY_PROOF","Process"))){throw "ENV_PREEXISTING"}
 $phase="CHILD_INHERITANCE"
 $env:KX_STAGING_PROXY_PROOF=$proof
 $exe=Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
 $args='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$Child+'"'
 $childProcess=Start-Process -FilePath $exe -ArgumentList $args -PassThru -Wait -ErrorAction Stop
 if($childProcess.ExitCode -ne 0){throw "CHILD"}
 $phase="POSTCHECK"
 if((Get-FileHash -LiteralPath "C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1" -Algorithm SHA256).Hash -cne $baseline -or
  (Get-FileHash -LiteralPath "C:\ProgramData\VehiculoIoT\Caddyfile" -Algorithm SHA256).Hash -cne $caddyBaseline){
  throw "LIVE_HASH"
 }
 $ok=$true
}
catch {
 # Do not print exception messages or secrets, including from child process.
 $ok=$false
}
finally {
 Remove-Item Env:KX_STAGING_PROXY_PROOF -ErrorAction SilentlyContinue
 $proof=$null
 $result=[ordered]@{
  schema_version=1
  mode="system_real_identity_launcher_proof_dryrun"
  status=$(if($ok){"PASS"}else{"FAIL"})
  phase=$phase
  system_identity_checked=$true
  exact_launcher_function_loaded=$true
  env_child_verified=$ok
  no_real_caddy_started=$true
  production_files_unchanged=$ok
  physical_control_enabled=$false
 }
 try{
  [IO.File]::WriteAllText($Output,($result|ConvertTo-Json -Depth 4),
   ([Text.UTF8Encoding]::new($false)))
 }catch{}
}
if($ok){exit 0}else{exit 30}
'@

 $childSource=@'
# Child runs as SYSTEM, with a temporary environment-only proxy proof.
$ErrorActionPreference="Stop"
try {
 $id=[Security.Principal.WindowsIdentity]::GetCurrent()
 if($id.User.Value -cne "S-1-5-18"){exit 21}
 $envProof=[Environment]::GetEnvironmentVariable("KX_STAGING_PROXY_PROOF","Process")
 if([string]::IsNullOrWhiteSpace($envProof)){exit 22}
 $path="C:\ProgramData\VehiculoIoT-KX-State\service\config.json"
 $config=Get-Content -LiteralPath $path -Raw -ErrorAction Stop|ConvertFrom-Json
 if($config.mode -cne "virtual_loopback_only" -or
   $config.proxy_proof -cne $envProof -or
   $envProof -cnotmatch '^[A-Za-z0-9_-]{64}$'){exit 23}
 $envProof=$null;$config=$null
 exit 0
}catch{exit 24}
'@
 Check (-not $workerSource.Contains("caddy run") -and
  -not $workerSource.Contains("caddy reload") -and
  -not $childSource.Contains("Start-Process")) "Scripts temporales no inician Caddy"
 foreach($code in @($workerSource,$childSource)){
  $tok=$null;$err=$null
  $null=[System.Management.Automation.Language.Parser]::ParseInput($code,[ref]$tok,[ref]$err)
  Check (@($err).Count -eq 0) "Subscript PowerShell 5.1 valido"
 }
 [IO.File]::WriteAllText($workerFile,$workerSource,([Text.UTF8Encoding]::new($false)))
 [IO.File]::WriteAllText($childFile,$childSource,([Text.UTF8Encoding]::new($false)))
 Check (-not ([IO.File]::ReadAllText($workerFile)).Contains("PROXY_PROOF_REAL_TOKEN_VALUE")) "No existen valores reales de token en el worker"

 Write-Host ""
 Write-Host "=== INICIANDO UNA TAREA TEMPORAL SISTEMA (SIN CADDY) ===" -ForegroundColor Cyan
 $phase="REGISTER_TEMP_TASK"
 $argsString='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+
  $workerFile+'" -Candidate "'+$launcher+'" -CandidateHash "'+
  $stageData.launcher_candidate_sha256+'" -Child "'+$childFile+'" -Output "'+$workerResult+'"'
 $action=New-ScheduledTaskAction -Execute $psExe -Argument $argsString
 $taskPrincipal=New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
 Register-ScheduledTask -TaskPath "\" -TaskName $taskName -Action $action -Principal $taskPrincipal -Settings $settings -ErrorAction Stop|Out-Null
 $taskCreated=$true
 $task=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
 Check (@($task.Actions).Count -eq 1 -and
  ([string]$task.Actions[0].Arguments).Contains($workerFile) -and
  ([string]$task.Principal.UserId -match '^(SYSTEM|S-1-5-18|NT AUTHORITY\\SYSTEM)$')) "Tarea aislada ejecutara el worker como SYSTEM"
 Start-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
 $phase="WAIT_SYSTEM_REPORT"
 $finished=$false
 for($i=0;$i -lt 120;$i++){
  Start-Sleep -Milliseconds 250
  $task=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  if((Test-Path -LiteralPath $workerResult -PathType Leaf) -and
   $task.State -ne "Running"){
   $finished=$true
   break
  }
 }
 Check ($finished) "Tarea SYSTEM termino y emitio reporte"
 $info=Get-ScheduledTaskInfo -TaskPath "\" -TaskName $taskName -ErrorAction Stop
 Check ($info.LastTaskResult -eq 0) "SYSTEM proceso finalizo con exit code 0"
 $result=Get-Content -LiteralPath $workerResult -Raw|ConvertFrom-Json
 Check ($result.mode -eq "system_real_identity_launcher_proof_dryrun" -and
  $result.status -eq "PASS" -and
  $result.env_child_verified -eq $true -and
  $result.production_files_unchanged -eq $true) "SYSTEM valido lector real y entorno heredado"
 $phase="PRODUCTION_POSTCHECK"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea productiva sin cambios: "+$name)
 }
 Check ((Get-FileHash -LiteralPath $activeLauncher -Algorithm SHA256).Hash -eq $launcherHash -and
  (Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $caddyHash -and
  (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $configHash) "Caddy, lanzador y secretos productivos intactos"
 Check (@(Listeners 9481).Count -eq 0) "No se inicio servidor Caddy temporal"
 $passed=$true
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO SYSTEM DRYRUN ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "DETALLES Y SECRETOS OMITIDOS"
 Write-Host "NO REPETIR, NO PUBLICAR CADDY"
}
finally {
 Write-Host ""
 Write-Host "=== LIMPIEZA DE TAREA UNICA Y LABORATORIO ===" -ForegroundColor Cyan
 if($taskCreated) {
  try {
   $tempTask=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
   if($tempTask.State -eq "Running"){
    Stop-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
   }
   Unregister-ScheduledTask -TaskPath "\" -TaskName $taskName -Confirm:$false -ErrorAction Stop
   Check ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue)) "Tarea temporal SYSTEM eliminada"
  }catch{
   $clean=$false
   Write-Host "NO-GO: no se pudo eliminar tarea temporal, no repetir" -ForegroundColor Red
  }
 }
 if($labCreated -and (Test-Path -LiteralPath $lab)) {
  try{
   Remove-Item -LiteralPath $lab -Force -Recurse -ErrorAction Stop
   Write-Host "OK: scripts temporales y reporte interno eliminados" -ForegroundColor Green
  }catch{
   $clean=$false
   Write-Host "NO-GO: laboratorio temporal no eliminado" -ForegroundColor Red
  }
 }
 if($null -ne $launcherHash -and (Test-Path -LiteralPath $activeLauncher)) {
  if((Get-FileHash -LiteralPath $activeLauncher -Algorithm SHA256).Hash -eq $launcherHash){
   Write-Host "OK: lanzador real original intacto" -ForegroundColor Green
  }else{
   $clean=$false
   Write-Host "NO-GO: lanzador real hash cambiado" -ForegroundColor Red
  }
 }
 if($null -ne $caddyHash -and (Test-Path -LiteralPath $liveCaddy)) {
  if((Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $caddyHash){
   Write-Host "OK: Caddyfile real original intacto" -ForegroundColor Green
  }else{
   $clean=$false
   Write-Host "NO-GO: Caddyfile real hash cambiado" -ForegroundColor Red
  }
 }
 if($passed -and $clean) {
  try{
   [ordered]@{
    schema_version=1
    mode="system_real_identity_launcher_proof_dryrun_not_activated"
    tested_utc=[DateTime]::UtcNow.ToString("o")
    exact_candidate_function_under_system=$true
    proof_delivered_only_by_environment=$true
    child_process_inherited_proof=$true
    temporary_system_task_removed=$true
    private_scripts_removed=$true
    caddy_restarted=$false
    production_caddy_modified=$false
    production_launcher_modified=$false
    kv_public_activated=$false
    physical_control_enabled=$false
   }|ConvertTo-Json -Depth 4 |Set-Content -LiteralPath $proofReport -Encoding UTF8 -ErrorAction Stop
   Write-Host ""
   Write-Host "=== RESULTADO: SYSTEM REAL DRYRUN APROBADO ===" -ForegroundColor Green
   Write-Host "CUENTA SYSTEM REAL: LECTURA Y VALIDACION K-V PASS"
   Write-Host "ENV DEL CHILD SYSTEM: TOKEN CORRECTO, SIN IMPRIMIR"
   Write-Host "TAREA SYSTEM TEMPORAL: ELIMINADA"
   Write-Host "NINGUN CADDY ADICIONAL ARRANCADO"
   Write-Host "CADDYFILE/LANZADOR/TAREAS REALES: INTACTOS"
   Write-Host "K-V PUBLICO: NO ACTIVADO"
   Write-Host "CONTROL FISICO: OFF"
  }catch{
   Write-Host "NO-GO: no se pudo guardar informe SYSTEM sin secreto" -ForegroundColor Red
  }
 }else{
  Write-Host "=== RESULTADO: SYSTEM DRYRUN NO CERTIFICADO ===" -ForegroundColor Red
 }
 Write-Host "SIN RELOAD, RESTART DE CADDY, HTTP, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X DRYRUN SYSTEM ===" -ForegroundColor Cyan
}
