# K-X: verify authenticated K-V local GET contract and negative denials.
# Read-only HTTP methods only. K-V GET itself may do expiry maintenance in its SQLite journal.
# Never prints or logs private credentials. No Caddy reload or hardware control.
$ErrorActionPreference = "Stop"

$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$service = "C:\ProgramData\VehiculoIoT-KX-State\service"
$manifestFile = Join-Path $service "install.json"
$configFile = Join-Path $service "config.json"
$certFile = Join-Path $root "kx_postboot_verified.json"
$backupFile = Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$drillFile = Join-Path $root "kx_caddy_rollback_rehearsal\rehearsal_results.json"
$caddyFile = "C:\ProgramData\VehiculoIoT\Caddyfile"
$python = "C:\ProgramData\VehiculoIoT-KX-Staging\runtime\venv\Scripts\python.exe"
$tempPy = Join-Path $root ("kx_active_tickets_" + [guid]::NewGuid().ToString("N") + ".py")
$http = $null
$config = $null
$originalHash = $null
$pass = $false

function Assert-KX([bool]$condition,[string]$name) {
 if(-not $condition) {throw ("NO-GO: "+$name)}
 Write-Host ("OK: "+$name) -ForegroundColor Green
}
function Test-LocalGET([string]$name,[string]$route,[bool]$perimeter,
 [string]$proxyProof,[string]$adminProof,[bool]$badOrigin,[bool]$badHost,
 [bool]$injectForwarded,[int]$expected) {
 $req = [Net.Http.HttpRequestMessage]::new(
  [Net.Http.HttpMethod]::Get,[Uri]("http://127.0.0.1:9444"+$route))
 try {
  if($perimeter) {
   $req.Headers.Host = $(if($badHost){"example.invalid"}else{"100-30-4-62.nip.io"})
   $origin = $(if($badOrigin){"https://example.invalid"}else{"https://yori7v7.github.io"})
   Assert-KX ($req.Headers.TryAddWithoutValidation("Origin",$origin)) ("Cabecera Origin enviada: "+$name)
   Assert-KX ($req.Headers.TryAddWithoutValidation("X-Admission-Scheme","https")) ("Cabecera HTTPS enviada: "+$name)
   Assert-KX ($req.Headers.TryAddWithoutValidation("X-Admission-Client-IP","1.1.1.1")) ("IP ficticia de prueba: "+$name)
   if($proxyProof.Length -gt 0){
    Assert-KX ($req.Headers.TryAddWithoutValidation("X-Admission-Proxy-Token",$proxyProof)) ("Prueba proxy enviada: "+$name)
   }
   if($adminProof.Length -gt 0) {
    Assert-KX ($req.Headers.TryAddWithoutValidation("X-API-Key",$adminProof)) ("Prueba admin enviada: "+$name)
   }
   if($injectForwarded){
    Assert-KX ($req.Headers.TryAddWithoutValidation("X-Forwarded-For","8.8.8.8")) ("Forwarded ficticio enviado: "+$name)
   }
  }
  $response = $http.SendAsync($req).GetAwaiter().GetResult()
  try {
   $actual = [int]$response.StatusCode
   Write-Host ("PRUEBA "+$name+": HTTP "+$actual)
   Assert-KX ($actual -eq $expected) ("HTTP esperado "+$expected+": "+$name)
   Assert-KX ($response.Headers.CacheControl.NoStore -eq $true) ("No-store: "+$name)
   if($expected -eq 200) {
    $data = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    Assert-KX ($data.simulado -eq $true -and
     $data.control_fisico -eq $false -and
     $data.canDrive -eq $false) "Contrato autenticado estrictamente virtual"
    Assert-KX ($data.PSObject.Properties.Name -contains "solicitudes") "Listado admin existente"
    Assert-KX ($data.turno_activo -eq $false) "Ningun turno virtual activo"
    Assert-KX (@($data.solicitudes).Count -eq 0) "Ninguna solicitud virtual en espera"
   }
  } finally {$response.Dispose()}
 } finally {$req.Dispose()}
}

