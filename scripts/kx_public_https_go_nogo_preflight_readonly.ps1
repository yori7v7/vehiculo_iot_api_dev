# K-X: final read-only go/no-go inventory before any real Caddy HTTPS cutover.
# Never deploy, reload, restart, stop, change ACLs, write files, print secrets or run HTTP.
# This does NOT authorize publication and does NOT test a real SYSTEM restart.
$ErrorActionPreference="Stop"
$installer="C:\ProgramData\VehiculoIoT-KX-Installer"
$state="C:\ProgramData\VehiculoIoT-KX-State\service"
$root="C:\ProgramData\VehiculoIoT"
$manifestFile=Join-Path $state "install.json"
$configFile=Join-Path $state "config.json"
$liveCaddy=Join-Path $root "Caddyfile"
$liveAuto=Join-Path $root "caddy-config\caddy\autosave.json"
$originalCaddy=Join-Path $installer "kx_caddy_release_preflight\Caddyfile.original.copy"
$originalTaskXML=Join-Path $installer "kx_caddy_release_preflight\VehiculoIoT-Caddy.task.xml"
$releaseDir=Join-Path $installer "kx_https_public_release_v1_offline"
$caddyCandidate=Join-Path $releaseDir "Caddyfile.kx.ready.NOT_ACTIVE"
$adapted=Join-Path $releaseDir "candidate-adapted.json"
$releaseReport=Join-Path $releaseDir "preparation.json"
$stage=Join-Path $releaseDir "launcher_staging_v1"
$stageCandidate=Join-Path $stage "run_caddy.kx.pending.ps1"
$stageOriginal=Join-Path $stage "run_caddy.original.backup.ps1"
$stageReport=Join-Path $stage "launcher_stage_report.json"
$simReport=Join-Path $stage "launcher_simulation_report.json"
$rotationReport=Join-Path $installer "kx_proxy_proof_rotation_result.json"
$runtimeReport=Join-Path $installer "kx_runtime_env_caddy_lab_result.json"
$activeLauncher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$activeCommon="C:\vehiculo_iot_api_dev\deploy\windows\common.ps1"
$originalLauncherHash="873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1"
$phase="INICIO"
$secret=$null
$config=$null
$liveHash=$null
$launchHash=$null

