# K-X: Offline File.Replace forensic test on INERT test files, never on real config.
# Temporarily writes 4 dummy files into the protected service dir, removes all in finally.
# Does not print config, autosave, tokens, exception messages or full stack traces.
# Never restarts K-V, Caddy, API or touches hardware.
$ErrorActionPreference="Stop"
$service="C:\ProgramData\VehiculoIoT-KX-State\service"
$installer="C:\ProgramData\VehiculoIoT-KX-Installer"
$configPath=Join-Path $service "config.json"
$manifestPath=Join-Path $service "install.json"
$caddyPath="C:\ProgramData\VehiculoIoT\Caddyfile"
$backupPath=Join-Path $installer "kx_caddy_release_preflight\Caddyfile.original.copy"
$oldAutosave=Join-Path $env:APPDATA "Caddy\autosave.json"
$rotatorReport=Join-Path $installer "kx_proxy_proof_rotation_result.json"
$probeId=[guid]::NewGuid().ToString("N")
$files=@()
$originalHash=$null
$caddyHash=$null
$secret=$null
$done=$false
$clean=$true
$phase="PREFLIGHT"

function Check([bool]$test,[string]$message){
 if(-not $test){throw ("NO-GO: "+$message)}
 Write-Host ("OK: "+$message) -ForegroundColor Green
}
function NoReparse([string]$p,[string]$label){
 Check (Test-Path -LiteralPath $p) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $p -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin ruta redirigida: "+$label)
}
function ReadOnlyAclSummary([string]$p,[string]$label){
 $acl=Get-Acl -LiteralPath $p -ErrorAction Stop
 $broad=@("S-1-1-0","S-1-5-11","S-1-5-32-545")
 $readBit=[int][Security.AccessControl.FileSystemRights]::ReadData
 $writeBit=[int](
  [Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 $wide=0
 foreach($ace in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($ace.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
   $ace.IdentityReference.Value -in $broad -and
   ([int]$ace.FileSystemRights -band ($readBit -bor $writeBit)) -ne 0){
   $wide++
  }
 }
 Check ($wide -eq 0) ("Archivo de "+$label+" sin acceso amplio")
}
function DescribeError([Exception]$ex){
 $inner=if($null -ne $ex.InnerException){$ex.InnerException}else{$ex}
 $hex="0x"+([uint32]$inner.HResult).ToString("X8")
 Write-Host ("EXCEPCION_INTERNA_TIPO: "+$inner.GetType().Name)
 Write-Host ("EXCEPCION_INTERNA_HRESULT: "+$hex)
 Write-Host ("EXCEPCION_INTERNA_WIN32_LOW: "+([uint32]$inner.HResult -band 65535))
 Write-Host "MENSAJE ORIGINAL OMITIDO PARA EVITAR RUTAS O SECRETOS"
}
function RunProbe([string]$label,[bool]$ignoreMetadata,[Security.AccessControl.FileSecurity]$configAcl){
 $src=Join-Path $service ("KX_REPLACE_"+$probeId+"_"+$label+"_source.tmp")
 $dest=Join-Path $service ("KX_REPLACE_"+$probeId+"_"+$label+"_destination.tmp")
 $script:files+=@($src,$dest)
 Check (-not (Test-Path -LiteralPath $src) -and
  -not (Test-Path -LiteralPath $dest)) ("Archivos nuevos: "+$label)
 [IO.File]::WriteAllText($src,"DUMMY_NEW_"+$label,([Text.UTF8Encoding]::new($false)))
 [IO.File]::WriteAllText($dest,"DUMMY_OLD_"+$label,([Text.UTF8Encoding]::new($false)))
 Set-Acl -LiteralPath $dest -AclObject $configAcl -ErrorAction Stop
 ReadOnlyAclSummary $src ($label+" origen")
 ReadOnlyAclSummary $dest ($label+" destino con ACL de config")
 try {
  if($ignoreMetadata){
   [IO.File]::Replace($src,$dest,$null,$true)
  }else{
   [IO.File]::Replace($src,$dest,$null)
  }
  $new=[IO.File]::ReadAllText($dest)
  Check ($new -ceq ("DUMMY_NEW_"+$label)) ("Contenido de prueba cambiado correctamente: "+$label)
  ReadOnlyAclSummary $dest ("resultado "+$label)
  Write-Host ("RESULTADO "+$label+": PASS") -ForegroundColor Green
 }catch{
  Write-Host ("RESULTADO "+$label+": ERROR") -ForegroundColor Yellow
  DescribeError $_.Exception
 }
}
Write-Host ""
Write-Host "=== K-X: DIAGNOSTICO AISLADO DE FILE.REPLACE, SIN ROTAR ===" -ForegroundColor Cyan
try{
 $current=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($path in @($installer,$service,$configPath,$manifestPath,$caddyPath,$backupPath,$oldAutosave)){
  NoReparse $path ([IO.Path]::GetFileName($path))
 }
 Check ((Get-Acl -LiteralPath $installer).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $service).AreAccessRulesProtected) "Directorios privados protegidos"
 Check (-not (Test-Path -LiteralPath $rotatorReport)) "Rotacion sin informe de PASS"
 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and
  $m.physical_control_enabled -eq $false -and
  $m.caddy_changed -eq $false) "K-V sigue virtual y no publicado"
 $originalHash=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
 $caddyHash=(Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash
 Check ($caddyHash -eq $m.original_caddy_sha256 -and
  $caddyHash -eq (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash) "Caddy y respaldo sin cambios"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea funcionando: "+$name)
 }
 $kv=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V recuperado en loopback"
 $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$kv[0].OwningProcess)
 Check ((Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid).Sid -eq $m.dedicated_sid) "Identidad de K-V recuperada"
 $cfg=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
 Check ($cfg.mode -eq "virtual_loopback_only" -and
  $cfg.proxy_proof -cmatch "^[A-Za-z0-9_-]{64}$") "Config K-V anterior intacta"
 $secret=[string]$cfg.proxy_proof
 $cfg=$null
 Check (([IO.File]::ReadAllText($oldAutosave)).Contains($secret)) "Token anterior permanece en autosave sin modificar"
 $secret=$null
 $configAttrs=(Get-Item -LiteralPath $configPath -Force).Attributes
 Write-Host ("CONFIG REAL: READ_ONLY="+[bool]($configAttrs -band [IO.FileAttributes]::ReadOnly)+
  "; ENCRYPTED="+[bool]($configAttrs -band [IO.FileAttributes]::Encrypted)+
  "; REPARSE="+[bool]($configAttrs -band [IO.FileAttributes]::ReparsePoint))
 $security=Get-Acl -LiteralPath $configPath -ErrorAction Stop
 ReadOnlyAclSummary $configPath "config original"

 Write-Host ""
 Write-Host "=== PROBANDO REEMPLAZO EN ARCHIVOS FICTICIOS ===" -ForegroundColor Cyan
 $phase="PROBES"
 RunProbe "THREE_ARGUMENTS" $false $security
 RunProbe "FOUR_IGNORE_METADATA" $true $security
 $done=$true
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO PRECHECK REPLACE ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase)
 DescribeError $_.Exception
 Write-Host "NO REINTENTAR ROTACION NI MODIFICAR CONFIG"
}
finally{
 Write-Host ""
 Write-Host "=== LIMPIEZA DE ARCHIVOS FICTICIOS ===" -ForegroundColor Cyan
 foreach($path in @($files | Select-Object -Unique)){
  if(Test-Path -LiteralPath $path){
   try{
    Remove-Item -LiteralPath $path -Force -ErrorAction Stop
   }catch{
    $clean=$false
    Write-Host "NO-GO: Archivo ficticio pendiente de limpieza" -ForegroundColor Red
   }
  }
 }
 if($clean){Write-Host "OK: Archivos de prueba eliminados" -ForegroundColor Green}
 if($null -ne $originalHash -and (Test-Path -LiteralPath $configPath)){
  if((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $originalHash){
   Write-Host "OK: Config K-V REAL intacta" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Config K-V REAL difiere" -ForegroundColor Red}
 }
 if($null -ne $caddyHash -and (Test-Path -LiteralPath $caddyPath)){
  if((Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash -eq $caddyHash){
   Write-Host "OK: Caddy original intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Caddy original difiere" -ForegroundColor Red}
 }
 if($done -and $clean){
  Write-Host ""
  Write-Host "=== RESULTADO: DIAGNOSTICO FILE.REPLACE COMPLETADO ===" -ForegroundColor Green
  Write-Host "LAS DOS PRUEBAS USARON SOLO CONTENIDO FICTICIO"
  Write-Host "K-V: SIN DETENER NI REINICIAR"
  Write-Host "CONFIG ORIGINAL: SIN REEMPLAZAR"
  Write-Host "ROTACION: PENDIENTE"
  Write-Host "AUTOSAVE ANTIGUO: SIN ELIMINAR"
  Write-Host "CONTROL FISICO: OFF"
 }else{
  Write-Host "=== RESULTADO: DIAGNOSTICO INCOMPLETO / LIMPIEZA NO-GO ===" -ForegroundColor Red
 }
 Write-Host "SIN RELOAD, RESTART, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X REPLACE DIAGNOSTICO ===" -ForegroundColor Cyan
}
