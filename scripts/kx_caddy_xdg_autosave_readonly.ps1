# K-X: exact redirected Caddy autosave and delegated process launcher, READ ONLY.
# Never prints command-line arguments, config JSON, secrets, or file contents.
$ErrorActionPreference = "Stop"
$project="C:\vehiculo_iot_api_dev"
$launcher=Join-Path $project "deploy\windows\run_caddy.ps1"
$common=Join-Path $project "deploy\windows\common.ps1"
$state="C:\ProgramData\VehiculoIoT"
$caddyfile=Join-Path $state "Caddyfile"
$deployment=Join-Path $state "deployment.json"
$autosaveDir=Join-Path $state "caddy-config\caddy"
$autosave=Join-Path $autosaveDir "autosave.json"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$manifest=Join-Path "C:\ProgramData\VehiculoIoT-KX-State\service" "install.json"
$backup=Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$report=Join-Path $root "kx_real_caddy_local_contract.json"
$expectedLauncherHash="873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1"

function Pass([bool]$predicate,[string]$message) {
 if(-not $predicate){throw ("NO-GO: "+$message)}
 Write-Host ("OK: "+$message) -ForegroundColor Green
}
function No-Reparse([string]$p,[string]$label) {
 Pass (Test-Path -LiteralPath $p) ("Existe: "+$label)
 Pass (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin redireccion: "+$label)
}
function ACL-Restricted([string]$p,[string]$label) {
 $acl=Get-Acl -LiteralPath $p -ErrorAction Stop
 $broad=@("S-1-1-0","S-1-5-11","S-1-5-32-545")
 $risky=0
 $readMask=[int](
  [Security.AccessControl.FileSystemRights]::ReadData -bor
  [Security.AccessControl.FileSystemRights]::ReadPermissions)
 $writeMask=[int](
  [Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow){continue}
  if($rule.IdentityReference.Value -notin $broad){continue}
  if(([int]$rule.FileSystemRights -band ($readMask -bor $writeMask)) -ne 0){$risky++}
 }
 Write-Host ("ACL: "+$label+"; HERENCIA_PROTEGIDA="+$acl.AreAccessRulesProtected+"; ACE_AMPLIAS="+$risky)
 Pass ($risky -eq 0) ("Sin acceso amplio a configuracion: "+$label)
}

Write-Host ""
Write-Host "=== K-X: AUDITORIA XDG CADDY AUTOSAVE REDIRIGIDO ===" -ForegroundColor Cyan
try{
 $user=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Pass ($user.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($item in @($launcher,$common,$state,$caddyfile,$deployment,$root,$manifest,$backup,$report)){
  No-Reparse $item ([IO.Path]::GetFileName($item))
 }
 $m=Get-Content -LiteralPath $manifest -Raw|ConvertFrom-Json
 $r=Get-Content -LiteralPath $report -Raw|ConvertFrom-Json
 Pass ($m.mode -eq "loopback_only_not_public" -and
  $m.physical_control_enabled -eq $false -and $m.caddy_changed -eq $false) "K-V no publicado"
 Pass ($r.mode -eq "local_caddy_real_kv_get_only" -and
  $r.public_https_tested -eq $false -and
  $r.candidate_enabled_in_production -eq $false) "Integracion local previa certificada"
 $hash=(Get-FileHash -LiteralPath $caddyfile -Algorithm SHA256).Hash
 Pass ($hash -eq $m.original_caddy_sha256 -and
  $hash -eq (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash) "Caddy productivo y respaldo conservados"
 Pass ((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq $expectedLauncherHash) "Lanzador exacto previamente auditado"

 Write-Host ""
 Write-Host "=== VERIFICANDO DELEGACION Y RUTAS XDG ===" -ForegroundColor Cyan
 $launchContent=Get-Content -LiteralPath $launcher -Raw
 $commonContent=Get-Content -LiteralPath $common -Raw
 Pass ($launchContent.Contains("Set-VehicleCaddyEnvironment") -and
  $launchContent.Contains("Invoke-VehicleProcess")) "Lanzador delega en funciones compartidas"
 Pass ($commonContent.Contains("function Set-VehicleCaddyEnvironment") -and
  $commonContent.Contains("function Invoke-VehicleProcess")) "Funciones compartidas presentes"
 Pass ($commonContent.Contains("Join-Path " + [char]36 + "StateDirectory 'caddy-config'") -and
  $commonContent.Contains("Join-Path " + [char]36 + "StateDirectory 'caddy-data'")) "XDG_CONFIG_HOME y XDG_DATA_HOME asignados"
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 Pass ($task.State -eq "Running" -and @($task.Actions).Count -eq 1) "Tarea Caddy sin cambios"
 Pass (([string]$task.Actions[0].Arguments).Contains($launcher) -and
  ([string]$task.Actions[0].Arguments).Contains($state)) "Tarea ejecuta lanzador y StateDirectory esperados"
 $deploy=Get-Content -LiteralPath $deployment -Raw|ConvertFrom-Json
 Pass ($deploy.state_directory -eq $state -and
  $deploy.caddyfile_path -eq $caddyfile) "deployment.json identifica la misma instalacion"

 Write-Host ""
 Write-Host "=== EXAMINANDO DESTINO AUTOSAVE CONOCIDO ===" -ForegroundColor Cyan
 Write-Host ("AUTOSAVE ESPERADO: "+$autosave)
 if(-not (Test-Path -LiteralPath $autosaveDir -PathType Container)){
  Write-Host "OBSERVACION: CARPETA caddy-config\caddy NO EXISTE" -ForegroundColor Yellow
 } else {
  No-Reparse $autosaveDir "Directorio autosave"
  ACL-Restricted $autosaveDir "Carpeta autosave"
 }
 if(Test-Path -LiteralPath $autosave -PathType Leaf){
  No-Reparse $autosave "autosave.json"
  ACL-Restricted $autosave "Archivo autosave"
  $raw=Get-Content -LiteralPath $autosave -Raw
  $parsed=$raw | ConvertFrom-Json
  Pass ($null -ne $parsed) "Autosave JSON legible y valido"
  Write-Host "AUTOSAVE: ENCONTRADO"
  Write-Host ("AUTOSAVE SHA256: "+(Get-FileHash -LiteralPath $autosave -Algorithm SHA256).Hash)
  Write-Host ("AUTOSAVE CONTIENE K-V HEADER: "+[bool]($raw -match 'X-Admission-Proxy-Token'))
  Write-Host "AUTOSAVE JSON / VALORES / TOKENS: NO MOSTRADOS"
  $raw=$null
  $parsed=$null
 } else {
  Write-Host "AUTOSAVE: NO ENCONTRADO EN RUTA XDG" -ForegroundColor Yellow
  Write-Host "NO-GO PARA PUBLICACION: investigar autosave no encontrado"
 }
 $admin=@(Get-NetTCPConnection -State Listen -LocalPort 2019 -ErrorAction SilentlyContinue)
 Pass (@($admin|Where-Object{$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "API administrativa 2019 no expuesta"
 $kv=@(Get-NetTCPConnection -State Listen -LocalPort 9444 -ErrorAction SilentlyContinue)
 Pass ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V solo loopback"
 Pass ((Get-FileHash -LiteralPath $caddyfile -Algorithm SHA256).Hash -eq $hash) "Caddyfile original sin cambios"
 Write-Host ""
 Write-Host "=== RESULTADO: AUDITORIA XDG AUTOSAVE COMPLETADA ===" -ForegroundColor Green
 Write-Host "LANZADOR: DELEGA A Invoke-VehicleProcess"
 Write-Host "CADDY: RUTAS XDG DEFINIDAS POR common.ps1"
 Write-Host "SECRETOS: NO MOSTRADOS"
 Write-Host "K-V PUBLICO: NO ACTIVADO"
 Write-Host "CONTROL FISICO: OFF"
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO AUDITORIA XDG ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO PUBLICAR NI CAMBIAR CADDY"
}
finally{
 Write-Host "SIN ESCRITURAS, HTTP, RELOAD, RESTART, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X AUDITORIA XDG ===" -ForegroundColor Cyan
}
