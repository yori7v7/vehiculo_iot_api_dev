# K-X SYSTEM real Caddy GET test, loopback only. Windows PowerShell 5.1.
# Reuses pinned completed local runtime lab, with isolated paths and exact SYSTEM identity guard.
# A temporary SYSTEM task runs Caddy only on 127.0.0.1:9481; no production task change.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$source=Join-Path $root "kx_runtime_proxy_proof_local_lab.ps1"
$previous=Join-Path $root "kx_https_public_release_v1_offline\launcher_staging_v1\system_proof_dryrun_result.json"
$manifestPath="C:\ProgramData\VehiculoIoT-KX-State\service\install.json"
$live="C:\ProgramData\VehiculoIoT\Caddyfile"
$launcher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$config="C:\ProgramData\VehiculoIoT-KX-State\service\config.json"
$autosave="C:\ProgramData\VehiculoIoT\caddy-config\caddy\autosave.json"
$work=Join-Path $root "kx_system_caddy_local_once_worker"
$worker=Join-Path $work "system_caddy_worker.ps1"
$lab=Join-Path $root "kx_system_caddy_local_once_lab"
$report=Join-Path $root "kx_system_caddy_local_once_result.json"
$ps=Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$task="VehiculoIoT-KX-CaddyLocalOnce-"+[guid]::NewGuid().ToString("N")
$expectedSourceBlob="b71c4086c2bcb260a10b4f8f525ab374a0c397a7"
$liveHash=$null
$launchHash=$null
$configHash=$null
$autoHash=$null
$created=$false
$registered=$false
$passed=$false
$clean=$true
$phase="PREFLIGHT"
function Check([bool]$ok,[string]$label){
 if(-not $ok){throw "NO-GO: "+$label}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function Normal([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ("Ruta normal: "+$label)
}
function GitBlob([string]$path){
 $b=[IO.File]::ReadAllBytes($path)
 $h=[Text.Encoding]::ASCII.GetBytes("blob "+$b.Length+[char]0)
 $all=New-Object byte[] ($h.Length+$b.Length)
 [Array]::Copy($h,0,$all,0,$h.Length)
 [Array]::Copy($b,0,$all,$h.Length,$b.Length)
 $sha=[Security.Cryptography.SHA1]::Create()
 try{return [BitConverter]::ToString($sha.ComputeHash($all)).Replace("-","").ToLowerInvariant()}
 finally{$sha.Dispose()}
}
function Listeners([int]$port){return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)}
function StopOnlyOurLabCaddy {
 $l=@(Listeners 9481)
 if($l.Count -eq 0){return $true}
 if($l.Count -ne 1 -or $l[0].LocalAddress -ne "127.0.0.1"){return $false}
 $id=[int]$l[0].OwningProcess
 $p=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$id) -ErrorAction Stop
 if($null -eq $p){return $false}
 $owner=(Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop).Sid
 if($owner -cne "S-1-5-18" -or
   [IO.Path]::GetFileName([string]$p.ExecutablePath) -cne "caddy.exe" -or
   -not ([string]$p.CommandLine).Contains((Join-Path $lab "Caddyfile"))){
   return $false
 }
 Stop-Process -Id $id -Force -ErrorAction Stop
 Start-Sleep -Milliseconds 400
 return (@(Listeners 9481).Count -eq 0)
}
Write-Host ""
Write-Host "=== K-X: CADDY REAL BAJO SYSTEM EN LOOPBACK 9481 ===" -ForegroundColor Cyan
try{
 $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Administrador elevado"
 foreach($p in @($root,$source,$previous,$manifestPath,$live,$launcher,$config,$autosave,$ps)){
  Normal $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador privado"
 foreach($p in @($work,$lab,$report)){Check (-not (Test-Path -LiteralPath $p)) ("Nueva ruta disponible: "+[IO.Path]::GetFileName($p))}
 Check ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction SilentlyContinue)) "Tarea temporal unica disponible"
 Check ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable("KX_STAGING_PROXY_PROOF","Process"))) "Sin credencial en entorno Administrador"
 Check ((GitBlob $source) -ceq $expectedSourceBlob) "Identidad exacta Git del laboratorio base"
 $p=Get-Content -LiteralPath $previous -Raw|ConvertFrom-Json
 Check ($p.mode -eq "system_real_identity_launcher_proof_dryrun_not_activated" -and
  $p.exact_candidate_function_under_system -eq $true -and
  $p.child_process_inherited_proof -eq $true -and
  $p.temporary_system_task_removed -eq $true) "Prueba anterior SYSTEM validada"
 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and $m.caddy_changed -eq $false -and
  $m.physical_control_enabled -eq $false) "K-V aun virtual y no publicado"
 $liveHash=(Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
 $launchHash=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash
 $configHash=(Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash
 $autoHash=(Get-FileHash -LiteralPath $autosave -Algorithm SHA256).Hash
 Check ($liveHash -eq $m.original_caddy_sha256 -and
  $launchHash -eq "873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1") "Produccion Caddy y launcher intactos"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name).State -eq "Running") ("Tarea original intacta: "+$name)
 }
 Check (@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'").Count -eq 1) "Un unico Caddy original en ejecucion"
 Check (@(Listeners 9481).Count -eq 0) "Puerto 9481 libre"
 Check (@(Listeners 443).Count -gt 0) "HTTPS original en 443"
 $kv=@(Listeners 9444)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V en loopback"

 Write-Host ""
 Write-Host "=== PREPARANDO COPIA DE LAB CON COMPROBACION SYSTEM ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $work -ErrorAction Stop | Out-Null
 $created=$true
 & icacls.exe $work /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia removida"
 & icacls.exe $work /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Worker solo SYSTEM y Administradores"
 Check ((Get-Acl -LiteralPath $work).AreAccessRulesProtected) "ACL del worker privada"
 $base=[IO.File]::ReadAllText($source)
 $oldLab='$lab = Join-Path $root "kx_runtime_env_caddy_lab"'
 $oldReport='$reportPath = Join-Path $root "kx_runtime_env_caddy_lab_result.json"'
 $oldGuard='Check ($id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"'
 foreach($needle in @($oldLab,$oldReport,$oldGuard)){Check ($base.Contains($needle)) "Marcador del script base presente"}
 $workerCode=$base.Replace($oldLab,'$lab = Join-Path $root "kx_system_caddy_local_once_lab"')
 $workerCode=$workerCode.Replace($oldReport,'$reportPath = Join-Path $root "kx_system_caddy_local_once_result.json"')
 $workerCode=$workerCode.Replace($oldGuard,$oldGuard+[Environment]::NewLine+
  '  Check ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ceq "S-1-5-18") "Ejecutando Caddy lab realmente como SYSTEM"')
 Check (-not $workerCode.Contains($oldLab) -and
  -not $workerCode.Contains($oldReport) -and
  $workerCode.Contains("S-1-5-18") -and
  $workerCode.Contains('{env.KX_STAGING_PROXY_PROOF}') -and
  $workerCode.Contains(" admin off") -and
  $workerCode.Contains(" persist_config off") -and
  $workerCode.Contains("http://127.0.0.1:9481")) "Worker preserva aislamiento y marcador runtime"
 $cred=(Get-Content -LiteralPath $config -Raw|ConvertFrom-Json)
 Check (-not $workerCode.Contains([string]$cred.proxy_proof) -and
  -not $workerCode.Contains([string]$cred.admin_proof)) "Worker no contiene secretos"
 $cred=$null
 $tok=$null;$err=$null
 [System.Management.Automation.Language.Parser]::ParseInput($workerCode,[ref]$tok,[ref]$err) | Out-Null
 Check (@($err).Count -eq 0) "Sintaxis worker PowerShell 5.1"
 [IO.File]::WriteAllText($worker,$workerCode,([Text.UTF8Encoding]::new($false)))

 Write-Host ""
 Write-Host "=== LANZANDO TAREA UNICA SYSTEM CON CADDY LOCAL ===" -ForegroundColor Cyan
 $phase="TASK"
 $action=New-ScheduledTaskAction -Execute $ps -Argument (
  '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$worker+'"')
 $systemPrincipal=New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
 Register-ScheduledTask -TaskPath "\" -TaskName $task -Action $action -Principal $systemPrincipal -Settings $settings -ErrorAction Stop | Out-Null
 $registered=$true
 Check ((Get-ScheduledTask -TaskPath "\" -TaskName $task).Principal.UserId -match '^(SYSTEM|S-1-5-18|NT AUTHORITY\\SYSTEM)$') "Tarea temporal bajo SYSTEM"
 Start-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop
 $phase="WAIT"
 $finish=$false
 for($i=0;$i -lt 170;$i++){
  Start-Sleep -Milliseconds 400
  $taskInfo=Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop
  if($taskInfo.State -ne "Running" -and (Test-Path -LiteralPath $report -PathType Leaf)){
   $finish=$true
   break
  }
 }
 Check ($finish) "Caddy SYSTEM termino y registro resultados"
 Check ((Get-ScheduledTaskInfo -TaskPath "\" -TaskName $task).LastTaskResult -eq 0) "Task SYSTEM termino con exit code 0"
 $outcome=Get-Content -LiteralPath $report -Raw|ConvertFrom-Json
 Check ($outcome.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $outcome.real_proxy_proof_saved_to_file -eq $false -and
  $outcome.runtime_env_placeholder_in_adapted_json -eq $true -and
  $outcome.production_caddy_modified -eq $false) "Caddy real SYSTEM: no se persiste credencial"
 $codes=@{ADMIN_VALIDO_POR_CADDY=200;ADMIN_SIN_CLAVE_POR_CADDY=401;ADMIN_CLAVE_FALSA_POR_CADDY=403;ORIGIN_FALSO_POR_CADDY=403;HEADERS_SPOOFED_FILTRADOS=200}
 foreach($k in @($codes.Keys | Sort-Object)){
  Check (@($outcome.expected_outcomes|Where-Object{$_.case -ceq $k -and $_.status -eq $codes[$k]}).Count -eq 1) ("GET SYSTEM "+$k+": HTTP "+$codes[$k])
 }
 Check (@(Listeners 9481).Count -eq 0) "Caddy SYSTEM temporal 9481 ya detenido"
 Check ((Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash -eq $liveHash -and
  (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq $launchHash -and
  (Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash -and
  (Get-FileHash -LiteralPath $autosave -Algorithm SHA256).Hash -eq $autoHash) "Caddy, launcher, autosave y config productivos sin cambios"
 $passed=$true
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ENSAYO CADDY REAL SYSTEM ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "ERROR ORIGINAL OMITIDO; NO PUBLICAR"
}
finally{
 Write-Host ""
 Write-Host "=== LIMPIEZA TAREA Y CADDY SYSTEM TEMPORALES ===" -ForegroundColor Cyan
 if($registered){
  try{
   $t=Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop
   if($t.State -eq "Running"){
    Stop-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop
    Start-Sleep -Milliseconds 800
   }
   Unregister-ScheduledTask -TaskPath "\" -TaskName $task -Confirm:$false -ErrorAction Stop
   Check ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction SilentlyContinue)) "Tarea SYSTEM temporal retirada"
  }catch{$clean=$false;Write-Host "NO-GO: tarea temporal no retirada" -ForegroundColor Red}
 }
 try{
  if(StopOnlyOurLabCaddy){
   Write-Host "OK: Caddy temporal y puerto 9481 ausentes" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Caddy temporal o puerto 9481 requiere inspeccion" -ForegroundColor Red}
 }catch{$clean=$false;Write-Host "NO-GO: fallo al inspeccionar puerto 9481" -ForegroundColor Red}
 if($created -and (Test-Path -LiteralPath $work)){
  try{Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Worker temporal retirado" -ForegroundColor Green
  }catch{$clean=$false;Write-Host "NO-GO: Worker temporal pendiente" -ForegroundColor Red}
 }
 if($null -ne $liveHash){
  if((Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash -eq $liveHash){Write-Host "OK: Caddy publico intacto" -ForegroundColor Green}
  else{$clean=$false;Write-Host "NO-GO: Caddy publico alterado" -ForegroundColor Red}
 }
 if($null -ne $launchHash){
  if((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq $launchHash){Write-Host "OK: Lanzador publico intacto" -ForegroundColor Green}
  else{$clean=$false;Write-Host "NO-GO: Lanzador publico alterado" -ForegroundColor Red}
 }
 if($passed -and $clean){
  Write-Host ""
  Write-Host "=== RESULTADO: CADDY SYSTEM REAL LOOPBACK APROBADO ===" -ForegroundColor Green
  Write-Host "CADDY REAL: SYSTEM, SOLO 127.0.0.1:9481"
  Write-Host "HTTP GET: 200 / 401 / 403, CABECERAS SPOOFED BLOQUEADAS"
  Write-Host "TOKEN: RUNTIME, NO PERSISTIDO EN ARCHIVOS INSPECCIONADOS"
  Write-Host "TAREA SYSTEM TEMPORAL: ELIMINADA"
  Write-Host "CADDY 9481: DETENIDO"
  Write-Host "HTTPS PUBLICO 443: INTACTO"
  Write-Host "K-V PUBLICO: NO ACTIVADO"
  Write-Host "CONTROL FISICO: OFF"
 }else{Write-Host "=== RESULTADO: NO-GO / LIMPIEZA INCOMPLETA ===" -ForegroundColor Red}
 Write-Host "SIN RESTART/RELOAD PRODUCTIVO, POST, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X CADDY SYSTEM ===" -ForegroundColor Cyan
}
