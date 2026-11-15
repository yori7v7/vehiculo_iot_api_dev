# K-X V2: disposable NTFS regression test of the EXACT live common.ps1 process-record writer.
# Test uses ONLY files in a unique private sandbox; no task, secret, Caddy, HTTP or port changes.
# Specifically checks original second Write-VehicleProcessRecord update calling [IO.File]::Replace(...,[NullString]::Value).
# Do not confuse the result with a live Caddy restart.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$source="C:\vehiculo_iot_api_dev\deploy\windows\common.ps1"
$manifestPath="C:\ProgramData\VehiculoIoT-KX-State\service\install.json"
$liveCaddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$liveLauncher="C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1"
$gate="C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_public_release_v1_offline\launcher_staging_v1\system_proof_dryrun_result.json"
$baseline="C:\ProgramData\VehiculoIoT-KX-Installer\kx_system_caddy_local_once_result.json"
$testDir=Join-Path $root ("kx_dummy_process_record_probe_"+[guid]::NewGuid().ToString("N"))
$testFile=Join-Path $testDir "processrecord.DUMMY.json"
$backupFile=Join-Path $testDir "processrecord.DUMMY.old-backup.json"
$liveHash=$null
$launcherHash=$null
$sourceHash=$null
$done=$false
$clean=$true
$noReparse=$false
$phase="PREFLIGHT"
function Check([bool]$pass,[string]$label) {
 if(-not $pass){throw "NO-GO: "+$label}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function ErrorClass([Exception]$e) {
 $inner=if($null -ne $e.InnerException){$e.InnerException}else{$e}
 $hr=[long]$inner.HResult -band 4294967295
 Write-Host ("EXCEPCION_INTERNA: "+$inner.GetType().Name) -ForegroundColor Yellow
 Write-Host ("HRESULT: 0x"+$hr.ToString("X8")) -ForegroundColor Yellow
 Write-Host ("WIN32_LOW: "+($hr -band 65535)) -ForegroundColor Yellow
 Write-Host "MENSAJE ORIGINAL OMITIDO; SIN DATOS SENSIBLES"
}
function NoReparse([string]$path,[string]$description){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$description)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$description)
}
Write-Host ""
Write-Host "=== K-X V2: PRUEBA NTFS DE REGISTRO DE PROCESO, SOLO FICTICIA ===" -ForegroundColor Cyan
try {
 $admin=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$source,$manifestPath,$liveCaddy,$liveLauncher,$gate,$baseline)){
  NoReparse $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador privado"
 Check (-not (Test-Path -LiteralPath $testDir)) "Ruta ficticia nueva disponible"
 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and
  $m.caddy_changed -eq $false -and
  $m.physical_control_enabled -eq $false) "K-V sigue virtual, no publicado"
 $gateData=Get-Content -LiteralPath $gate -Raw|ConvertFrom-Json
 Check ($gateData.mode -eq "system_real_identity_launcher_proof_dryrun_not_activated" -and
  $gateData.temporary_system_task_removed -eq $true) "Prueba SYSTEM del lector aprobada"
 $labData=Get-Content -LiteralPath $baseline -Raw|ConvertFrom-Json
 Check ($labData.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $labData.real_proxy_proof_saved_to_file -eq $false -and
  $labData.production_caddy_modified -eq $false) "Caddy real SYSTEM local aprobado"
 $liveHash=(Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash
 $launcherHash=(Get-FileHash -LiteralPath $liveLauncher -Algorithm SHA256).Hash
 $sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
 Check ($liveHash -eq $m.original_caddy_sha256) "Caddy original intacto"
 Check ($launcherHash -eq "873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1") "Lanzador original intacto"
 foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Tarea original: "+$taskName)
 }
 Check (@(Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "HTTPS original funciona"
 Check (@(Get-NetTCPConnection -LocalPort 9481 -State Listen -ErrorAction SilentlyContinue).Count -eq 0) "Puerto laboratorio libre"

 $tokens=$null;$errors=$null
 $ast=[System.Management.Automation.Language.Parser]::ParseFile(
  $source,[ref]$tokens,[ref]$errors)
 Check (@($errors).Count -eq 0) "Helper real PowerShell parseable"
 $defs=@($ast.FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
   $node.Name -ceq "Write-VehicleProcessRecord"
 },$true))
 Check ($defs.Count -eq 1) "Una sola funcion exacta de escritura de procesos"
 $functionSource=$defs[0].Extent.Text
 Check ($functionSource.Contains('[IO.File]::Replace($temporary, $Path, [NullString]::Value)')) "Metodo original File.Replace detectado"
 Check ($functionSource.Contains('Set-Content -LiteralPath $temporary -Encoding UTF8')) "Temporal del registro original detectado"
 Check ($functionSource.Contains('[IO.File]::Move($temporary, $Path)')) "Creacion original detectada"
 $statements=@($defs[0].FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.CommandAst]
 },$true)|ForEach-Object{$_.GetCommandName()})
 Check (@($statements | Where-Object{$_ -notin @("param","Set-Content","ConvertTo-Json","Test-Path")}).Count -eq 0) "Funcion aislada sin operaciones externas"
 . ([ScriptBlock]::Create($functionSource))

 Write-Host ""
 Write-Host "=== CREANDO ARCHIVOS DUMMY PRIVADOS ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $testDir -ErrorAction Stop|Out-Null
 & icacls.exe $testDir /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia NTFS retirada"
 & icacls.exe $testDir /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Archivos dummy solo SYSTEM/Administradores"
 Check ((Get-Acl -LiteralPath $testDir).AreAccessRulesProtected) "Directorio ficticio privado"
 $first=[ordered]@{phase="supervisor";mock_id=111;test="K-X-DUMMY"}
 $second=[ordered]@{phase="child";mock_id=222;test="K-X-DUMMY"}
 $phase="FIRST_WRITE"
 Write-VehicleProcessRecord -Path $testFile -Record $first
 Check (Test-Path -LiteralPath $testFile -PathType Leaf) "Creacion inicial dummy con funcion real"
 Check ((Get-Content -LiteralPath $testFile -Raw|ConvertFrom-Json).phase -ceq "supervisor") "Contenido dummy inicial correcto"
 $initialHash=(Get-FileHash -LiteralPath $testFile -Algorithm SHA256).Hash
 $phase="SECOND_WRITE"
 Write-Host ""
 Write-Host "=== REEMPLAZO DUMMY CON LA MISMA FUNCION DE PRODUCCION ===" -ForegroundColor Cyan
 try{
  Write-VehicleProcessRecord -Path $testFile -Record $second
  $content=Get-Content -LiteralPath $testFile -Raw|ConvertFrom-Json
  Check ($content.phase -ceq "child") "Contenido dummy actualizado"
  Write-Host "SEGUNDA ESCRITURA ORIGINAL: PASS" -ForegroundColor Green
 }catch{
  Write-Host "SEGUNDA ESCRITURA ORIGINAL: ERROR" -ForegroundColor Yellow
  ErrorClass $_.Exception
  Check ((Get-FileHash -LiteralPath $testFile -Algorithm SHA256).Hash -eq $initialHash) "El registro ficticio original sobrevivio al error"
 }
 $phase="EXPLICIT_BACKUP_DUMMY"
 Write-Host ""
 Write-Host "=== CONTROL FILE.REPLACE CON RESPALDO EXPLICITO FICTICIO ===" -ForegroundColor Cyan
 $third=Join-Path $testDir "processrecord.NEW_DUMMY.tmp"
 [IO.File]::WriteAllText($third,'{"phase":"third","test":"K-X-DUMMY"}',([Text.UTF8Encoding]::new($false)))
 Check (-not (Test-Path -LiteralPath $backupFile)) "Backup ficticio nuevo"
 [IO.File]::Replace($third,$testFile,$backupFile)
 Check ([IO.File]::ReadAllText($testFile).Contains('"third"')) "Reemplazo explicito del dummy correcto"
 Check (Test-Path -LiteralPath $backupFile -PathType Leaf) "Backup dummy creado"
 Remove-Item -LiteralPath $backupFile -Force -ErrorAction Stop
 Check (-not (Test-Path -LiteralPath $backupFile)) "Backup ficticio eliminado"
 $done=$true
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO PRUEBA REGISTRO PROCESO ===" -ForegroundColor Red
 Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
 ErrorClass $_.Exception
 Write-Host "NO PUBLICAR NI REINICIAR CADDY"
}
finally{
 Write-Host ""
 Write-Host "=== LIMPIEZA PRUEBA DE REGISTRO ===" -ForegroundColor Cyan
 if(Test-Path -LiteralPath $testDir){
  try{
   Remove-Item -LiteralPath $testDir -Force -Recurse -ErrorAction Stop
   Write-Host "OK: TODOS los archivos dummy eliminados" -ForegroundColor Green
  }catch{
   $clean=$false
   Write-Host "NO-GO: dummy pendiente de limpieza" -ForegroundColor Red
  }
 }
 if($null -ne $sourceHash -and (Test-Path -LiteralPath $source)){
  if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -eq $sourceHash){
   Write-Host "OK: common.ps1 REAL intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: common.ps1 REAL difiere" -ForegroundColor Red}
 }
 if($null -ne $launcherHash -and (Test-Path -LiteralPath $liveLauncher)){
  if((Get-FileHash -LiteralPath $liveLauncher -Algorithm SHA256).Hash -eq $launcherHash){
   Write-Host "OK: run_caddy.ps1 REAL intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: run_caddy.ps1 REAL difiere" -ForegroundColor Red}
 }
 if($null -ne $liveHash -and (Test-Path -LiteralPath $liveCaddy)){
  if((Get-FileHash -LiteralPath $liveCaddy -Algorithm SHA256).Hash -eq $liveHash){
   Write-Host "OK: Caddyfile REAL intacto" -ForegroundColor Green
  }else{$clean=$false;Write-Host "NO-GO: Caddyfile REAL difiere" -ForegroundColor Red}
 }
 if($done -and $clean) {
  Write-Host ""
  Write-Host "=== RESULTADO: DIAGNOSTICO RECORD WRITER DUMMY V2 COMPLETO ===" -ForegroundColor Green
  Write-Host "LEER: SEGUNDA ESCRITURA ORIGINAL PASS O ERROR"
  Write-Host "EXPLICIT BACKUP DUMMY: PASS"
  Write-Host "CADDY, TAREAS, API, K-V: INTACTOS"
  Write-Host "PUBLICACION K-V: PENDIENTE"
  Write-Host "CONTROL FISICO: OFF"
 }else{
  Write-Host "=== RESULTADO: DIAGNOSTICO INCOMPLETO ===" -ForegroundColor Red
 }
 Write-Host "SIN START/STOP/RELOAD/HTTP/RDS/ESP/MOTORES"
 Write-Host "=== FIN K-X RECORD WRITER DUMMY V2 ===" -ForegroundColor Cyan
}
