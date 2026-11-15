# K-X / Release preflight (NO ACTIVA RUTAS PUBLICAS)
# Backup verificable de Caddy + definicion tarea, y pruebas GET negativas a K-V.
# PowerShell 5.1; escritura SOLO bajo instalador K-X privado; sin reload ni restart.
$ErrorActionPreference="Stop"

$installerDir="C:\ProgramData\VehiculoIoT-KX-Installer"
$serviceDir="C:\ProgramData\VehiculoIoT-KX-State\service"
$originalCaddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestPath=Join-Path $serviceDir "install.json"
$certificatePath=Join-Path $installerDir "kx_postboot_verified.json"
$offlineCandidate=Join-Path $installerDir "kx_caddy_offline_disabled\Caddyfile.kx.offline"
$kitDir=Join-Path $installerDir "kx_caddy_release_preflight"
$backupPath=Join-Path $kitDir "Caddyfile.original.copy"
$taskPath=Join-Path $kitDir "VehiculoIoT-Caddy.task.xml"
$reportPath=Join-Path $kitDir "release_preflight.json"
$created=$false
$ok=$false
$client=$null
$originalHash=$null

function Assert-KX([bool]$condition,[string]$message){
 if(-not $condition){throw ("NO-GO: "+$message)}
 Write-Host ("OK: "+$message) -ForegroundColor Green
}
function Get-Listeners([int]$port){
 return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Probe-Denial([string]$route,[int]$expected){
 $uri="http://127.0.0.1:9444"+$route
 $request=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,[Uri]$uri)
 try {
  $response=$client.SendAsync($request).GetAwaiter().GetResult()
  try {
   $actual=[int]$response.StatusCode
   Write-Host ("HTTP LOCAL K-V: "+$route+" -> "+$actual)
   Assert-KX ($actual -eq $expected) ("Respuesta denegada esperada: "+$expected)
   Assert-KX ($response.Headers.CacheControl.NoStore -eq $true) "Cache-Control no-store en respuesta"
  } finally {$response.Dispose()}
 } finally {$request.Dispose()}
}

