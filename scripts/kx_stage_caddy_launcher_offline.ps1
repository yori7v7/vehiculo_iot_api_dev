# K-X: stage Caddy launcher patch ONLY in protected installer; NEVER copy to live launcher.
# Windows PowerShell 5.1. No task changes, service restart, HTTP, new listening ports or physical control.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$state="C:\ProgramData\VehiculoIoT-KX-State\service"
$manifest=Join-Path $state "install.json"
$rotation=Join-Path $root "kx_proxy_proof_rotation_result.json"
$runtime=Join-Path $root "kx_runtime_env_caddy_lab_result.json"
$liveCaddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$originalLauncher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$common="C:\vehiculo_iot_api_dev\deploy\windows\common.ps1"
$release=Join-Path $root "kx_https_public_release_v1_offline"
$candidateCaddy=Join-Path $release "Caddyfile.kx.ready.NOT_ACTIVE"
$releaseReport=Join-Path $release "preparation.json"
$stage=Join-Path $release "launcher_staging_v1"
$stageCandidate=Join-Path $stage "run_caddy.kx.pending.ps1"
$stageOriginal=Join-Path $stage "run_caddy.original.backup.ps1"
$stageReport=Join-Path $stage "launcher_stage_report.json"
$temporary=Join-Path $stage ("download_"+[guid]::NewGuid().ToString("N")+".tmp")
$launcherCommit="64e4ff0b84cc773013add82fe4e8254091a81c33"
$expectedBlob="69fc1c82fef9ea5efe8dce300f7d650c260ed0de"
$expectedOriginalSha256="873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1"
$created=$false
$passed=$false
$liveHash=$null
$caddyHash=$null

