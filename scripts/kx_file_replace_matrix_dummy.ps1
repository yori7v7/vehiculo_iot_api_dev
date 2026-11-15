# K-X: diag File.Replace matrix on INERT dummy files only.
# Never touches K-V config.json, Caddy config, task state, credential, or autosave.
# Creates disposable dummy files under private K-V service directory; removes all in finally.
# Output contains no secret material, no raw Windows exception text.
$ErrorActionPreference="Stop"
$service="C:\ProgramData\VehiculoIoT-KX-State\service"
$installer="C:\ProgramData\VehiculoIoT-KX-Installer"
$manifest=Join-Path $service "install.json"
$config=Join-Path $service "config.json"
$backupCaddy=Join-Path $installer "kx_caddy_release_preflight\Caddyfile.original.copy"
$caddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$rotated=Join-Path $installer "kx_proxy_proof_rotation_result.json"
$beforeConfig=$null
$beforeCaddy=$null
$testId=[guid]::NewGuid().ToString("N")
$dummyFiles=New-Object 'System.Collections.Generic.List[string]'
$failures=0
$completed=0
$clean=$true
$preflight=$false
$phase="PREFLIGHT"
function Check([bool]$pass,[string]$label){
 if(-not $pass){throw "NO-GO: $label"}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function NoReparse([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$label)
}
function GetBits([int]$permissions){
 $r=[int][Security.AccessControl.FileSystemRights]::ReadData
 $w=[int]([Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 return (($permissions -band ($r -bor $w)) -ne 0)
}
function BroadAllowCount([string]$path){
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $count=0
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $rule.IdentityReference.Value -in @("S-1-1-0","S-1-5-11","S-1-5-32-545") -and
   (GetBits ([int]$rule.FileSystemRights))){
   $count++
  }
 }
 return $count
}
function ErrorSummary([Exception]$outer){
 $inner=if($null -ne $outer.InnerException){$outer.InnerException}else{$outer}
 $hr=[long]$inner.HResult -band 4294967295
 Write-Host ("EXCEPCION_INTERNA_TIPO: "+$inner.GetType().Name) -ForegroundColor Yellow
 Write-Host ("EXCEPCION_INTERNA_HRESULT: 0x"+$hr.ToString("X8")) -ForegroundColor Yellow
 Write-Host ("EXCEPCION_WIN32_LOW: "+($hr -band 65535)) -ForegroundColor Yellow
 Write-Host "MENSAJE ORIGINAL OMITIDO, SIN DATOS SENSIBLES"
}
function Test-Replace([string]$label,[bool]$cloneACL,[bool]$createBackup,[bool]$ignoreMetadata,
 [Security.AccessControl.FileSecurity]$security){
 $src=Join-Path $service ("KX_MATRIX_"+$testId+"_"+$label+"_source.tmp")
 $dest=Join-Path $service ("KX_MATRIX_"+$testId+"_"+$label+"_destination.tmp")
 $bak=Join-Path $service ("KX_MATRIX_"+$testId+"_"+$label+"_backup.tmp")
 $script:dummyFiles.Add($src)
 $script:dummyFiles.Add($dest)
 $script:dummyFiles.Add($bak)
 Check (-not (Test-Path -LiteralPath $src) -and
   -not (Test-Path -LiteralPath $dest) -and
   -not (Test-Path -LiteralPath $bak)) ("Archivos de prueba exclusivos: "+$label)
 [IO.File]::WriteAllText($src,("DUMMY_NEW_"+$label),([Text.UTF8Encoding]::new($false)))
 [IO.File]::WriteAllText($dest,("DUMMY_OLD_"+$label),([Text.UTF8Encoding]::new($false)))
 if($cloneACL){
  Set-Acl -LiteralPath $dest -AclObject $security -ErrorAction Stop
 }
 Check ((BroadAllowCount $src) -eq 0 -and (BroadAllowCount $dest) -eq 0) ("Sin permisos amplios: "+$label)
 $sourceBefore=(Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
 $destBefore=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
 Write-Host ""
 Write-Host ("=== PRUEBA: "+$label+" ===") -ForegroundColor Cyan
 Write-Host ("ACL CLONADA: "+$cloneACL+"; BACKUP EXPLICITO: "+$createBackup+
  "; IGNORE_METADATA: "+$ignoreMetadata)
 try{
  $backupArg=if($createBackup){$bak}else{$null}
  if($ignoreMetadata){
   [IO.File]::Replace($src,$dest,$backupArg,$true)
  }else{
   [IO.File]::Replace($src,$dest,$backupArg)
  }
  Check (-not (Test-Path -LiteralPath $src)) ("Origen consumido: "+$label)
  Check ([IO.File]::ReadAllText($dest) -ceq ("DUMMY_NEW_"+$label)) ("Destino contiene DUMMY_NEW: "+$label)
  if($createBackup){
   Check (Test-Path -LiteralPath $bak -PathType Leaf) ("Backup creado: "+$label)
   Check ([IO.File]::ReadAllText($bak) -ceq ("DUMMY_OLD_"+$label)) ("Backup contiene DUMMY_OLD: "+$label)
  }else{
   Check (-not (Test-Path -LiteralPath $bak)) ("Sin backup requerido: "+$label)
  }
  Check ((BroadAllowCount $dest) -eq 0) ("ACL destino segura: "+$label)
  Write-Host ("RESULTADO "+$label+": PASS") -ForegroundColor Green
 }catch{
  $script:failures++
  Write-Host ("RESULTADO "+$label+": ERROR") -ForegroundColor Yellow
  ErrorSummary $_.Exception
  $sourceAfter=if(Test-Path -LiteralPath $src){(Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash}else{"MISSING"}
  $destAfter=if(Test-Path -LiteralPath $dest){(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash}else{"MISSING"}
  $backupExists=Test-Path -LiteralPath $bak
  Write-Host ("DUMMY_SOURCE_UNCHANGED: "+($sourceAfter -eq $sourceBefore))
  Write-Host ("DUMMY_DEST_UNCHANGED: "+($destAfter -eq $destBefore))
  Write-Host ("DUMMY_BACKUP_CREATED: "+$backupExists)
 }
 $script:completed++
}
Write-Host ""
Write-Host "=== K-X: MATRIZ FILE.REPLACE EN ARCHIVOS FICTICIOS ===" -ForegroundColor Cyan
try {
 $user=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($user.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($path in @($service,$installer,$manifest,$config,$caddy,$backupCaddy)){
  NoReparse $path ([IO.Path]::GetFileName($path))
 }
 Check ((Get-Acl -LiteralPath $service).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $installer).AreAccessRulesProtected) "Directorios de K-V protegidos"
 Check (-not (Test-Path -LiteralPath $rotated)) "Rotacion pendiente: sin reporte exitoso"
 $m=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and
  $m.caddy_changed -eq $false -and
  $m.physical_control_enabled -eq $false) "K-V en modo virtual, sin publicar"
 $beforeConfig=(Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash
 $beforeCaddy=(Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash
 Check ($beforeCaddy -eq $m.original_caddy_sha256 -and
  $beforeCaddy -eq (Get-FileHash -LiteralPath $backupCaddy -Algorithm SHA256).Hash) "Caddy productivo y respaldo intactos"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea intacta: "+$name)
 }
 $kv=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V exclusivamente loopback"
 $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$kv[0].OwningProcess) -ErrorAction Stop
 Check ((Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop).Sid -eq
  $m.dedicated_sid) "Identidad K-V dedicada intacta"
 $acl=Get-Acl -LiteralPath $config -ErrorAction Stop
 Check ((BroadAllowCount $config) -eq 0) "Config.json sin permisos amplios"
 $volume=Get-Volume -DriveLetter "C" -ErrorAction SilentlyContinue
 if($null -ne $volume){Write-Host ("SISTEMA ARCHIVOS VOLUMEN C: "+$volume.FileSystem)}
 $preflight=$true
 $phase="DUMMY_MATRIX"
 Write-Host ""
 Write-Host "=== CINCO PRUEBAS SIN USAR CONFIG REAL ===" -ForegroundColor Cyan
 Test-Replace "BASE_NULL" $false $false $false $acl
 Test-Replace "BASE_BACKUP" $false $true $false $acl
 Test-Replace "CLONE_NULL" $true $false $false $acl
 Test-Replace "CLONE_BACKUP" $true $true $false $acl
 Test-Replace "CLONE_BACKUP_IGNORE" $true $true $true $acl
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO MATRIZ NTFS ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 ErrorSummary $_.Exception
 Write-Host "NO REINTENTAR ROTACION, NO MODIFICAR CONFIG" -ForegroundColor Red
}
finally {
 Write-Host ""
 Write-Host "=== LIMPIEZA DE ARCHIVOS FICTICIOS ===" -ForegroundColor Cyan
 foreach($path in $dummyFiles){
  if(Test-Path -LiteralPath $path){
   try {Remove-Item -LiteralPath $path -Force -ErrorAction Stop}
   catch {
    $clean=$false
    Write-Host "NO-GO: archivo ficticio pendiente de limpieza" -ForegroundColor Red
   }
  }
 }
 if($clean){Write-Host "OK: todos los archivos ficticios eliminados" -ForegroundColor Green}
 if($null -ne $beforeConfig -and (Test-Path -LiteralPath $config)){
  if((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $beforeConfig){
   Write-Host "OK: config.json REAL intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: config.json REAL cambiado" -ForegroundColor Red}
 }
 if($null -ne $beforeCaddy -and (Test-Path -LiteralPath $caddy)){
  if((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $beforeCaddy){
   Write-Host "OK: Caddy REAL intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Caddy REAL cambiado" -ForegroundColor Red}
 }
 if($preflight -and $completed -eq 5 -and $clean){
  Write-Host ""
  Write-Host "=== RESULTADO: MATRIZ FILE.REPLACE COMPLETA ===" -ForegroundColor Green
  Write-Host ("PRUEBAS EJECUTADAS: "+$completed)
  Write-Host ("PRUEBAS CON ERROR: "+$failures)
  Write-Host "ARCHIVOS: TODOS FICTICIOS"
  Write-Host "SERVICIOS: NO DETENIDOS"
  Write-Host "ROTACION DE PROXY_PROOF: PENDIENTE"
  Write-Host "AUTOSAVE ANTIGUO: INTACTO"
  Write-Host "CONTROL FISICO: OFF"
 }else{Write-Host "=== RESULTADO: MATRIZ INCOMPLETA / LIMPIEZA NO-GO ===" -ForegroundColor Red}
 Write-Host "SIN RELOAD, RESTART, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X MATRIZ NTFS ===" -ForegroundColor Cyan
}
