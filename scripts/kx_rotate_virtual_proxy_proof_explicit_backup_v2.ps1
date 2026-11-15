# K-X v2: Rotate ONLY virtual local K-V proxy_proof with explicit NTFS replacement backup (verified in five dummy tests).
# CAUTION: This stops/starts K-V task ONLY; Caddy/legacy tasks/config and admin_proof untouched.
# No physical control, no RDS, no public K-V exposure. Fail closed if unable to certify rotation.
$ErrorActionPreference="Stop"
$installer="C:\ProgramData\VehiculoIoT-KX-Installer"
$service="C:\ProgramData\VehiculoIoT-KX-State\service"
$manifestPath=Join-Path $service "install.json"
$configPath=Join-Path $service "config.json"
$launcher=Join-Path $service "launcher.py"
$bootCertificate=Join-Path $installer "kx_postboot_verified.json"
$caddyPath="C:\ProgramData\VehiculoIoT\Caddyfile"
$prodAutosave="C:\ProgramData\VehiculoIoT\caddy-config\caddy\autosave.json"
$backup=Join-Path $installer "kx_caddy_release_preflight\Caddyfile.original.copy"
$oldAuto=Join-Path $env:APPDATA "Caddy\autosave.json"
$rotationReport=Join-Path $installer "kx_proxy_proof_rotation_result.json"
$staged=Join-Path $service ("config_rotation_v2_"+[guid]::NewGuid().ToString("N")+".tmp")
$rollbackBackup=Join-Path $service ("config_rotation_v2_old_"+[guid]::NewGuid().ToString("N")+".backup")
$oldProof=$null
$newProof=$null
$adminProof=$null
$config=$null
$client=$null
$caddyHash=$null
$originalConfigHash=$null
$stopped=$false
$swapped=$false
$swapAttempted=$false
$oldBackupRemoved=$false
$verified=$false
$success=$false
$phase="PREFLIGHT"

