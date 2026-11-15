# K-X: test HTTP de la tarea K-V instalada, reinicio de servicio y fencing de sesiones.
# Solo admision virtual. NO modifica Caddy, firewall, tareas legacy ni hardware.
$ErrorActionPreference = "Stop"
$stage = "C:\ProgramData\VehiculoIoT-KX-Staging"
$serviceDir = "C:\ProgramData\VehiculoIoT-KX-State\service"
$taskName = "VehiculoIoT-Admission-Virtual"
$configPath = Join-Path $serviceDir "config.json"
$manifestPath = Join-Path $serviceDir "install.json"
$caddy = "C:\ProgramData\VehiculoIoT\Caddyfile"
$http = $null
$interrupted = $false
$restarted = $false
$initialHash = $null
$taskSid = $null
$checks = 0
function Assert-KX([bool]$condition, [string]$label) {
  if(-not $condition){throw ("NO-GO: "+$label)}
  Write-Host ("OK: "+$label) -ForegroundColor Green
}
function New-BrowserKey {
  $bytes = New-Object byte[] 32
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
  } finally { $rng.Dispose(); [Array]::Clear($bytes,0,$bytes.Length) }
}
function Invoke-KV([string]$method,[string]$path,[hashtable]$extra,[string]$payload=$null) {
  $uri = [Uri]("http://127.0.0.1:9444"+$path)
  $req = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($method),$uri)
  try {
    $req.Headers.Host = "100-30-4-62.nip.io"
    $headers = @{
      "Origin" = "https://yori7v7.github.io"
      "X-Admission-Scheme" = "https"
      "X-Admission-Client-IP" = "9.9.9.9"
      "X-Admission-Proxy-Token" = $config.proxy_proof
    }
    if($null -ne $extra) {
      foreach($key in $extra.Keys){$headers[$key]=$extra[$key]}
    }
    foreach($key in $headers.Keys) {
      Assert-KX ([bool]$req.Headers.TryAddWithoutValidation($key,[string]$headers[$key])) ("Cabecera valida: "+$key)
    }
    if($null -ne $payload) {
      $req.Content = [Net.Http.StringContent]::new($payload,[Text.Encoding]::UTF8,"application/json")
    }
    $res = $http.SendAsync($req).GetAwaiter().GetResult()
    try {
      $body = $res.Content.ReadAsStringAsync().GetAwaiter().GetResult()
      $parsed = $null
      if(-not [string]::IsNullOrWhiteSpace($body)){
        $parsed = $body | ConvertFrom-Json
      }
      return @{Status=[int]$res.StatusCode; Data=$parsed}
    } finally {$res.Dispose()}
  } finally {$req.Dispose()}
}
function Wait-KX([bool]$listening,[int]$timeoutTicks) {
  for($i=0;$i -lt $timeoutTicks;$i++){
    $listeners = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    if($listening -and $listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1"){return $true}
    if(-not $listening -and $listeners.Count -eq 0){return $true}
    Start-Sleep -Milliseconds 500
  }
  return $false
}

Write-Host ""
Write-Host "=== K-X: PRUEBA END-TO-END CON REINICIO Y FENCING ===" -ForegroundColor Cyan
try {
  $identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  Assert-KX ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
  Assert-KX (Test-Path -LiteralPath $configPath -PathType Leaf) "Credenciales privadas presentes"
  Assert-KX (Test-Path -LiteralPath $manifestPath -PathType Leaf) "Manifiesto de instalacion presente"
  Assert-KX (Test-Path -LiteralPath $caddy -PathType Leaf) "Caddy original presente"
  $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
  $st = Get-Content (Join-Path $stage "stage.json") -Raw | ConvertFrom-Json
  Assert-KX ($manifest.schema_version -eq 1 -and $manifest.mode -eq "loopback_only_not_public" -and
             $manifest.task_name -eq $taskName -and $manifest.dedicated_user -eq "VehIoT_KXSvc" -and
             $manifest.physical_control_enabled -eq $false -and $manifest.caddy_changed -eq $false) "Contrato K-X virtual"
  Assert-KX ($st.mode -eq "offline_staging_only") "Staging original independiente"
  $initialHash = (Get-FileHash $caddy -Algorithm SHA256).Hash
  Assert-KX ($initialHash -eq $manifest.original_caddy_sha256) "Caddy sin modificaciones"
  Assert-KX ((Get-FileHash (Join-Path $serviceDir "launcher.py") -Algorithm SHA256).Hash -eq $manifest.launcher_sha256) "Lanzador sin alteraciones"
  $account = Get-LocalUser -Name "VehIoT_KXSvc" -ErrorAction Stop
  $taskSid = $account.SID.Value
  Assert-KX ($taskSid -eq $manifest.dedicated_sid) "SID dedicado correcto"
  $task = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  Assert-KX ($task.State -eq "Running") "Tarea K-V en ejecucion"
  Assert-KX (@($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) "Aun sin trigger automatico"
  Assert-KX (Wait-KX $true 2) "Solo loopback 9444"
  foreach($name in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")) {
    Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea legacy activa: "+$name)
  }
  Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "8000 legacy disponible"
  $config = Get-Content $configPath -Raw | ConvertFrom-Json
  Assert-KX ($config.mode -eq "virtual_loopback_only" -and $config.bind_host -eq "127.0.0.1" -and
             $config.bind_port -eq 9444 -and $config.admin_proof -ne $config.proxy_proof) "Configuracion privada del servicio"
  $configAcl = Get-Acl -LiteralPath $configPath
  Assert-KX ($configAcl.AreAccessRulesProtected -or (Get-Acl -LiteralPath $serviceDir).AreAccessRulesProtected) "Ruta privada protegida"
  Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
  $handler = [Net.Http.HttpClientHandler]::new()
  $handler.UseProxy = $false
  $handler.UseCookies = $false
  $handler.AllowAutoRedirect = $false
  $http = [Net.Http.HttpClient]::new($handler)
  $http.Timeout = [TimeSpan]::FromSeconds(5)

  Write-Host ""
  Write-Host "=== SOLICITUD Y APROBACION VIRTUAL ===" -ForegroundColor Cyan
  $guestPath = "/publico/vehiculos/1/solicitudes"
  $adminPath = "/admin/vehiculos/1/control-publico/solicitudes"
  $idem = New-BrowserKey
  $proposal = New-BrowserKey
  Assert-KX ($idem -ne $proposal) "Claves de solicitud distintas"
  $request = Invoke-KV "POST" $guestPath @{
    "Idempotency-Key" = $idem
    "X-Browser-Proposal" = $proposal
  }
  Assert-KX ($request.Status -eq 201 -and $request.Data.canDrive -eq $false) "Ticket virtual HTTP 201, sin conducir"
  $browser = $request.Data.browser_secret
  $requestId = $request.Data.request_id
  Assert-KX (-not [string]::IsNullOrWhiteSpace($browser) -and -not [string]::IsNullOrWhiteSpace($requestId)) "Ticket opaco recibido"
  $checks++

  $adminHeaders = @{"X-API-Key"=$config.admin_proof}
  $guestHeaders = @{"X-Browser-Session"=$browser}
  $response = Invoke-KV "POST" ($adminPath+"/supervision") $adminHeaders
  Assert-KX ($response.Status -eq 200 -and $response.Data.canDrive -eq $false) "Supervision virtual activa"
  $checks++
  $response = Invoke-KV "POST" ($adminPath+"/"+$requestId+"/aprobar") $adminHeaders '{"modo":"timed","segundos":45}'
  Assert-KX ($response.Status -eq 200 -and $response.Data.canDrive -eq $false) "Aprobacion virtual sin motores"
  $checks++
  $response = Invoke-KV "GET" ($guestPath+"/estado") $guestHeaders
  Assert-KX ($response.Status -eq 200 -and $response.Data.estado -eq "autorizado" -and
             $response.Data.canDrive -eq $false) "Turno virtual vigente antes del reinicio"
  $checks++

  Write-Host ""
  Write-Host "=== REINICIO INDEPENDIENTE DE LA TAREA K-V ===" -ForegroundColor Cyan
  $interrupted = $true
  Stop-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  Assert-KX (Wait-KX $false 50) "Puerto 9444 cerrado tras detener K-V"
  Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "Backend original 8000 sin interrupcion"
  Start-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  Assert-KX (Wait-KX $true 80) "Sidecar K-V reiniciado en loopback"
  $restarted = $true
  $listener = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
  $process = Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listener[0].OwningProcess) -ErrorAction Stop
  $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid -ErrorAction Stop
  Assert-KX ($owner.Sid -eq $taskSid) "Proceso reiniciado bajo identidad dedicada"
  $response = Invoke-KV "GET" ($guestPath+"/estado") $guestHeaders
  Assert-KX ($response.Status -eq 401) "Sesion anterior rechazada tras cambio de epoca"
  $checks++
  $response = Invoke-KV "GET" $adminPath $adminHeaders
  Assert-KX ($response.Status -eq 200 -and $response.Data.turno_activo -eq $false -and
             $response.Data.canDrive -eq $false) "Sin turno virtual heredado"
  $checks++
  $response = Invoke-KV "POST" ($adminPath+"/revocar") $adminHeaders
  Assert-KX ($response.Status -eq 200 -and $response.Data.canDrive -eq $false) "Revocacion de cierre disponible"
  $checks++
  Assert-KX ((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $initialHash) "Caddy original intacto"
  foreach($name in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")) {
    Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Legacy aun activa: "+$name)
  }
  Assert-KX ($checks -eq 7) "Siete operaciones HTTP de ciclo y reinicio"
  Write-Host ""
  Write-Host "=== RESULTADO: REINICIO Y EPOCAS K-V APROBADOS ===" -ForegroundColor Green
  Write-Host "SESIONES ANTERIORES: INVALIDADAS"
  Write-Host "PUERTO 9444: SOLO LOOPBACK"
  Write-Host "CADDY: INTACTO; MOTOR: NO HABILITADO"
} catch {
  Write-Host ""
  Write-Host "=== RESULTADO: NO-GO ===" -ForegroundColor Red
  Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
  Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
  Write-Host "NO activar Caddy ni crear triggers nuevos"
} finally {
  if($interrupted -and -not $restarted) {
    Write-Host ""
    Write-Host "=== RECUPERACION DEL SERVICIO VIRTUAL ===" -ForegroundColor Cyan
    try {
      $task = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
      if($task.State -ne "Running") {
        Start-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
      }
      Assert-KX (Wait-KX $true 80) "Servicio virtual restaurado en loopback"
    } catch {
      Write-Host "NO-GO: No se pudo restaurar K-V; conservar Caddy intacto" -ForegroundColor Red
    }
  }
  if($null -ne $http){$http.Dispose()}
  $config=$null; $browser=$null; $idem=$null; $proposal=$null; $adminHeaders=$null; $guestHeaders=$null
  Write-Host "SIN CAMBIOS A CADDY, RDS, ESP, MOTORES O TAREAS LEGACY"
  Write-Host "=== FIN K-X REINICIO VIRTUAL ===" -ForegroundColor Cyan
}
