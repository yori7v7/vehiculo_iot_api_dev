# K-X: prueba local desechable de Caddy. NO conecta a K-V ni a FastAPI.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$candidate=Join-Path $root "kx_caddy_offline_disabled\Caddyfile.kx.offline"
$lab=Join-Path $root "kx_route_header_lab"
$caddyLive="C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestPath="C:\ProgramData\VehiculoIoT-KX-State\service\install.json"
$certPath=Join-Path $root "kx_postboot_verified.json"
$python="C:\ProgramData\VehiculoIoT-KX-Staging\runtime\venv\Scripts\python.exe"
$caddyProcess=$null
$echoProcess=$null
$client=$null
$originalHash=$null
$clean=$true
function Check([bool]$ok,[string]$label){
 if(-not $ok){throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function Port([int]$num){
 return @(Get-NetTCPConnection -LocalPort $num -State Listen -ErrorAction SilentlyContinue)
}
function Poll-Port([int]$num){
 for($i=0;$i -lt 64;$i++){
  $listeners=@(Port $num)
  if($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1"){return $true}
  Start-Sleep -Milliseconds 250
 }
 return $false
}
function Probe([string]$path,[bool]$spoof){
 $request=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,[Uri]("http://127.0.0.1:9481"+$path))
 try {
  $request.Headers.TryAddWithoutValidation("Origin","https://yori7v7.github.io")|Out-Null
  if($spoof){
   foreach($entry in @(
    @("X-Admission-Proxy-Token","ATTACKER_TOKEN"),
    @("X-Admission-Client-IP","9.9.9.9"),
    @("X-Admission-Scheme","http"),
    @("Forwarded","for=8.8.8.8"),
    @("X-Forwarded-For","8.8.8.8"),
    @("X-Forwarded-Host","evil.example"),
    @("X-Forwarded-Proto","http"),
    @("X-Real-IP","8.8.8.8")
   )){
    if(-not $request.Headers.TryAddWithoutValidation($entry[0],$entry[1])){
     throw "NO-GO: no se pudo inyectar cabecera ficticia"
    }
   }
  }
  $response=$client.SendAsync($request).GetAwaiter().GetResult()
  try {
   if([int]$response.StatusCode -ne 200){throw ("NO-GO: HTTP lab "+[int]$response.StatusCode)}
   return (($response.Content.ReadAsStringAsync().GetAwaiter().GetResult())|ConvertFrom-Json)
  } finally {$response.Dispose()}
 } finally {$request.Dispose()}
}
Write-Host ""
Write-Host "=== K-X: PRUEBA AISLADA DE RUTAS Y CABECERAS ===" -ForegroundColor Cyan
try {
 $p=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($file in @($root,$candidate,$caddyLive,$manifestPath,$certPath,$python)){
  Check (Test-Path -LiteralPath $file) "Componente requerido presente"
  Check (((Get-Item -LiteralPath $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta no redirigida"
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador privado"
 Check (-not (Test-Path $lab)) "Laboratorio no preexistente"
 $m=Get-Content $manifestPath -Raw|ConvertFrom-Json
 $v=Get-Content $certPath -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and $m.physical_control_enabled -eq $false -and
  $v.mode -eq "kx_real_boot_verified" -and $v.bootstrap_status -eq "PASS") "K-V virtual certificado"
 $originalHash=(Get-FileHash $caddyLive -Algorithm SHA256).Hash
 Check ($originalHash -eq $m.original_caddy_sha256 -and $originalHash -eq $v.caddy_original_sha256) "Caddy original coincide"
 foreach($name in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea original activa: "+$name)
 }
 foreach($n in @(9481,9482,9483)){
  Check (@(Port $n).Count -eq 0) ("Puerto temporal libre: "+$n)
 }
 $kv=@(Port 9444)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V real conserva loopback"
 Check (@(Port 443).Count -gt 0) "HTTPS real 443 sigue activo"
 $raw=Get-Content $candidate -Raw
 Check ($raw.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT") -and
  $raw.Contains("reverse_proxy 127.0.0.1:9444") -and
  $raw.Contains("reverse_proxy 127.0.0.1:8000")) "Candidato desactivado y token ficticio"
 $caddyPaths=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'"|Where-Object{
  -not [string]::IsNullOrWhiteSpace($_.ExecutablePath)
 }|ForEach-Object{$_.ExecutablePath}|Select-Object -Unique)
 Check ($caddyPaths.Count -eq 1 -and (Test-Path $caddyPaths[0])) "Ejecutable Caddy real identificado"

 Write-Host ""
 Write-Host "=== CREANDO PROCESOS ECHO EN LOOPBACK ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $lab -ErrorAction Stop|Out-Null
 & icacls.exe $lab /inheritance:r|Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia deshabilitada"
 & icacls.exe $lab /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
 Check ($LASTEXITCODE -eq 0) "Archivos solo SYSTEM y Administradores"
 $echoSrc=@'
import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
class Echo(BaseHTTPRequestHandler):
 def do_GET(self):
  h=self.headers
  def vals(k):return h.get_all(k,[])
  def one(k):return vals(k)[0] if len(vals(k))==1 else ""
  token=vals("X-Admission-Proxy-Token")
  data={
   "port":self.server.server_port,"path":urlsplit(self.path).path,
   "host":one("Host"),"origin":one("Origin"),
   "clientip":one("X-Admission-Client-IP"),"clientip_count":len(vals("X-Admission-Client-IP")),
   "scheme":one("X-Admission-Scheme"),"scheme_count":len(vals("X-Admission-Scheme")),
   "token_count":len(token),
   "token_is_invalid":len(token)==1 and token[0]=="OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT_000000000000000000",
   "attacker_token":any("ATTACKER_TOKEN" in v for v in token),
   "forwarded_count":len(vals("Forwarded")),
   "xff_count":len(vals("X-Forwarded-For")),
   "xfh_count":len(vals("X-Forwarded-Host")),
   "xfp_count":len(vals("X-Forwarded-Proto")),
   "xri_count":len(vals("X-Real-IP"))
  }
  body=json.dumps(data).encode()
  self.send_response(200)
  self.send_header("Content-Type","application/json")
  self.send_header("Content-Length",str(len(body)))
  self.end_headers()
  self.wfile.write(body)
 def log_message(self,*args):pass
a=ThreadingHTTPServer(("127.0.0.1",9482),Echo)
b=ThreadingHTTPServer(("127.0.0.1",9483),Echo)
threading.Thread(target=a.serve_forever,daemon=True).start()
b.serve_forever()
'@
 $echoFile=Join-Path $lab "echo.py"
 $labCaddy=Join-Path $lab "Caddyfile"
 [IO.File]::WriteAllText($echoFile,$echoSrc,([Text.UTF8Encoding]::new($false)))
 & $python -B -m py_compile $echoFile
 Check ($LASTEXITCODE -eq 0) "Sintaxis echo Python correcta"
 $derived=$raw.Replace("100-30-4-62.nip.io {","http://127.0.0.1:9481 {")
 $derived=$derived.Replace("reverse_proxy 127.0.0.1:9444","reverse_proxy 127.0.0.1:9482")
 $derived=$derived.Replace("reverse_proxy 127.0.0.1:8000","reverse_proxy 127.0.0.1:9483")
 $prefix=[string]::Join([Environment]::NewLine,@("{"," admin off","}",""))
 $derived=$prefix+[Environment]::NewLine+$derived
 Check ($derived.Contains("http://127.0.0.1:9481") -and
  $derived.Contains("reverse_proxy 127.0.0.1:9482") -and
  $derived.Contains("reverse_proxy 127.0.0.1:9483") -and
  -not $derived.Contains("reverse_proxy 127.0.0.1:9444") -and
  -not $derived.Contains("reverse_proxy 127.0.0.1:8000")) "Ningun destino real en laboratorio"
 [IO.File]::WriteAllText($labCaddy,$derived,([Text.UTF8Encoding]::new($false)))

 $echoArgs=@{
  FilePath=$python;ArgumentList=('-B "'+$echoFile+'"');PassThru=$true;WindowStyle='Hidden'
  RedirectStandardOutput=(Join-Path $lab 'echo.stdout')
  RedirectStandardError=(Join-Path $lab 'echo.stderr')
 }
 $echoProcess=Start-Process @echoArgs
 Check (Poll-Port 9482) "Echo K-V ficticio activo"
 Check (Poll-Port 9483) "Echo FastAPI ficticio activo"
 $caddyArgs=@{
  FilePath=[string]$caddyPaths[0];ArgumentList=('run --config "'+$labCaddy+'" --adapter caddyfile')
  PassThru=$true;WindowStyle='Hidden'
  RedirectStandardOutput=(Join-Path $lab 'caddy.stdout')
  RedirectStandardError=(Join-Path $lab 'caddy.stderr')
 }
 $caddyProcess=Start-Process @caddyArgs
 Check (Poll-Port 9481) "Caddy temporal escuchando solo en loopback"
 Add-Type -AssemblyName System.Net.Http
 $handler=[Net.Http.HttpClientHandler]::new()
 $handler.UseProxy=$false;$handler.UseCookies=$false;$handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler)
 $client.Timeout=[TimeSpan]::FromSeconds(5)

 Write-Host ""
 Write-Host "=== ENSAYANDO RUTAS Y ANTI-SPOOFING ===" -ForegroundColor Cyan
 $guest=Probe "/publico/vehiculos/1/solicitudes/estado" $true
 Check ($guest.port -eq 9482 -and $guest.path -eq "/publico/vehiculos/1/solicitudes/estado") "Invitado llega a K-V ficticio"
 $admin=Probe "/admin/vehiculos/1/control-publico/solicitudes" $false
 Check ($admin.port -eq 9482) "Administrador llega a K-V ficticio"
 $legacy=Probe "/health" $false
 Check ($legacy.port -eq 9483) "Ruta legacy va a FastAPI ficticio"
 $other=Probe "/publico/vehiculos/11/solicitudes" $false
 Check ($other.port -eq 9483) "ID distinto no entra en K-V"
 $prefix=Probe "/publico/vehiculos/1/solicitudes_otra" $false
 Check ($prefix.port -eq 9483) "Prefijo ambiguo no entra en K-V"
 Check ($guest.host -eq "100-30-4-62.nip.io" -and
  $guest.origin -eq "https://yori7v7.github.io") "Host y Origin intactos"
 Check ($guest.clientip_count -eq 1 -and $guest.clientip -eq "127.0.0.1" -and
  $guest.clientip -ne "9.9.9.9") "Cabecera IP del visitante sobrescrita"
 Check ($guest.scheme_count -eq 1 -and $guest.scheme -eq "https") "Esquema HTTPS fijado por Caddy"
 Check ($guest.token_count -eq 1 -and $guest.token_is_invalid -eq $true -and
  $guest.attacker_token -eq $false) "Token falso de visitante reemplazado"
 Check ($guest.forwarded_count -eq 0 -and $guest.xff_count -eq 0 -and
  $guest.xfh_count -eq 0 -and $guest.xfp_count -eq 0 -and $guest.xri_count -eq 0) "Cabeceras prohibidas eliminadas"
 Check ((Get-FileHash $caddyLive -Algorithm SHA256).Hash -eq $originalHash) "Caddyfile real intacto"
 foreach($name in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea original preservada: "+$name)
 }
 Write-Host ""
 Write-Host "=== RESULTADO: RUTAS Y CABECERAS OFFLINE APROBADAS ===" -ForegroundColor Green
 Write-Host "RUTAS DE K-V / LEGACY: AISLADAS"
 Write-Host "CABECERAS: SOBRESCRITAS / FILTRADAS"
 Write-Host "UPSTREAMS: SOLO ECHO FICTICIO"
 Write-Host "CADDY PUBLICO: INTACTO"
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO PRUEBA CADDY ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("ERROR: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO ACTIVAR CADDY CANDIDATO"
}
finally {
 Write-Host ""
 Write-Host "=== LIMPIEZA DE LABORATORIO ===" -ForegroundColor Cyan
 if($null -ne $client){$client.Dispose()}
 foreach($proc in @($caddyProcess,$echoProcess)){
  if($null -eq $proc){continue}
  try {
   $existing=Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
   if($null -ne $existing){Stop-Process -Id $proc.Id -Force -ErrorAction Stop}
   Write-Host ("OK: PID temporal "+$proc.Id+" eliminado") -ForegroundColor Green
  } catch {$clean=$false;Write-Host ("NO-GO: PID temporal "+$proc.Id+" no detenido") -ForegroundColor Red}
 }
 Start-Sleep -Milliseconds 500
 foreach($n in @(9481,9482,9483)){
  if(@(Port $n).Count -eq 0){Write-Host ("OK: puerto "+$n+" libre") -ForegroundColor Green}
  else{$clean=$false;Write-Host ("NO-GO: puerto "+$n+" ocupado") -ForegroundColor Red}
 }
 if($clean -and (Test-Path -LiteralPath $lab)){
  try {
   Remove-Item -LiteralPath $lab -Recurse -Force -ErrorAction Stop
   Write-Host "OK: archivos temporales retirados" -ForegroundColor Green
  } catch {$clean=$false;Write-Host "NO-GO: archivos temporales presentes" -ForegroundColor Red}
 }
 if($null -ne $originalHash -and (Test-Path $caddyLive)){
  if((Get-FileHash $caddyLive -Algorithm SHA256).Hash -eq $originalHash){
   Write-Host "OK: Caddy original sin alteraciones" -ForegroundColor Green
  } else {$clean=$false;Write-Host "NO-GO: Hash Caddy cambio" -ForegroundColor Red}
 }
 if($clean){Write-Host "=== LIMPIEZA COMPLETA ===" -ForegroundColor Green}
 else{Write-Host "=== NO-GO LIMPIEZA INCOMPLETA, NO REPETIR ===" -ForegroundColor Red}
 Write-Host "SIN HTTP A K-V REAL NI BACKEND REAL; SIN RELOAD CADDY; SIN RDS / ESP / MOTORES"
 Write-Host "=== FIN K-X LABORATORIO ===" -ForegroundColor Cyan
}