function Check([bool]$ok,[string]$message){
 if(-not $ok){throw ("NO-GO: "+$message)}
 Write-Host ("OK: "+$message) -ForegroundColor Green
}
function NoReparse([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) ("No redirigido: "+$label)
}
function CheckACL([string]$path,[string]$dedicatedSid,[bool]$allowDedicated) {
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $trusted=@("S-1-5-18","S-1-5-32-544",([Security.Principal.WindowsIdentity]::GetCurrent().User.Value))
 if($allowDedicated){$trusted+= $dedicatedSid}
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
    $rule.IdentityReference.Value -notin $trusted){
   throw "NO-GO: Permisos ACL a identidades inesperadas"
  }
 }
}
function KXListeners([int]$port) {
 return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function WaitPort([bool]$wantListening){
 for($attempt=0;$attempt -lt 80;$attempt++){
  $listeners=@(KXListeners 9444)
  $isOK=if($wantListening){
   $listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1"
  }else{$listeners.Count -eq 0}
  if($isOK){return $true}
  Start-Sleep -Milliseconds 250
 }
 return $false
}
function MakeProof {
 $bytes=New-Object byte[] 48
 $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
 try{
  $rng.GetBytes($bytes)
  return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
 }finally{
  $rng.Dispose()
  [Array]::Clear($bytes,0,$bytes.Length)
 }
}
function Probe([string]$proxy,[string]$admin,[int]$expect,[string]$label) {
 $req=[System.Net.Http.HttpRequestMessage]::new(
  [System.Net.Http.HttpMethod]::Get,
  [Uri]"http://127.0.0.1:9444/admin/vehiculos/1/control-publico/solicitudes")
 try{
  $req.Headers.Host="100-30-4-62.nip.io"
  foreach($entry in @(
    @("Origin","https://yori7v7.github.io"),
    @("X-Admission-Scheme","https"),
    @("X-Admission-Client-IP","1.1.1.1"),
    @("X-Admission-Proxy-Token",$proxy),
    @("X-API-Key",$admin)
  )){
   Check ($req.Headers.TryAddWithoutValidation($entry[0],$entry[1])) ("Cabecera valida: "+$label)
  }
  $res=$client.SendAsync($req).GetAwaiter().GetResult()
  try{
   $status=[int]$res.StatusCode
   Write-Host ("PRUEBA "+$label+": HTTP "+$status)
   Check ($status -eq $expect) ("Respuesta "+$expect+" esperada: "+$label)
   Check ($res.Headers.CacheControl.NoStore -eq $true) ("No-store: "+$label)
   if($expect -eq 200){
    $json=$res.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    Check ($json.simulado -eq $true -and
      $json.control_fisico -eq $false -and
      $json.canDrive -eq $false) "Respuesta sin control fisico"
    Check ($json.turno_activo -eq $false -and
      @($json.solicitudes).Count -eq 0) "No hay turnos ni solicitudes activos"
   }
  }finally{$res.Dispose()}
 }finally{$req.Dispose()}
}
Write-Host ""
Write-Host "=== K-X: ROTACION CONTROLADA DE PROXY_PROOF + RETIRO AUTOSAVE ===" -ForegroundColor Cyan
try{
 $who=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($who.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 $profileAppData=[IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "AppData")).TrimEnd("\")
 $appDataRoot=[IO.Path]::GetFullPath($env:APPDATA).TrimEnd("\")
 Check ($appDataRoot.StartsWith($profileAppData+"\",[StringComparison]::OrdinalIgnoreCase)) "APPDATA corresponde al perfil actual"
 NoReparse (Split-Path -Parent $oldAuto) "Carpeta Caddy del perfil Administrador"
 foreach($p in @($installer,$service,$manifestPath,$configPath,$launcher,
  $bootCertificate,$caddyPath,$prodAutosave,$backup,$oldAuto)){
  NoReparse $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $installer).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $service).AreAccessRulesProtected) "Directorios K-X protegidos"
 Check (-not (Test-Path -LiteralPath $rotationReport)) "Rotacion aun no ejecutada"
 Check (-not (Test-Path -LiteralPath $staged)) "Temporal de configuracion no presente"
 Check (-not (Test-Path -LiteralPath $rollbackBackup)) "Ruta de respaldo temporal nueva"
 Check (-not (Test-Path -LiteralPath (Join-Path $installer "kx_rotate_virtual_proxy_proof_explicit_backup_v2.ps1.report"))) "Sin reporte alternativo de rotacion"
 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $cert=Get-Content -LiteralPath $bootCertificate -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and $m.caddy_changed -eq $false -and
  $m.physical_control_enabled -eq $false -and $m.task_name -eq "VehiculoIoT-Admission-Virtual" -and
  $m.dedicated_user -eq "VehIoT_KXSvc") "K-V virtual, sin publicar"
 Check ($cert.mode -eq "kx_real_boot_verified" -and $cert.bootstrap_status -eq "PASS") "Arranque certificado"
 Check ((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq $m.launcher_sha256) "Lanzador K-V inalterado"
 $caddyHash=(Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash
 Check ($caddyHash -eq $m.original_caddy_sha256 -and
  $caddyHash -eq (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash) "Caddy y backup intactos"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea original Running: "+$name)
 }
 Check (@(KXListeners 9481).Count -eq 0) "Sin Caddy temporal 9481"
 Check (@(KXListeners 443).Count -gt 0) "HTTPS original 443 activo"
 $listeners=@(KXListeners 9444)
 Check ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1") "K-V solo loopback"
 $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listeners[0].OwningProcess) -ErrorAction Stop
 $owner=(Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop).Sid
 Check ($owner -eq $m.dedicated_sid) "K-V bajo cuenta dedicada"
 CheckACL $configPath $m.dedicated_sid $true
 CheckACL $prodAutosave $m.dedicated_sid $false
 CheckACL $oldAuto $m.dedicated_sid $false
 Write-Host "OK: ACL de secretos sin otros lectores" -ForegroundColor Green

 $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
 Check ($config.schema_version -eq 1 -and $config.mode -eq "virtual_loopback_only" -and
  $config.bind_host -eq "127.0.0.1" -and [int]$config.bind_port -eq 9444) "Config virtual intacta"
 Check ($config.proxy_proof -is [string] -and
  $config.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  $config.admin_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  $config.proxy_proof -cne $config.admin_proof) "Secretos actuales validos; no se muestran"
 $expectedKeys=@("schema_version","mode","bind_host","bind_port","database_path","admin_proof","proxy_proof")
 $actualKeys=@($config.PSObject.Properties.Name | Sort-Object)
 Check (($actualKeys -join ",") -eq ((@($expectedKeys | Sort-Object)) -join ",")) "Estructura de config sin propiedades inesperadas"
 $oldProof=[string]$config.proxy_proof
 $adminProof=[string]$config.admin_proof
 $originalConfigHash=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
 $oldProfile=[IO.File]::ReadAllText($oldAuto)
 Check ($oldProfile.Contains($oldProof) -and
  $oldProfile.IndexOf("X-Admission-Proxy-Token",[StringComparison]::OrdinalIgnoreCase) -ge 0) "Autosave de laboratorio contiene token antiguo"
 $oldProfile=$null
 Check (-not ([IO.File]::ReadAllText($prodAutosave)).Contains($oldProof)) "Autosave de produccion sin token anterior"
 $localData=Join-Path $env:LOCALAPPDATA "Caddy\autosave.json"
 Check (-not (Test-Path -LiteralPath $localData)) "Sin autosave alternativo LOCALAPPDATA"
 $caddyList=@(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop)
 Check ($caddyList.Count -eq 1 -and
  $caddyList[0].ProcessId -eq @(KXListeners 443)[0].OwningProcess) "Un unico Caddy de produccion en ejecucion"
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop
 Check ($task.Principal.RunLevel -eq "Limited") "Tarea K-V sin elevacion"
 Check ((Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual-Boot" -ErrorAction Stop).State -in @("Ready","Running")) "Bootstrap existente y habilitado"

 Write-Host ""
 Write-Host "=== PRECHECK SQLITE SOLO LECTURA (SIN TICKETS ACTIVOS) ===" -ForegroundColor Cyan
 Add-Type -AssemblyName System.Data -ErrorAction Stop
 # Use Python read-only as in previously approved no-active-ticket preflight.
 $py="C:\ProgramData\VehiculoIoT-KX-Staging\runtime\venv\Scripts\python.exe"
 NoReparse $py "Python aislado"
 $checkFile=Join-Path $installer ("kx_tickets_ro_"+[guid]::NewGuid().ToString("N")+".py")
 $pyCode=@'
import sqlite3,sys
from pathlib import Path
p=Path(sys.argv[1]).resolve(strict=True)
with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
    db.execute("PRAGMA query_only=ON")
    n=db.execute("SELECT COUNT(*) FROM kr_ticket WHERE state IN ('waiting','approved_virtual')").fetchone()[0]
print("PRECHECK TICKETS ACTIVOS: "+str(n))
sys.exit(0 if n==0 else 3)
'@
 try{
  [IO.File]::WriteAllText($checkFile,$pyCode,([Text.UTF8Encoding]::new($false)))
  & $py -B $checkFile ([string]$config.database_path)
  Check ($LASTEXITCODE -eq 0) "No hay solicitudes ni turnos virtuales activos"
 }finally{
  if(Test-Path -LiteralPath $checkFile){Remove-Item -LiteralPath $checkFile -Force -ErrorAction SilentlyContinue}
 }

 Write-Host ""
 Write-Host "=== PREPARANDO ROTACION DE 64 CARACTERES SIN IMPRIMIR TOKEN ===" -ForegroundColor Cyan
 $phase="STAGING"
 $newProof=MakeProof
 Check ($newProof.Length -eq 64 -and
  $newProof -cmatch '^[A-Za-z0-9_-]{64}$' -and
  $newProof -cne $oldProof -and
  $newProof -cne $adminProof) "Nuevo proxy proof aleatorio valido"
 $config.proxy_proof=$newProof
 $json=$config|ConvertTo-Json -Depth 4
 Check ($json.Length -lt 4096 -and
  $json.Contains($newProof) -and
  -not $json.Contains($oldProof)) "Nuevo JSON preparado sin token antiguo"
 [IO.File]::WriteAllText($staged,$json,([Text.UTF8Encoding]::new($false)))
 CheckACL $staged $m.dedicated_sid $true
 Check ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $originalConfigHash) "Config real sin cambios antes del STOP"

 Write-Host ""
 Write-Host "=== DETENIENDO SOLO K-V PARA ROTACION ===" -ForegroundColor Cyan
 $phase="STOP_KV"
 Stop-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop
 $stopped=$true
 Check (WaitPort $false) "Puerto K-V 9444 cerrado antes de reemplazo"
 Check ((Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy").State -eq "Running") "Caddy sigue funcionando"
 Check ((Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-FastAPI").State -eq "Running") "Legacy sigue funcionando"

 Write-Host ""
 Write-Host "=== SUSTITUYENDO SOLO CONFIG K-V EN NTFS ===" -ForegroundColor Cyan
 $phase="SWAP"
 Check (-not (Test-Path -LiteralPath $rollbackBackup)) "Respaldo NTFS explicito disponible"
 Check ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $originalConfigHash) "Original igual antes de intercambio"
 Check (@(KXListeners 9444).Count -eq 0) "Sidecar 9444 realmente detenido"
 $volume=Get-Volume -DriveLetter C -ErrorAction Stop
 Check ($volume.FileSystem -eq "NTFS") "Unidad C utiliza NTFS"
 Check (([IO.Path]::GetPathRoot($rollbackBackup)) -ceq ([IO.Path]::GetPathRoot($configPath))) "Respaldo NTFS en mismo volumen"
 # IMPORTANT: File.Replace(..., $null) failed with HRESULT 0x80070057 on this server.
 # Five independent dummy tests proved an EXPLICIT backup path succeeds.
 $swapAttempted=$true
 [IO.File]::Replace($staged,$configPath,$rollbackBackup)
 $swapped=$true
 Check (Test-Path -LiteralPath $rollbackBackup -PathType Leaf) "Respaldo NTFS antiguo creado dentro del directorio privado"
 Check (((Get-Item -LiteralPath $rollbackBackup -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Respaldo temporal sin reparse point"
 CheckACL $rollbackBackup $m.dedicated_sid $true
 Check ((Get-FileHash -LiteralPath $rollbackBackup -Algorithm SHA256).Hash -eq $originalConfigHash) "Respaldo contiene exactamente configuracion antigua"
 Check ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalConfigHash) "Configuracion K-V cambiada"
 CheckACL $configPath $m.dedicated_sid $true
 $onDisk=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
 Check ($onDisk.proxy_proof -ceq $newProof -and $onDisk.admin_proof -ceq $adminProof -and
  $onDisk.mode -eq "virtual_loopback_only") "Solo proxy_proof actualizado"
 $onDisk=$null
 # The backup holds the previously exposed credential. Do NOT retain it;
 # never use it to restore a known-exposed proof after a partial rotation.
 Remove-Item -LiteralPath $rollbackBackup -Force -ErrorAction Stop
 Check (-not (Test-Path -LiteralPath $rollbackBackup)) "Respaldo con token antiguo retirado antes de reiniciar K-V"
 $oldBackupRemoved=$true

 Write-Host ""
 Write-Host "=== REINICIANDO SOLO SERVICIO VIRTUAL K-V ===" -ForegroundColor Cyan
 $phase="START_KV"
 Start-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop
 Check (WaitPort $true) "K-V vuelve a 127.0.0.1:9444"
 $listen=@(KXListeners 9444)
 $process=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listen[0].OwningProcess) -ErrorAction Stop
 Check ((Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid).Sid -eq $m.dedicated_sid) "K-V reanudado bajo identidad dedicada"
 Check ((Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual").State -eq "Running") "Tarea virtual reanudada"

 $phase="CHECK_AUTH"
 $handler=[Net.Http.HttpClientHandler]::new()
 $handler.UseProxy=$false
 $handler.UseCookies=$false
 $handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler)
 $client.Timeout=[TimeSpan]::FromSeconds(8)
 Write-Host ""
 Write-Host "=== COMPROBACION NUEVO TOKEN Y REVOCACION DEL ANTIGUO ===" -ForegroundColor Cyan
 Probe $oldProof $adminProof 403 "TOKEN_ANTIGUO_REVOCADO"
 Probe $newProof $adminProof 200 "TOKEN_NUEVO_AUTORIZADO"
 $verified=$true
 Check ((Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash -eq $caddyHash) "Caddyfile sigue intacto"

 Write-Host ""
 Write-Host "=== RETIRANDO AUTOSAVE OBSOLETO DEL PERFIL ADMIN ===" -ForegroundColor Cyan
 $phase="CLEANUP_OLD_AUTOSAVE"
 Check (([IO.File]::ReadAllText($oldAuto)).Contains($oldProof)) "Autosave obsoleto exacto localizado"
 Remove-Item -LiteralPath $oldAuto -Force -ErrorAction Stop
 Check (-not (Test-Path -LiteralPath $oldAuto)) "Autosave antiguo retirado"
 Check (Test-Path -LiteralPath $prodAutosave) "Autosave productivo preservado"
 Check (-not ([IO.File]::ReadAllText($prodAutosave)).Contains($newProof)) "Autosave productivo no contiene token nuevo"

 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea tras rotacion: "+$name)
 }
 Check (@(KXListeners 9481).Count -eq 0) "Sin laboratorio temporal 9481"
 Check ((Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash -eq $caddyHash) "Caddy 443 sin cambios"

 $phase="REPORT"
 [ordered]@{
  schema_version=1
  mode="proxy_proof_rotated_kv_loopback_only"
  updated_utc=[DateTime]::UtcNow.ToString("o")
  old_proxy_rejected=403
  new_proxy_authenticated=200
  stale_profile_autosave_deleted=$true
  explicit_ntfs_backup_used=$true
  old_ntfs_backup_deleted_before_restart=$oldBackupRemoved
  production_caddy_sha256=$caddyHash
  admin_proof_unchanged=$true
  no_active_virtual_tickets=$true
  caddy_changed=$false
  public_routes_enabled=$false
  rds_enabled_by_script=$false
  physical_control_enabled=$false
 }|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $rotationReport -Encoding UTF8 -ErrorAction Stop
 Check (Test-Path -LiteralPath $rotationReport -PathType Leaf) "Reporte sin secretos guardado"
 Check ($oldBackupRemoved -and -not (Test-Path -LiteralPath $rollbackBackup)) "Sin respaldo temporal con token antiguo"
 $success=$true
 Write-Host ""
 Write-Host "=== RESULTADO: ROTACION K-V Y CONTENCION APROBADAS ===" -ForegroundColor Green
 Write-Host "TOKEN ANTIGUO: REVOCADO HTTP 403"
 Write-Host "TOKEN NUEVO: VALIDADO HTTP 200"
 Write-Host "AUTOSAVE PERFIL ADMIN: RETIRADO"
 Write-Host "AUTOSAVE CADDY PRODUCCION: INTACTO"
 Write-Host "ADMIN_PROOF / API KEY ACADEMICA: INTACTAS"
 Write-Host "K-V: SOLO LOOPBACK 9444"
 Write-Host "CADDY PUBLICO: SIN MODIFICACIONES"
 Write-Host "CONTROL FISICO: OFF"
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO ROTACION K-V ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "ERROR DETALLADO OMITIDO: NO MOSTRAR CREDENCIALES" -ForegroundColor Yellow
 Write-Host "NO REPETIR ESTE PROCEDIMIENTO"
 # Never infer state only from the line following File.Replace: exceptions may
 # occur after the destination changes, or during follow-up verification.
 if($stopped -and -not $verified){
  $oldConfirmed=$false
  try{
   $oldConfirmed=(Test-Path -LiteralPath $configPath -PathType Leaf) -and
     ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $originalConfigHash)
  }catch{$oldConfirmed=$false}
  if($oldConfirmed){
   Write-Host "CONFIG ORIGINAL VERIFICADA: SE INTENTARA RECUPERAR K-V ORIGINAL" -ForegroundColor Yellow
   try{
    $t=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop
    if($t.State -ne "Running"){Start-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop}
    Check (WaitPort $true) "K-V original recuperado con config anterior intacta"
   }catch{
    Write-Host "NO-GO: K-V original no pudo recuperarse" -ForegroundColor Red
   }
  }else{
   Write-Host "CONFIG YA NO ES ORIGINAL: SE DETENDRA K-V SIN RESTAURAR TOKEN EXPUESTO" -ForegroundColor Red
   try{
    $t=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop
    if($t.State -eq "Running"){Stop-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Admission-Virtual" -ErrorAction Stop}
    Check (WaitPort $false) "K-V contenido; no se restaura token antiguo"
   }catch{
    Write-Host "NO-GO: no se pudo certificar la detencion de K-V" -ForegroundColor Red
   }
  }
 }
 Write-Host "CADDY / LEGACY NO DEBEN MODIFICARSE"
}
finally{
 if($null -ne $client){$client.Dispose()}
 $oldProof=$null;$newProof=$null;$adminProof=$null;$config=$null
 if(Test-Path -LiteralPath $staged){
  try{Remove-Item -LiteralPath $staged -Force -ErrorAction Stop
   Write-Host "OK: temporal privado nuevo retirado" -ForegroundColor Green
  }catch{Write-Host "NO-GO: temporal con credencial nueva pendiente" -ForegroundColor Red}
 }
 if(Test-Path -LiteralPath $rollbackBackup){
  try{
   # Contains OLD proof; remove even when the attempt did not complete.
   Remove-Item -LiteralPath $rollbackBackup -Force -ErrorAction Stop
   Write-Host "OK: respaldo temporal de token antiguo retirado" -ForegroundColor Green
  }catch{
   Write-Host "NO-GO: RESPALDO CON TOKEN ANTIGUO PENDIENTE EN ESTADO PRIVADO" -ForegroundColor Red
  }
 }
 if($null -ne $caddyHash -and (Test-Path -LiteralPath $caddyPath)){
  if((Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash -eq $caddyHash){
   Write-Host "OK: Hash Caddy publico intacto" -ForegroundColor Green
  }else{Write-Host "NO-GO: Hash Caddy publico distinto" -ForegroundColor Red}
 }
 Write-Host "SIN RELOAD CADDY, SIN CAMBIO DE PUERTOS, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X ROTACION ===" -ForegroundColor Cyan
}
