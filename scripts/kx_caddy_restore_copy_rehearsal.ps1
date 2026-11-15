# K-X: private offline Caddy rollback COPY rehearsal. Never modifies live config.
$ErrorActionPreference = "Stop"
$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$service = "C:\ProgramData\VehiculoIoT-KX-State\service"
$caddy = "C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestPath = Join-Path $service "install.json"
$certPath = Join-Path $root "kx_postboot_verified.json"
$kit = Join-Path $root "kx_caddy_release_preflight"
$backup = Join-Path $kit "Caddyfile.original.copy"
$report = Join-Path $kit "release_preflight.json"
$taskBackup = Join-Path $kit "VehiculoIoT-Caddy.task.xml"
$candidate = Join-Path $root "kx_caddy_offline_disabled\Caddyfile.kx.offline"
$drill = Join-Path $root "kx_caddy_rollback_rehearsal"
$simulated = Join-Path $drill "Caddyfile.restored.copy"
$adapted = Join-Path $drill "adapted.json"
$errors = Join-Path $drill "adapt.stderr"
$result = Join-Path $drill "rehearsal_results.json"
$hash = $null
$created = $false
$passed = $false
function Check([bool]$ok,[string]$label) {
 if(-not $ok){throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
Write-Host ""
Write-Host "=== K-X: ENSAYO DE ROLLBACK EN COPIA PRIVADA ===" -ForegroundColor Cyan
try {
 $p = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($file in @($root,$service,$caddy,$manifestPath,$certPath,$kit,$backup,$report,$taskBackup,$candidate)) {
  Check (Test-Path -LiteralPath $file) "Componente presente"
  Check (((Get-Item -LiteralPath $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Sin ruta redirigida"
 }
 Check ((Get-Acl $root).AreAccessRulesProtected -and (Get-Acl $kit).AreAccessRulesProtected) "Respaldos privados protegidos"
 Check (-not (Test-Path -LiteralPath $drill)) "Ensayo nuevo disponible"
 $m = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
 $v = Get-Content -LiteralPath $certPath -Raw | ConvertFrom-Json
 $b = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and $m.caddy_changed -eq $false -and
  $m.physical_control_enabled -eq $false) "K-V aislado; motores OFF"
 Check ($v.mode -eq "kx_real_boot_verified" -and $v.bootstrap_status -eq "PASS") "Boot real certificado"
 Check ($b.mode -eq "release_preflight_only_not_activated" -and
  $b.production_reload_executed -eq $false -and $b.rollback_execution_tested -eq $false) "Preflight offline intacto"
 $hash = (Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash
 Check ($hash -eq $m.original_caddy_sha256 -and
  $hash -eq $v.caddy_original_sha256 -and
  $hash -eq $b.backup_caddy_sha256 -and
  $hash -eq (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash) "Original y respaldo SHA256 iguales"
 Check ((Get-FileHash -LiteralPath $taskBackup -Algorithm SHA256).Hash -eq $b.caddy_task_xml_sha256) "Tarea Caddy respaldada intacta"
 $candidateSource = Get-Content -LiteralPath $candidate -Raw
 Check ($candidateSource.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT") -and
  $candidateSource.Contains("reverse_proxy 127.0.0.1:9444")) "Candidato con token INVALIDO, offline"
 foreach($task in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop).State -eq "Running") ("Tarea intacta: "+$task)
 }
 $k = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
 Check ($k.Count -eq 1 -and $k[0].LocalAddress -eq "127.0.0.1") "K-V sigue solo loopback"
 $executables = @(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" | Where-Object {
  -not [string]::IsNullOrWhiteSpace($_.ExecutablePath)
 } | ForEach-Object { $_.ExecutablePath } | Select-Object -Unique)
 Check ($executables.Count -eq 1 -and (Test-Path -LiteralPath $executables[0] -PathType Leaf)) "Binario Caddy identificado"
 Write-Host ""
 Write-Host "=== CREANDO ENSAYO CON ARCHIVOS NO PRODUCTIVOS ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $drill -ErrorAction Stop | Out-Null
 $created = $true
 & icacls.exe $drill /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia del ensayo retirada"
 & icacls.exe $drill /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Solo SYSTEM y Administradores"
 Check ((Get-Acl $drill).AreAccessRulesProtected) "Carpeta de ensayo protegida"
 [IO.File]::Copy($candidate,$simulated,$false)
 Check ((Get-FileHash $simulated -Algorithm SHA256).Hash -ne $hash) "Configuracion candidata copiada, original sin tocar"
 [IO.File]::Copy($backup,$simulated,$true)
 Check ((Get-FileHash $simulated -Algorithm SHA256).Hash -eq $hash) "Copia restaurada byte a byte desde backup"
 $arguments = 'adapt --config "'+$simulated+'" --adapter caddyfile'
 $proc = Start-Process -FilePath ([string]$executables[0]) -ArgumentList $arguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $adapted -RedirectStandardError $errors -ErrorAction Stop
 Check ($proc.ExitCode -eq 0) "Caddy adapt acepta copia restaurada"
 $parsed = Get-Content -LiteralPath $adapted -Raw
 Check ($parsed -match '127\.0\.0\.1:8000' -and $parsed -notmatch '127\.0\.0\.1:9444') "Solo ruta original 8000 en copia restaurada"
 Check ((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $hash) "Caddy productivo intacto"
 foreach($task in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop).State -eq "Running") ("Servicio productivo sin cambios: "+$task)
 }
 [ordered]@{
  schema_version = 1
  mode = "copy_only_restore_rehearsal_no_reload"
  timestamp_utc = [DateTime]::UtcNow.ToString("o")
  original_sha256 = $hash
  restored_copy_sha256 = (Get-FileHash $simulated -Algorithm SHA256).Hash
  caddy_adapt_exit_code = 0
  actual_service_rollback_tested = $false
  current_caddy_changed = $false
  new_public_routes_enabled = $false
  physical_control_enabled = $false
 } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $result -Encoding UTF8 -ErrorAction Stop
 Check (Test-Path -LiteralPath $result -PathType Leaf) "Evidencia de ensayo guardada"
 $passed = $true
 Write-Host ""
 Write-Host "=== RESULTADO: ROLLBACK DE ARCHIVOS EN COPIA APROBADO ===" -ForegroundColor Green
 Write-Host "RESTAURACION COPIA: HASH SHA256 PASS"
 Write-Host "CADDY ADAPT SOBRE COPIA: PASS"
 Write-Host "CADDY REAL: INTACTO"
 Write-Host "ROLLBACK DE SERVICIO REAL: NO EJECUTADO"
 Write-Host "K-V: NO PUBLICADO"
 Write-Host "CONTROL FISICO: OFF"
 Write-Host "EVIDENCIA: C:\ProgramData\VehiculoIoT-KX-Installer\kx_caddy_rollback_rehearsal\rehearsal_results.json"
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ENSAYO ROLLBACK ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO REPETIR NI MODIFICAR CADDY"
}
finally {
 if(-not $passed -and $created -and (Test-Path -LiteralPath $drill)){
  try {
   Remove-Item -LiteralPath $drill -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Ensayo incompleto retirado" -ForegroundColor Green
  } catch {
   Write-Host "NO-GO: Archivo temporal pendiente" -ForegroundColor Red
  }
 }
 if($null -ne $hash -and (Test-Path -LiteralPath $caddy)){
  if((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $hash){
   Write-Host "OK: SHA256 del Caddy real sin cambios" -ForegroundColor Green
  } else {
   Write-Host "NO-GO: Archivo Caddy real diferente" -ForegroundColor Red
  }
 }
 Write-Host "SIN RELOAD, RESTART, HTTP, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X ROLLBACK DE COPIA ===" -ForegroundColor Cyan
}