Write-Host ""
Write-Host "=== K-X: ADMIN GET LOCAL Y RECHAZOS DE SEGURIDAD ===" -ForegroundColor Cyan
try {
 Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
 $identity = [Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Assert-KX ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$service,$manifestFile,$configFile,$certFile,$backupFile,$drillFile,$caddyFile,$python)) {
  Assert-KX (Test-Path -LiteralPath $p) "Componente requerido presente"
  Assert-KX (((Get-Item -LiteralPath $p -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) "Sin ruta redirigida"
 }
 Assert-KX ((Get-Acl -LiteralPath $root).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $service).AreAccessRulesProtected) "Directorios privados protegidos"
 Assert-KX (-not (Test-Path -LiteralPath $tempPy)) "Comprobador temporal nuevo"

 $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
 $certificate = Get-Content -LiteralPath $certFile -Raw | ConvertFrom-Json
 $rehearsal = Get-Content -LiteralPath $drillFile -Raw | ConvertFrom-Json
 Assert-KX ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false) "K-V virtual sin publicacion"
 Assert-KX ($certificate.mode -eq "kx_real_boot_verified" -and
  $certificate.bootstrap_status -eq "PASS" -and
  $certificate.physical_control_enabled -eq $false) "Arranque real certificado"
 Assert-KX ($rehearsal.mode -eq "copy_only_restore_rehearsal_no_reload" -and
  $rehearsal.actual_service_rollback_tested -eq $false -and
  $rehearsal.new_public_routes_enabled -eq $false) "Rollback de copia sin recargas"
 $originalHash = (Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash
 Assert-KX ($originalHash -eq $manifest.original_caddy_sha256 -and
  $originalHash -eq $certificate.caddy_original_sha256 -and
  $originalHash -eq (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash) "Caddy y respaldo sin cambios"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")) {
  Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea original activa: "+$name)
 }
 $ports = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
 Assert-KX ($ports.Count -eq 1 -and $ports[0].LocalAddress -eq "127.0.0.1") "K-V solo loopback 9444"
 $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = "+$ports[0].OwningProcess)
 $sid = (Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid).Sid
 Assert-KX ($sid -eq $manifest.dedicated_sid) "Python K-V mantiene identidad dedicada"
 Assert-KX (@(Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "Caddy HTTPS 443 activo"

 $config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
 Assert-KX ($config.mode -eq "virtual_loopback_only" -and
  $config.bind_host -eq "127.0.0.1" -and
  $config.bind_port -eq 9444) "Configuracion K-V loopback"
 Assert-KX ($config.proxy_proof -is [string] -and
  $config.admin_proof -is [string] -and
  $config.proxy_proof.Length -ge 32 -and
  $config.admin_proof.Length -ge 32 -and
  $config.proxy_proof -cne $config.admin_proof) "Credenciales independientes; no se mostraran"

 Write-Host ""
 Write-Host "=== PRECHECK: SIN TURNOS NI TICKETS ACTIVOS ===" -ForegroundColor Cyan
 $pythonCode = @'
import sqlite3, sys
from pathlib import Path
p=Path(sys.argv[1]).resolve(strict=True)
with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
    db.execute("PRAGMA query_only=ON")
    count=db.execute(
        "SELECT COUNT(*) FROM kr_ticket WHERE state IN ('waiting','approved_virtual')"
    ).fetchone()[0]
if count == 0:
    print("OK: No existen tickets waiting ni approved_virtual")
else:
    print("NO-GO: Existen tickets activos; no hacer GET autenticado")
sys.exit(0 if count == 0 else 3)
'@
 [IO.File]::WriteAllText($tempPy,$pythonCode,([Text.UTF8Encoding]::new($false)))
 & $python -B -m py_compile $tempPy
 Assert-KX ($LASTEXITCODE -eq 0) "Comprobador Python valido"
 & $python -B $tempPy ([string]$config.database_path)
 Assert-KX ($LASTEXITCODE -eq 0) "Sin tickets ni autorizaciones pendientes"

 Write-Host ""
 Write-Host "=== GET LOCALES: ADMIN Y DENEGACIONES ===" -ForegroundColor Cyan
 $handler = [Net.Http.HttpClientHandler]::new()
 $handler.UseProxy = $false
 $handler.UseCookies = $false
 $handler.AllowAutoRedirect = $false
 $http = [Net.Http.HttpClient]::new($handler)
 $http.Timeout = [TimeSpan]::FromSeconds(8)
 $route = "/admin/vehiculos/1/control-publico/solicitudes"
 Test-LocalGET "SIN_PERIMETRO" $route $false "" "" $false $false $false 403
 Test-LocalGET "ADMIN_VALIDO" $route $true $config.proxy_proof $config.admin_proof $false $false $false 200
 Test-LocalGET "PROXY_INVALIDO" $route $true "OFFLINE_INVALID_TOKEN" $config.admin_proof $false $false $false 403
 Test-LocalGET "ORIGEN_FALSO" $route $true $config.proxy_proof $config.admin_proof $true $false $false 403
 Test-LocalGET "HOST_FALSO" $route $true $config.proxy_proof $config.admin_proof $false $true $false 403
 Test-LocalGET "FORWARDED_FALSO" $route $true $config.proxy_proof $config.admin_proof $false $false $true 403
 Test-LocalGET "SIN_CLAVE_ADMIN" $route $true $config.proxy_proof "" $false $false $false 401

 Assert-KX ((Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash -eq $originalHash) "Caddy original sin modificaciones"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")) {
  Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Servicio intacto: "+$name)
 }
 $pass = $true
 Write-Host ""
 Write-Host "=== RESULTADO: ADMIN GET K-V LOCAL CERTIFICADO ===" -ForegroundColor Green
 Write-Host "ADMIN VALIDO: HTTP 200, SIMULADO, canDrive=False"
 Write-Host "RECHAZOS: HTTP 403 / HTTP 401 ESPERADOS"
 Write-Host "CADDY PUBLICO: INTACTO"
 Write-Host "K-V: SOLO LOOPBACK"
 Write-Host "CONTROL FISICO: OFF"
 Write-Host "NOTA: K-V actualiza metadata temporal de SQLite tambien en GET valido"
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ADMIN GET LOCAL ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("ERROR: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO REPETIR NI MODIFICAR CADDY"
}
finally {
 $config = $null
 if($null -ne $http){$http.Dispose()}
 if(Test-Path -LiteralPath $tempPy){
  try {
   Remove-Item -LiteralPath $tempPy -Force -ErrorAction Stop
   Write-Host "OK: Comprobador temporal eliminado" -ForegroundColor Green
  } catch {
   Write-Host "NO-GO: Script temporal no se pudo borrar" -ForegroundColor Red
  }
 }
 if($null -ne $originalHash -and (Test-Path -LiteralPath $caddyFile)){
  if((Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash -eq $originalHash) {
   Write-Host "OK: Hash Caddy original sin cambios" -ForegroundColor Green
  } else {
   Write-Host "NO-GO: Hash Caddy inesperado" -ForegroundColor Red
  }
 }
 Write-Host "SIN POST, RELOAD CADDY, RESTART, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X ADMIN GET ===" -ForegroundColor Cyan
}
