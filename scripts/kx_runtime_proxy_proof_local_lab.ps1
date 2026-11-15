# K-X: test runtime env placeholder via temporary Caddy to real K-V; no production changes.
# A temporary Caddy listens 127.0.0.1:9481 and proxies only K-V's virtual admin path.
# A SIMULATED global IP is used for the trust header; NOT a public-network proof.
# The real proxy proof is passed via inherited PROCESS ENVIRONMENT only, never saved.
# GET is not fully immutable: K-V journal may advance expiry/clock metadata.
$ErrorActionPreference = "Stop"
$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$state = "C:\ProgramData\VehiculoIoT-KX-State\service"
$original = "C:\ProgramData\VehiculoIoT\Caddyfile"
$candidate = Join-Path $root "kx_caddy_offline_disabled\Caddyfile.kx.offline"
$manifestPath = Join-Path $state "install.json"
$configPath = Join-Path $state "config.json"
$certificatePath = Join-Path $root "kx_postboot_verified.json"
$backupPath = Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$drillPath = Join-Path $root "kx_caddy_rollback_rehearsal\rehearsal_results.json"
$python = "C:\ProgramData\VehiculoIoT-KX-Staging\runtime\venv\Scripts\python.exe"
$lab = Join-Path $root "kx_runtime_env_caddy_lab"
$labConfig = Join-Path $lab "Caddyfile"
$precheckFile = Join-Path $lab "no_active_tickets.py"
$reportPath = Join-Path $root "kx_runtime_env_caddy_lab_result.json"
$environmentName = "KX_STAGING_PROXY_PROOF"
$savedConfigEnv=[Environment]::GetEnvironmentVariable("XDG_CONFIG_HOME","Process")
$savedDataEnv=[Environment]::GetEnvironmentVariable("XDG_DATA_HOME","Process")
$xdgSet=$false
$secretOnDisk=$false
$config = $null
$http = $null
$caddyProcess = $null
$originalHash = $null
$complete = $false
$clean = $true
$labCreated = $false
$envWasSet = $false
$tests = @()