function Check([bool]$yes,[string]$label) {
 if(-not $yes){throw "NO-GO: "+$label}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function AssertNormal([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$label)
}
function Blob([string]$path) {
 $bytes=[IO.File]::ReadAllBytes($path)
 $header=[Text.Encoding]::ASCII.GetBytes("blob "+$bytes.Length+[char]0)
 $data=New-Object byte[] ($header.Length+$bytes.Length)
 [Array]::Copy($header,0,$data,0,$header.Length)
 [Array]::Copy($bytes,0,$data,$header.Length,$bytes.Length)
 $sha=[Security.Cryptography.SHA1]::Create()
 try{return [BitConverter]::ToString($sha.ComputeHash($data)).Replace("-","").ToLowerInvariant()}
 finally{$sha.Dispose()}
}
function ACLNoBroadWrite([string]$path) {
 $acl=Get-Acl -LiteralPath $path
 $mask=[int](
  [Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $rule.IdentityReference.Value -in @("S-1-1-0","S-1-5-11","S-1-5-32-545") -and
   ([int]$rule.FileSystemRights -band $mask) -ne 0){
   throw "NO-GO: permisos amplios sobre el lanzador original"
  }
 }
}
Write-Host ""
Write-Host "=== K-X: STAGING OFFLINE DE LANZADOR CADDY CON ENV PROOF ===" -ForegroundColor Cyan
try{
 $admin=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$state,$manifest,$rotation,$runtime,$liveCaddy,$originalLauncher,
  $common,$release,$candidateCaddy,$releaseReport)){
  AssertNormal $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl $root).AreAccessRulesProtected -and (Get-Acl $release).AreAccessRulesProtected) "Instalador y kit HTTPS privados"
 Check (-not (Test-Path -LiteralPath $stage)) "Directorio de staging nuevo disponible"
 $m=Get-Content -LiteralPath $manifest -Raw|ConvertFrom-Json
 $rr=Get-Content -LiteralPath $rotation -Raw|ConvertFrom-Json
 $rt=Get-Content -LiteralPath $runtime -Raw|ConvertFrom-Json
 $cr=Get-Content -LiteralPath $releaseReport -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and
  $m.physical_control_enabled -eq $false -and
  $m.caddy_changed -eq $false) "K-V aun no publicado"
 Check ($rr.mode -eq "proxy_proof_rotated_kv_loopback_only" -and
  $rr.old_proxy_rejected -eq 403 -and $rr.new_proxy_authenticated -eq 200 -and
  $rr.stale_profile_autosave_deleted -eq $true) "Token anterior revocado"
 Check ($rt.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $rt.real_proxy_proof_saved_to_file -eq $false -and
  $rt.runtime_env_placeholder_in_adapted_json -eq $true -and
  $rt.caddy_autosave_disabled_in_lab -eq $true) "Marcador runtime autenticado y sin persistir"
 Check ($cr.mode -eq "offline_public_https_candidate_never_activated" -and
  $cr.new_public_routes_enabled -eq $false -and
  $cr.production_caddy_changed -eq $false) "Kit HTTPS publico todavia offline"
 $caddyHash=(Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash
 Check ($caddyHash -eq $m.original_caddy_sha256 -and $caddyHash -eq $cr.production_sha256) "Caddy original intacto"
 Check ((Get-FileHash -LiteralPath $candidateCaddy -Algorithm SHA256).Hash -eq $cr.candidate_sha256) "Candidato Caddy offline integro"
 $liveHash=(Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash
 Check ($liveHash -eq $expectedOriginalSha256) "Lanzador de produccion SHA256 exacto"
 ACLNoBroadWrite $originalLauncher
 ACLNoBroadWrite (Split-Path -Parent $originalLauncher)
 Check ((Get-FileHash -LiteralPath $common -Algorithm SHA256).Hash.Length -eq 64) "Helper comun existente y verificado"
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 Check ($task.State -eq "Running" -and @($task.Actions).Count -eq 1) "Tarea de Caddy intacta"
 Check (([string]$task.Actions[0].Arguments).Contains($originalLauncher)) "Tarea sigue apuntando al lanzador original"
 foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop).State -eq "Running") ("Servicio en ejecucion: "+$n)
 }
 Check (@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue).Count -eq 1) "K-V loopback sigue activo"
 Check (@(Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "HTTPS original sigue activo"

 Write-Host ""
 Write-Host "=== DESCARGANDO CANDIDATO DE LANZADOR EN KIT PRIVADO ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $stage -ErrorAction Stop|Out-Null
 $created=$true
 & icacls.exe $stage /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia del staging retirada"
 & icacls.exe $stage /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Staging solo SYSTEM/Administradores"
 Check ((Get-Acl -LiteralPath $stage).AreAccessRulesProtected) "Staging protegido"
 [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
 $url="https://raw.githubusercontent.com/yori7v7/vehiculo_iot_api_dev/"+$launcherCommit+"/scripts/kx_run_caddy_launcher_candidate_not_active.ps1"
 Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $temporary -ErrorAction Stop
 Check ((Blob $temporary) -eq $expectedBlob) "Identidad Git del candidato verificada"
 $tokens=$null;$errors=$null
 [System.Management.Automation.Language.Parser]::ParseFile(
  $temporary,[ref]$tokens,[ref]$errors)|Out-Null
 Check (@($errors).Count -eq 0) "Sintaxis PowerShell 5.1 del nuevo lanzador correcta"
 $source=Get-Content -LiteralPath $temporary -Raw
 foreach($marker in @("Get-KXValidatedVirtualProxyProof",
  "Invoke-VehicleProcess", "Set-VehicleCaddyEnvironment",
  "KX_STAGING_PROXY_PROOF", "KX_INVALID_PROOF_SERVICE_UNAVAILABLE_DO_NOT_USE",
  "ConvertFrom-Json", "config.json", "install.json", "proxy_proof",
  "Remove-Item Env:KX_STAGING_PROXY_PROOF")) {
  Check ($source.Contains($marker)) "Contrato de lanzador propuesto presente"
 }
 $privateConfig=Join-Path $state "config.json"
 AssertNormal $privateConfig "Config virtual privada"
 $secretConfig=Get-Content -LiteralPath $privateConfig -Raw | ConvertFrom-Json
 Check ($secretConfig.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  -not $source.Contains([string]$secretConfig.proxy_proof) -and
  -not $source.Contains([string]$secretConfig.admin_proof)) "Script candidato no contiene secretos"
 $secretConfig=$null

 [IO.File]::Copy($originalLauncher,$stageOriginal,$false)
 Move-Item -LiteralPath $temporary -Destination $stageCandidate -ErrorAction Stop
 Check ((Get-FileHash -LiteralPath $stageOriginal -Algorithm SHA256).Hash -eq $expectedOriginalSha256) "Copia de rollback del lanzador exacta"
 Check ((Blob $stageCandidate) -eq $expectedBlob) "Candidato copiado e integro"
 Check ((Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash -eq $liveHash) "Lanzador productivo NO modificado"
 Check ((Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $caddyHash) "Caddyfile original NO modificado"

 [ordered]@{
  schema_version=1;mode="launcher_candidate_staged_offline_not_installed"
  created_utc=[DateTime]::UtcNow.ToString("o")
  launcher_original_sha256=$liveHash
  launcher_backup_sha256=(Get-FileHash -LiteralPath $stageOriginal -Algorithm SHA256).Hash
  launcher_candidate_sha256=(Get-FileHash -LiteralPath $stageCandidate -Algorithm SHA256).Hash
  launcher_candidate_git_blob=$expectedBlob
  caddy_candidate_sha256=$cr.candidate_sha256
  caddy_original_sha256=$caddyHash
  secret_in_launcher=$false
  environment_injection_at_runtime=$true
  deny_safe_legacy_fallback_planned=$true
  launch_task_modified=$false
  launcher_active_file_modified=$false
  production_caddy_modified=$false
  kv_public_activated=$false
  physical_control_enabled=$false
 }|ConvertTo-Json -Depth 4 |Set-Content -LiteralPath $stageReport -Encoding UTF8 -ErrorAction Stop
 Check (Test-Path -LiteralPath $stageReport -PathType Leaf) "Manifest offline sin secretos guardado"
 $passed=$true
 Write-Host ""
 Write-Host "=== RESULTADO: LANZADOR K-X STAGED OFFLINE APROBADO ===" -ForegroundColor Green
 Write-Host "LANZADOR ORIGINAL: INTACTO Y RESPALDADO"
 Write-Host "LANZADOR CANDIDATO: SOLO EN KIT PRIVADO"
 Write-Host "TOKEN EN SCRIPT O MANIFIESTO: NO"
 Write-Host "CADDYFILE CANDIDATO: NO ACTIVADO"
 Write-Host "TAREAS PROGRAMADAS: SIN CAMBIOS"
 Write-Host "SIGUIENTE: PRUEBA DE ARRANQUE Y ROLLBACK EN AISLAMIENTO ANTES DE PRODUCCION"
 Write-Host "CONTROL FISICO: OFF"
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO STAGING LANZADOR ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "MENSAJE DE EXCEPCION OMITIDO; NO ACTIVAR HTTPS K-V"
}
finally{
 if($created -and -not $passed -and (Test-Path -LiteralPath $stage)){
  try{Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Staging incompleto limpiado" -ForegroundColor Green
  }catch{Write-Host "NO-GO: Staging incompleto no pudo limpiarse" -ForegroundColor Red}
 }
 if($null -ne $liveHash -and (Test-Path -LiteralPath $originalLauncher)){
  if((Get-FileHash -LiteralPath $originalLauncher -Algorithm SHA256).Hash -eq $liveHash){
   Write-Host "OK: Lanzador original sigue intacto" -ForegroundColor Green
  }else{Write-Host "NO-GO: Lanzador original con hash distinto" -ForegroundColor Red}
 }
 if($null -ne $caddyHash -and (Test-Path -LiteralPath $liveCaddy)){
  if((Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $caddyHash){
   Write-Host "OK: Caddy original sigue intacto" -ForegroundColor Green
  }else{Write-Host "NO-GO: Caddy original con hash distinto" -ForegroundColor Red}
 }
 Write-Host "SIN RELOAD, RESTART, POST, NUEVOS PUERTOS, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X STAGING LANZADOR ===" -ForegroundColor Cyan
}