function Check([bool]$yes,[string]$label) {
 if(-not $yes) {throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function Normal([string]$path,[string]$label) {
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$label)
}
function AllowReadFor([string]$path,[string]$sid) {
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $mask=[int][Security.AccessControl.FileSystemRights]::ReadData
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
  if($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $rule.IdentityReference.Value -eq $sid -and
   (([int]$rule.FileSystemRights -band $mask) -ne 0)) {return $true}
 }
 return $false
}
function CheckNoBroadWrite([string]$path,[string]$label) {
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $mask=[int](
  [Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
  [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
  [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 $broad=@("S-1-1-0","S-1-5-11","S-1-5-32-545")
 foreach($r in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
  if($r.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $r.IdentityReference.Value -in $broad -and
   (([int]$r.FileSystemRights -band $mask) -ne 0)) {
   throw "NO-GO: ACL amplia detectada en "+$label
  }
 }
 Write-Host ("OK: "+$label+" sin escritura amplia") -ForegroundColor Green
}
function Listeners([int]$port) {
 return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function MatchSid([uint32]$pid,[string]$sid) {
 $p=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$pid) -ErrorAction Stop
 if($null -eq $p){return $false}
 $owner=(Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop).Sid
 return $owner -eq $sid
}

Write-Host ""
Write-Host "=== K-X: PREFLIGHT GO/NO-GO HTTPS SIN CAMBIOS ===" -ForegroundColor Cyan
try{
 $self=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($self.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola Administrador"
 $phase="ARTIFACTOS"
 foreach($path in @($installer,$state,$root,$manifestFile,$configFile,
  $liveCaddy,$liveAuto,$originalCaddy,$originalTaskXML,
  $releaseDir,$caddyCandidate,$adapted,$releaseReport,
  $stage,$stageCandidate,$stageOriginal,$stageReport,$simReport,
  $rotationReport,$runtimeReport,$activeLauncher,$activeCommon)) {
  Normal $path ([IO.Path]::GetFileName($path))
 }
 foreach($path in @($installer,$state,$root,$releaseDir,$stage)){
  Check ((Get-Acl -LiteralPath $path).AreAccessRulesProtected) ("Directorio privado: "+[IO.Path]::GetFileName($path))
 }
 foreach($path in @($configFile,$caddyCandidate,$adapted,$stageCandidate,$stageOriginal)){
  CheckNoBroadWrite $path ([IO.Path]::GetFileName($path))
 }

 $phase="EVIDENCIAS"
 $manifest=Get-Content -LiteralPath $manifestFile -Raw|ConvertFrom-Json
 $rotation=Get-Content -LiteralPath $rotationReport -Raw|ConvertFrom-Json
 $runtime=Get-Content -LiteralPath $runtimeReport -Raw|ConvertFrom-Json
 $release=Get-Content -LiteralPath $releaseReport -Raw|ConvertFrom-Json
 $stageData=Get-Content -LiteralPath $stageReport -Raw|ConvertFrom-Json
 $sim=Get-Content -LiteralPath $simReport -Raw|ConvertFrom-Json
 Check ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false -and
  $manifest.dedicated_user -eq "VehIoT_KXSvc") "Manifiesto K-V original aislado"
 Check ($rotation.mode -eq "proxy_proof_rotated_kv_loopback_only" -and
  $rotation.old_proxy_rejected -eq 403 -and
  $rotation.new_proxy_authenticated -eq 200 -and
  $rotation.stale_profile_autosave_deleted -eq $true -and
  $rotation.old_ntfs_backup_deleted_before_restart -eq $true) "Rotacion certificada 403/200"
 Check ($runtime.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $runtime.real_proxy_proof_saved_to_file -eq $false -and
  $runtime.runtime_env_placeholder_in_adapted_json -eq $true -and
  $runtime.production_caddy_modified -eq $false) "Runtime K-V local validado"
 Check ($release.mode -eq "offline_public_https_candidate_never_activated" -and
  $release.production_caddy_changed -eq $false -and
  $release.new_public_routes_enabled -eq $false -and
  $release.caddy_persist_config_disabled -eq $true) "Candidato HTTPS inactivo"
 Check ($stageData.mode -eq "launcher_candidate_staged_offline_not_installed" -and
  $stageData.launch_task_modified -eq $false -and
  $stageData.launcher_active_file_modified -eq $false -and
  $stageData.secret_in_launcher -eq $false) "Lanzador candidato NO instalado"
 Check ($sim.mode -eq "isolated_launcher_and_rollback_simulation_not_production" -and
  $sim.valid_proof_passed_in_memory -eq $true -and
  $sim.deny_acl_mock_uses_invalid_proof -eq $true -and
  $sim.fake_launcher_patch_and_rollback_passed -eq $true -and
  $sim.actual_caddy_process_started -eq $false -and
  $sim.production_launcher_changed -eq $false) "Simulacion aislada aprobada"

 $phase="HASHES"
 $liveHash=(Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash
 $launchHash=(Get-FileHash -LiteralPath $activeLauncher -Algorithm SHA256).Hash
 Check ($liveHash -eq $manifest.original_caddy_sha256 -and
  $liveHash -eq $release.production_sha256 -and
  $liveHash -eq $sim.production_caddy_sha256 -and
  $liveHash -eq (Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash) "Hash Caddy productivo corresponde respaldo"
 Check ($launchHash -eq $originalLauncherHash -and
  $launchHash -eq $stageData.launcher_original_sha256 -and
  $launchHash -eq $sim.original_launcher_sha256 -and
  $launchHash -eq (Get-FileHash -LiteralPath $stageOriginal -Algorithm SHA256).Hash) "Hash lanzador productivo corresponde rollback"
 Check ((Get-FileHash -LiteralPath $caddyCandidate -Algorithm SHA256).Hash -eq
  $release.candidate_sha256) "Caddyfile offline exacto"
 Check ((Get-FileHash -LiteralPath $adapted -Algorithm SHA256).Hash -eq
  $release.adapted_sha256) "JSON adaptado offline exacto"
 Check ((Get-FileHash -LiteralPath $stageCandidate -Algorithm SHA256).Hash -eq
  $stageData.launcher_candidate_sha256) "Lanzador staged SHA256 exacto"

 $phase="SECRETOS"
 $config=Get-Content -LiteralPath $configFile -Raw|ConvertFrom-Json
 Check ($config.mode -eq "virtual_loopback_only" -and
  $config.bind_host -eq "127.0.0.1" -and
  [int]$config.bind_port -eq 9444 -and
  $config.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  $config.admin_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  $config.admin_proof -cne $config.proxy_proof) "Config K-V con secretos distintos, no mostrados"
 $secret=[string]$config.proxy_proof
 Check (AllowReadFor $configFile "S-1-5-18") "ACL de config permite lectura a SYSTEM (no equivale a prueba de acceso real)"
 Check (AllowReadFor $configFile ([string]$manifest.dedicated_sid)) "ACL de config permite lectura a cuenta K-V"
 foreach($p in @($liveAuto,$caddyCandidate,$adapted,$stageCandidate,$stageReport,$simReport)){
  Check (-not ([IO.File]::ReadAllText($p)).Contains($secret)) ("Sin token en "+[IO.Path]::GetFileName($p))
 }
 Check (-not (Test-Path -LiteralPath (Join-Path $env:APPDATA "Caddy\autosave.json"))) "Autosave obsoleto de Admin ausente"
 $candidateText=[IO.File]::ReadAllText($caddyCandidate)
 $adaptedText=[IO.File]::ReadAllText($adapted)
 $launcherText=[IO.File]::ReadAllText($stageCandidate)
 Check ($candidateText.Contains("{env.KX_STAGING_PROXY_PROOF}") -and
  $adaptedText.Contains("{env.KX_STAGING_PROXY_PROOF}") -and
  $launcherText.Contains("Get-KXValidatedVirtualProxyProof")) "Marcador runtime y lector privado presentes"
 Check ($candidateText.Contains(" persist_config off") -and
  $candidateText.Contains(" admin 127.0.0.1:2019") -and
  $candidateText.Contains("reverse_proxy 127.0.0.1:8000") -and
  $candidateText.Contains("reverse_proxy 127.0.0.1:9444")) "Legado conservado, K-V por ruta restringida"
 Check ($adaptedText -match '"persist"\s*:\s*false') "Persistencia Caddy candidato deshabilitada"
 $secret=$null;$config=$null

 $phase="TAREAS_Y_PROCESOS"
 foreach($n in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop).State -eq "Running") ("Tarea sin cambio: "+$n)
 }
 $boot=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual-Boot" -ErrorAction Stop
 Check ($boot.State -ne "Disabled") "Bootstrap K-V habilitado"
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 Check (@($task.Actions).Count -eq 1 -and
  ([string]$task.Actions[0].Arguments).Contains($activeLauncher)) "Tarea Caddy sigue apuntando al lanzador original"
 $https=@(Listeners 443)
 Check ($https.Count -ge 1) "HTTPS original 443 activo"
 Check (@($https | Select-Object -ExpandProperty OwningProcess -Unique).Count -eq 1) "Unico proceso propietario HTTPS"
 $caddyPID=[uint32]$https[0].OwningProcess
 Check (MatchSid $caddyPID "S-1-5-18") "Propietario de HTTPS Caddy es SYSTEM"
 $process=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$caddyPID) -ErrorAction Stop
 Check ([IO.Path]::GetFileName([string]$process.ExecutablePath) -eq "caddy.exe") "HTTPS proviene de caddy.exe"
 Check (-not (([string]$process.CommandLine) -match '(?i)--resume')) "Proceso Caddy no usa --resume"
 $kv=@(Listeners 9444)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V 9444 solo loopback"
 Check (MatchSid ([uint32]$kv[0].OwningProcess) ([string]$manifest.dedicated_sid)) "K-V bajo usuario dedicado"
 $legacy=@(Listeners 8000)
 Check ($legacy.Count -ge 1 -and @($legacy | Where-Object {$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "FastAPI 8000 solo loopback"
 Check (@(Listeners 9481).Count -eq 0) "Puerto de laboratorio 9481 libre"
 Check (@(Listeners 2019 | Where-Object {$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "Admin Caddy 2019 sin escucha externa"
 Check ((Get-FileHash -LiteralPath $activeLauncher -Algorithm SHA256).Hash -eq $launchHash -and
  (Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $liveHash) "Produccion sin cambios durante preflight"

 Write-Host ""
 Write-Host "=== RESULTADO: PREFLIGHT READINESS OFFLINE APROBADO ===" -ForegroundColor Green
 Write-Host "EVIDENCIAS: ROTACION, RUNTIME, CANDIDATO, STAGING, SIMULACION VERIFICADAS"
 Write-Host "SYSTEM: ACL DE LECTURA VALIDADA, EJECUCION REAL NO PROBADA"
 Write-Host "HTTPS 443: SOLO CADDY ORIGINAL"
 Write-Host "TOKEN: SIN PERSISTENCIA EN ARCHIVOS EXAMINADOS"
 Write-Host "K-V PUBLICO: NO ACTIVADO"
 Write-Host "ROLLBACK REAL CON SERVICIO SYSTEM: AUN NO PROBADO"
 Write-Host "CADDYFILE/LANZADOR/TAREAS: NO MODIFICADOS"
 Write-Host "CONTROL FISICO: OFF"
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO PREFLIGHT READINESS ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "DETALLE DE ERROR OMITIDO, NO IMPRIMIR DATOS SENSIBLES"
 Write-Host "NO PUBLICAR, NO REINICIAR CADDY"
}
finally{
 $secret=$null;$config=$null
 Write-Host "SOLO LECTURA: SIN WRITES, RELOAD, RESTART, HTTP, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X PREFLIGHT GO/NO-GO ===" -ForegroundColor Cyan
}