function Check([bool]$yes,[string]$label) {
 if(-not $yes){throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function Get-KXListener([int]$port) {
 return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Wait-Local([int]$port) {
 for($attempt=0;$attempt -lt 60;$attempt++){
  $listen = @(Get-KXListener $port)
  if($listen.Count -eq 1 -and $listen[0].LocalAddress -eq "127.0.0.1"){return $true}
  Start-Sleep -Milliseconds 250
 }
 return $false
}
function Test-Get([string]$name,[string]$origin,[string]$adminKey,[bool]$spoof,[int]$expected) {
 $path = "/admin/vehiculos/1/control-publico/solicitudes"
 $req = [Net.Http.HttpRequestMessage]::new(
  [Net.Http.HttpMethod]::Get,
  [Uri]("http://127.0.0.1:9481"+$path))
 try {
  Check ($req.Headers.TryAddWithoutValidation("Origin",$origin)) ("Origin enviado: "+$name)
  if($adminKey.Length -gt 0){
   Check ($req.Headers.TryAddWithoutValidation("X-API-Key",$adminKey)) ("Cabecera admin enviada: "+$name)
  }
  if($spoof){
   Check ($req.Headers.TryAddWithoutValidation("X-Admission-Proxy-Token","VISITOR_FALSE_TOKEN")) ("Token falso enviado: "+$name)
   Check ($req.Headers.TryAddWithoutValidation("X-Admission-Client-IP","9.9.9.9")) ("IP falsa enviada: "+$name)
   Check ($req.Headers.TryAddWithoutValidation("Forwarded","for=8.8.8.8")) ("Forwarded falso enviado: "+$name)
   Check ($req.Headers.TryAddWithoutValidation("X-Forwarded-For","8.8.8.8")) ("XFF falso enviado: "+$name)
  }
  $response = $http.SendAsync($req).GetAwaiter().GetResult()
  try {
   $actual=[int]$response.StatusCode
   Write-Host ("PRUEBA "+$name+": HTTP "+$actual)
   Check ($actual -eq $expected) ("Respuesta esperada "+$expected+": "+$name)
   Check ($response.Headers.CacheControl.NoStore -eq $true) ("No-store: "+$name)
   if($expected -eq 200){
    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    Check ($body.simulado -eq $true -and $body.control_fisico -eq $false -and
     $body.canDrive -eq $false) "Respuesta administrativa sin control fisico"
    Check (@($body.solicitudes).Count -eq 0 -and
     $body.turno_activo -eq $false) "Sin solicitudes ni turnos activos"
   }
   $script:tests += [ordered]@{case=$name;status=$actual;expected=$expected}
  } finally {$response.Dispose()}
 } finally {$req.Dispose()}
}
Write-Host ""
Write-Host "=== K-X: PRUEBA CADDY PROXY PROOF RUNTIME, SOLO LOOPBACK ===" -ForegroundColor Cyan
try {
 Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
 $id = [Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$state,$original,$candidate,$manifestPath,$configPath,
   $certificatePath,$backupPath,$drillPath,$python)){
  Check (Test-Path -LiteralPath $p) "Archivo o directorio requerido presente"
  Check (((Get-Item -LiteralPath $p -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta sin reparse point"
 }
 Check ((Get-Acl $root).AreAccessRulesProtected -and
  (Get-Acl $state).AreAccessRulesProtected) "Directorios privados protegidos"
 Check (-not (Test-Path -LiteralPath $lab)) "Laboratorio nuevo disponible"
 Check (-not (Test-Path -LiteralPath $reportPath)) "Reporte nuevo disponible"
 Check ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($environmentName,"Process"))) "Variable secreta temporal no preexistente"

 $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
 $cert=Get-Content -LiteralPath $certificatePath -Raw | ConvertFrom-Json
 $drillReport=Get-Content -LiteralPath $drillPath -Raw | ConvertFrom-Json
 Check ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false) "K-V permanece aislado y virtual"
 Check ($cert.mode -eq "kx_real_boot_verified" -and
  $cert.bootstrap_status -eq "PASS" -and
  $cert.physical_control_enabled -eq $false) "Autoarranque real certificado"
 Check ($drillReport.mode -eq "copy_only_restore_rehearsal_no_reload" -and
  $drillReport.new_public_routes_enabled -eq $false) "Rollback de copia ya aprobado"

 $originalHash=(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash
 Check ($originalHash -eq $manifest.original_caddy_sha256 -and
  $originalHash -eq $cert.caddy_original_sha256 -and
  $originalHash -eq (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash) "Caddy real y respaldo originales"
 foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Tarea original en ejecucion: "+$taskName)
 }
 $k=@(Get-KXListener 9444)
 Check ($k.Count -eq 1 -and $k[0].LocalAddress -eq "127.0.0.1") "K-V real solo 127.0.0.1:9444"
 Check (@(Get-KXListener 9481).Count -eq 0) "Puerto de ensayo 9481 libre"
 Check (@(Get-KXListener 443).Count -gt 0) "Caddy publico sigue escuchando 443"
 $ownerProcess=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$k[0].OwningProcess)
 $ownerSid=(Invoke-CimMethod -InputObject $ownerProcess -MethodName GetOwnerSid).Sid
 Check ($ownerSid -eq $manifest.dedicated_sid) "K-V mantiene identidad dedicada"
 $exe=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" |
  Where-Object{-not [string]::IsNullOrWhiteSpace($_.ExecutablePath)} |
  ForEach-Object{$_.ExecutablePath} | Select-Object -Unique)
 Check ($exe.Count -eq 1 -and (Test-Path -LiteralPath $exe[0] -PathType Leaf)) "Ejecutable Caddy activo identificado"
 $config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
 Check ($config.mode -eq "virtual_loopback_only" -and
  $config.bind_host -eq "127.0.0.1" -and
  [int]$config.bind_port -eq 9444) "Configuracion privada modo loopback"
 Check ($config.proxy_proof -is [string] -and
  $config.admin_proof -is [string] -and
  $config.proxy_proof.Length -ge 32 -and
  $config.admin_proof.Length -ge 32 -and
  $config.proxy_proof -cne $config.admin_proof) "Credenciales privadas distintas; no imprimir"

 $raw=Get-Content -LiteralPath $candidate -Raw
 Check ($raw.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT_000000000000000000") -and
  $raw.Contains("reverse_proxy 127.0.0.1:9444") -and
  $raw.Contains("reverse_proxy 127.0.0.1:8000")) "Candidato original sigue deshabilitado"

 Write-Host ""
 Write-Host "=== PRECHECK: SIN SOLICITUDES VIRTUALES ACTIVAS ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $lab -ErrorAction Stop | Out-Null
 $labCreated=$true
 & icacls.exe $lab /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia retirada"
 & icacls.exe $lab /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Ensayo solo SYSTEM y Administradores"
 Check ((Get-Acl $lab).AreAccessRulesProtected) "ACL privada comprobada"

 $pyCode=@'
import sqlite3,sys
from pathlib import Path
db_path=Path(sys.argv[1]).resolve(strict=True)
with sqlite3.connect(db_path.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
    db.execute("PRAGMA query_only=ON")
    n=db.execute("SELECT COUNT(*) FROM kr_ticket WHERE state IN ('waiting','approved_virtual')").fetchone()[0]
if n!=0:
    print("NO-GO: tickets virtuales activos")
    sys.exit(3)
print("OK: sin tickets virtuales waiting / approved_virtual")
'@
 [IO.File]::WriteAllText($precheckFile,$pyCode,([Text.UTF8Encoding]::new($false)))
 & $python -B $precheckFile ([string]$config.database_path)
 Check ($LASTEXITCODE -eq 0) "Sin tickets activos antes de prueba GET"

 Write-Host ""
 Write-Host "=== CONFIGURANDO CADDY TEMPORAL CON SECRETO SOLO EN MEMORIA ===" -ForegroundColor Cyan
 $temp=$raw.Replace("100-30-4-62.nip.io {","http://127.0.0.1:9481 {")
 $temp=$temp.Replace("http://127.0.0.1:9481 {",
  "http://127.0.0.1:9481 {"+[Environment]::NewLine+" bind 127.0.0.1")
 $temp=$temp.Replace("reverse_proxy 127.0.0.1:8000","respond 404")
 $temp=$temp.Replace("header_up X-Admission-Client-IP {http.request.remote.host}",
  "header_up X-Admission-Client-IP 1.1.1.1")
 $temp=$temp.Replace("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT_000000000000000000",
  '{env.KX_STAGING_PROXY_PROOF}')
 $temp=[string]::Join([Environment]::NewLine,@("{"," admin off"," persist_config off","}",""))+
  [Environment]::NewLine+$temp
 Check ($temp.Contains("http://127.0.0.1:9481") -and
  $temp.Contains(" bind 127.0.0.1") -and
  $temp.Contains("reverse_proxy 127.0.0.1:9444") -and
  $temp.Contains('{env.KX_STAGING_PROXY_PROOF}') -and
  $temp.Contains(' persist_config off') -and
  $temp.Contains("header_up X-Admission-Client-IP 1.1.1.1")) "Caddy lab aislado con IP SIMULADA"
 Check (-not $temp.Contains("reverse_proxy 127.0.0.1:8000") -and
  -not $temp.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT") -and
  -not $temp.Contains([string]$config.proxy_proof)) "Ningun token real guardado, legacy fuera de laboratorio"
 [IO.File]::WriteAllText($labConfig,$temp,([Text.UTF8Encoding]::new($false)))
 Write-Host ""
 Write-Host "=== ADAPTADO JSON CON PLACEHOLDER RUNTIME ===" -ForegroundColor Cyan
 $adaptOut=Join-Path $lab "adapted.json"
 $adaptErr=Join-Path $lab "adapt.stderr"
 $adaptArgs=@{
  FilePath=[string]$exe[0]
  ArgumentList=('adapt --config "'+$labConfig+'" --adapter caddyfile')
  NoNewWindow=$true
  Wait=$true
  PassThru=$true
  RedirectStandardOutput=$adaptOut
  RedirectStandardError=$adaptErr
  ErrorAction="Stop"
 }
 $adapt=Start-Process @adaptArgs
 Check ($adapt.ExitCode -eq 0) "Caddy adapt acepta placeholder runtime"
 $adaptedText=[IO.File]::ReadAllText($adaptOut)
 Check ($adaptedText.Contains('{env.KX_STAGING_PROXY_PROOF}')) "JSON adaptado conserva placeholder literal"
 Check (-not $adaptedText.Contains([string]$config.proxy_proof)) "JSON adaptado sin token de proxy real"
 Check ($adaptedText -match '"disabled"\s*:\s*true') "Admin API temporal deshabilitada"
 Check ($adaptedText -match '"persist"\s*:\s*false') "Autosave temporal deshabilitado"
 $adaptedText=$null
 [Environment]::SetEnvironmentVariable("XDG_CONFIG_HOME",(Join-Path $lab "xdg-config"),"Process")
 [Environment]::SetEnvironmentVariable("XDG_DATA_HOME",(Join-Path $lab "xdg-data"),"Process")
 $xdgSet=$true
 [Environment]::SetEnvironmentVariable($environmentName,[string]$config.proxy_proof,"Process")
 $envWasSet=$true
 $startArgs=@{
  FilePath=[string]$exe[0]
  ArgumentList=('run --config "'+$labConfig+'" --adapter caddyfile')
  PassThru=$true
  WindowStyle='Hidden'
  RedirectStandardOutput=(Join-Path $lab "caddy.stdout")
  RedirectStandardError=(Join-Path $lab "caddy.stderr")
 }
 $caddyProcess=Start-Process @startArgs
 [Environment]::SetEnvironmentVariable($environmentName,$null,"Process")
 $envWasSet=$false
 [Environment]::SetEnvironmentVariable("XDG_CONFIG_HOME",$savedConfigEnv,"Process")
 [Environment]::SetEnvironmentVariable("XDG_DATA_HOME",$savedDataEnv,"Process")
 $xdgSet=$false
 Check (Wait-Local 9481) "Proxy Caddy temporal solo 127.0.0.1:9481"
 Check (-not $caddyProcess.HasExited) "Proceso Caddy temporal vivo"

 Write-Host ""
 Write-Host "=== GET A K-V CON PROOF DE ENTORNO EN RUNTIME ===" -ForegroundColor Cyan
 $handler=[Net.Http.HttpClientHandler]::new()
 $handler.UseProxy=$false
 $handler.UseCookies=$false
 $handler.AllowAutoRedirect=$false
 $http=[Net.Http.HttpClient]::new($handler)
 $http.Timeout=[TimeSpan]::FromSeconds(8)
 Test-Get "ADMIN_VALIDO_POR_CADDY" "https://yori7v7.github.io" ([string]$config.admin_proof) $false 200
 Test-Get "ADMIN_SIN_CLAVE_POR_CADDY" "https://yori7v7.github.io" "" $false 401
 Test-Get "ADMIN_CLAVE_FALSA_POR_CADDY" "https://yori7v7.github.io" "INVALID_ADMIN_KEY" $false 403
 Test-Get "ORIGIN_FALSO_POR_CADDY" "https://example.invalid" ([string]$config.admin_proof) $false 403
 Test-Get "HEADERS_SPOOFED_FILTRADOS" "https://yori7v7.github.io" ([string]$config.admin_proof) $true 200

 $unexpected=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,[Uri]"http://127.0.0.1:9481/health")
 try {
  $r=$http.SendAsync($unexpected).GetAwaiter().GetResult()
  try {
   Check ([int]$r.StatusCode -eq 404) "Fallback legacy de laboratorio bloqueado"
  } finally {$r.Dispose()}
 } finally {$unexpected.Dispose()}
 Check ((Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash -eq $originalHash) "Caddy productivo sin modificaciones"
 foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Servicio original intacto: "+$taskName)
 }
 $complete=$true
 Write-Host "OK: Ensayo end-to-end local K-V finalizado" -ForegroundColor Green
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ENSAYO CADDY->K-V REAL ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO REPETIR NI CAMBIAR CADDY PUBLICO"
}
finally {
 Write-Host ""
 Write-Host "=== LIMPIEZA SEGURA ===" -ForegroundColor Cyan
 if($envWasSet){
  [Environment]::SetEnvironmentVariable($environmentName,$null,"Process")
  $envWasSet=$false
 }
 if($xdgSet){
  [Environment]::SetEnvironmentVariable("XDG_CONFIG_HOME",$savedConfigEnv,"Process")
  [Environment]::SetEnvironmentVariable("XDG_DATA_HOME",$savedDataEnv,"Process")
  $xdgSet=$false
 }
 if($null -ne $http){$http.Dispose()}
 if($null -ne $caddyProcess){
  try {
   $p=Get-Process -Id $caddyProcess.Id -ErrorAction SilentlyContinue
   if($null -ne $p){Stop-Process -Id $caddyProcess.Id -Force -ErrorAction Stop}
   Write-Host "OK: Caddy temporal detenido" -ForegroundColor Green
  } catch {
   $clean=$false
   Write-Host "NO-GO: proceso Caddy temporal sigue activo" -ForegroundColor Red
  }
 }
 Start-Sleep -Milliseconds 500
 if(@(Get-KXListener 9481).Count -eq 0){
  Write-Host "OK: Puerto temporal 9481 liberado" -ForegroundColor Green
 } else {
  $clean=$false
  Write-Host "NO-GO: puerto temporal 9481 sigue ocupado" -ForegroundColor Red
 }
 if($labCreated -and (Test-Path -LiteralPath $lab) -and $null -ne $config){
  Write-Host "=== AUDITANDO ARCHIVOS DE CADDY TEMPORAL ===" -ForegroundColor Cyan
  try {
   $files=@(Get-ChildItem -LiteralPath $lab -Recurse -File -ErrorAction Stop | Where-Object {
    $_.Length -lt 1048576 -and ($_.Name -eq "Caddyfile" -or
     $_.Extension -in @(".json",".log",".txt",".stdout",".stderr"))
   })
   foreach($file in $files){
    $contents=[IO.File]::ReadAllText($file.FullName)
    if($contents.Contains([string]$config.proxy_proof)){
     $secretOnDisk=$true
    }
   }
   Check (-not $secretOnDisk) "Ningun archivo del laboratorio contiene token real"
   Write-Host ("ARCHIVOS DE LABORATORIO REVISADOS: "+$files.Count)
  } catch {
   $clean=$false
   Write-Host "NO-GO: revision de persistencia en archivos incompleta" -ForegroundColor Red
  }
 }
 $config=$null
 if($labCreated -and (Test-Path -LiteralPath $lab)){
  try {
   Remove-Item -LiteralPath $lab -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Materiales temporales eliminados" -ForegroundColor Green
  } catch {
   $clean=$false
   Write-Host "NO-GO: materiales temporales no eliminados" -ForegroundColor Red
  }
 }
 if($null -ne $originalHash -and (Test-Path -LiteralPath $original)){
  if((Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash -eq $originalHash){
   Write-Host "OK: Caddy original intacto" -ForegroundColor Green
  } else {
   $clean=$false
   Write-Host "NO-GO: SHA256 Caddy original distinto" -ForegroundColor Red
  }
 }
 if($complete -and $clean){
  try {
   [ordered]@{
    schema_version=1
    mode="runtime_env_proxy_proof_local_get_only"
    tested_utc=[DateTime]::UtcNow.ToString("o")
    expected_outcomes=@($tests)
    simulated_public_client_ip="1.1.1.1"
    true_external_client_ip_tested=$false
    public_https_tested=$false
    real_proxy_proof_saved_to_file=$secretOnDisk
    caddy_admin_disabled_in_lab=$true
    caddy_autosave_disabled_in_lab=$true
    runtime_env_placeholder_in_adapted_json=$true
    candidate_enabled_in_production=$false
    production_caddy_modified=$false
    physical_control_enabled=$false
   } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8 -ErrorAction Stop
   Write-Host ""
   Write-Host "=== RESULTADO: PROXY PROOF RUNTIME SIN PERSISTENCIA APROBADO ===" -ForegroundColor Green
   Write-Host "ADMIN CON CLAVE: 200, SOLO VIRTUAL"
   Write-Host "PROXY PROOF: RESUELTO EN RUNTIME POR CADDY"
   Write-Host "TOKEN EN JSON / ARCHIVOS LAB: NO"
   Write-Host "ADMIN CADDY LAB: OFF; AUTOSAVE LAB: OFF"
   Write-Host "RECHAZOS: 401 / 403"
   Write-Host "SPOOFING DE CABECERAS: BLOQUEADO POR CADDY"
   Write-Host "CABECERA DE IP PUBLICA: SIMULADA, NO PROBADA EN INTERNET"
   Write-Host "CONFIGURACION HTTPS PUBLICA: INTACTA"
   Write-Host "LABORATORIO 9481: ELIMINADO"
   Write-Host "REPORTE: C:\ProgramData\VehiculoIoT-KX-Installer\kx_runtime_env_caddy_lab_result.json"
   Write-Host "CONTROL FISICO: OFF"
  } catch {
   Write-Host "NO-GO: reporte final no guardado" -ForegroundColor Red
  }
 } else {
  Write-Host "=== RESULTADO: ENSAYO NO APROBADO O LIMPIEZA INCOMPLETA ===" -ForegroundColor Red
 }
 Write-Host "SIN RELOAD, POST, RDS, ESP, MOTORES NI MODIFICACIONES DE TAREAS"
 Write-Host "=== FIN K-X RUNTIME PROXY PROOF ===" -ForegroundColor Cyan
}