Write-Host ""
Write-Host "=== K-X: PREFLIGHT DE ROLLBACK + RECHAZO K-V ===" -ForegroundColor Cyan
try {
 Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
 $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Assert-KX ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($path in @($installerDir,$serviceDir,$originalCaddy,$manifestPath,$certificatePath,$offlineCandidate)){
  Assert-KX (Test-Path -LiteralPath $path) "Componente requerido presente"
  Assert-KX (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Sin ruta redirigida"
 }
 Assert-KX ((Get-Acl -LiteralPath $installerDir).AreAccessRulesProtected) "Instalador protegido"
 Assert-KX ((Get-Acl -LiteralPath $serviceDir).AreAccessRulesProtected) "Estado K-V protegido"
 Assert-KX (-not (Test-Path -LiteralPath $kitDir)) "Kit de respaldo no existe previamente"

 $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $cert=Get-Content -LiteralPath $certificatePath -Raw|ConvertFrom-Json
 Assert-KX ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false) "K-V virtual sin publicacion"
 Assert-KX ($cert.mode -eq "kx_real_boot_verified" -and
  $cert.bootstrap_result -eq 0 -and
  $cert.bootstrap_status -eq "PASS" -and
  $cert.physical_control_enabled -eq $false) "Autoarranque real certificado"
 $originalHash=(Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash
 Assert-KX ($originalHash -eq $manifest.original_caddy_sha256 -and
  $originalHash -eq $cert.caddy_original_sha256) "Caddy original inalterado"

 $offlineRaw=Get-Content -LiteralPath $offlineCandidate -Raw -ErrorAction Stop
 Assert-KX ($offlineRaw.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT") -and
  $offlineRaw.Contains("reverse_proxy 127.0.0.1:9444") -and
  $offlineRaw.Contains("reverse_proxy 127.0.0.1:8000")) "Candidato permanece solo offline con token invalido"

 foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Tarea activa: "+$taskName)
 }
 $bootTask=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual-Boot" -ErrorAction Stop
 Assert-KX ($bootTask.State -ne "Disabled") "Bootstrap K-V habilitado"

 $kv=@(Get-Listeners 9444)
 Assert-KX ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V escucha solo en loopback"
 $pythonProc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$kv[0].OwningProcess) -ErrorAction Stop
 $sid=(Invoke-CimMethod -InputObject $pythonProc -MethodName GetOwnerSid -ErrorAction Stop).Sid
 Assert-KX ($sid -eq $manifest.dedicated_sid) "K-V conserva usuario dedicado"

 $legacy=@(Get-Listeners 8000)
 Assert-KX ($legacy.Count -ge 1 -and
  @($legacy|Where-Object{$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "Legacy 8000 restringido"
 Assert-KX (@(Get-Listeners 443).Count -ge 1) "HTTPS original en 443"

 Write-Host ""
 Write-Host "=== SOLO GET NEGATIVOS HACIA K-V LOCAL ===" -ForegroundColor Cyan
 $handler=[Net.Http.HttpClientHandler]::new()
 $handler.UseProxy=$false
 $handler.UseCookies=$false
 $handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler)
 $client.Timeout=[TimeSpan]::FromSeconds(7)
 Probe-Denial "/publico/vehiculos/1/solicitudes/estado" 403
 Probe-Denial "/admin/vehiculos/1/control-publico/solicitudes" 403
 Probe-Denial "/openapi.json" 404
 Probe-Denial "/docs" 404

 Write-Host ""
 Write-Host "=== RESPALDO ORIGINAL PRIVADO (SIN ACTIVACION) ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $kitDir -ErrorAction Stop|Out-Null
 $created=$true
 & icacls.exe $kitDir /inheritance:r | Out-Null
 Assert-KX ($LASTEXITCODE -eq 0) "Herencia de kit retirada"
 & icacls.exe $kitDir /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Assert-KX ($LASTEXITCODE -eq 0) "Kit solo SYSTEM y Administradores"
 Assert-KX ((Get-Acl -LiteralPath $kitDir).AreAccessRulesProtected) "ACL kit protegida"

 [IO.File]::Copy($originalCaddy,$backupPath,$false)
 Assert-KX ((Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash -eq $originalHash) "Copia byte a byte del Caddy original"

 $taskXml=Export-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 Assert-KX (-not [string]::IsNullOrWhiteSpace($taskXml)) "Definicion de tarea original exportada"
 [IO.File]::WriteAllText($taskPath,$taskXml,([Text.UTF8Encoding]::new($false)))
 Assert-KX (Test-Path -LiteralPath $taskPath -PathType Leaf) "Snapshot de tarea registrado"

 $report=[ordered]@{
  schema_version=1
  mode="release_preflight_only_not_activated"
  created_utc=[DateTime]::UtcNow.ToString("o")
  original_caddy_sha256=$originalHash
  backup_caddy_sha256=(Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
  caddy_task_xml_sha256=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash
  kv_untrusted_guest_get_status=403
  kv_untrusted_admin_get_status=403
  kv_docs_status=404
  kv_openapi_status=404
  original_caddy_modified=$false
  new_public_routes_activated=$false
  production_reload_executed=$false
  rollback_execution_tested=$false
  physical_control_enabled=$false
 }
 $report|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $reportPath -Encoding UTF8 -ErrorAction Stop
 Assert-KX (Test-Path -LiteralPath $reportPath -PathType Leaf) "Reporte de respaldo guardado"
 Assert-KX ((Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash -eq $originalHash) "Caddy original sigue intacto"
 foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Servicio intacto: "+$taskName)
 }
 $ok=$true
 Write-Host ""
 Write-Host "=== RESULTADO: PREFLIGHT DE ROLLBACK Y DENEGACIONES APROBADO ===" -ForegroundColor Green
 Write-Host "GET NO AUTORIZADOS K-V: 403"
 Write-Host "DOCS / OPENAPI K-V: 404"
 Write-Host "BACKUP CADDY ORIGINAL: SHA256 VERIFICADO"
 Write-Host "TAREA CADDY: DEFINICION EXPORTADA"
 Write-Host "KIT: C:\ProgramData\VehiculoIoT-KX-Installer\kx_caddy_release_preflight"
 Write-Host "ROLLBACK: MATERIALES LISTOS; EJECUCION NO PROBADA"
 Write-Host "CONFIGURACION PUBLICA: SIN MODIFICAR"
 Write-Host "RUTAS PUBLICAS NUEVAS: DESHABILITADAS"
 Write-Host "CONTROL FISICO: OFF"
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO PREFLIGHT ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO ACTIVAR CADDY NI REPETIR SIN DIAGNOSTICO"
}
finally {
 if($null -ne $client){$client.Dispose()}
 if(-not $ok -and $created -and (Test-Path -LiteralPath $kitDir)){
  try {
   Remove-Item -LiteralPath $kitDir -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Kit parcial retirado tras NO-GO" -ForegroundColor Green
  } catch {
   Write-Host "NO-GO: Kit parcial no retirado; no repetir" -ForegroundColor Red
  }
 }
 if($null -ne $originalHash -and (Test-Path -LiteralPath $originalCaddy)){
  if((Get-FileHash -LiteralPath $originalCaddy -Algorithm SHA256).Hash -eq $originalHash){
   Write-Host "OK: Archivo Caddy original sin cambios" -ForegroundColor Green
  } else {
   Write-Host "NO-GO: Hash de Caddy original inesperado" -ForegroundColor Red
  }
 }
 Write-Host "SIN RELOAD, RESTART, SET TASK, PORT FIREWALL, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X PREFLIGHT ===" -ForegroundColor Cyan
}
