# K-X: pre-publication Caddy PowerShell launcher and autosave inventory.
# READ ONLY: does not start, reload, stop, write, or change task/process/config.
# Never prints full arguments, script contents, environment values or tokens.
$ErrorActionPreference = "Stop"
$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$state = "C:\ProgramData\VehiculoIoT-KX-State\service"
$caddyFile = "C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestFile = Join-Path $state "install.json"
$certFile = Join-Path $root "kx_postboot_verified.json"
$backupTask = Join-Path $root "kx_caddy_release_preflight\VehiculoIoT-Caddy.task.xml"
$backupFile = Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$integrationFile = Join-Path $root "kx_real_caddy_local_contract.json"

function Check([bool]$condition,[string]$message) {
 if(-not $condition){throw ("NO-GO: "+$message)}
 Write-Host ("OK: "+$message) -ForegroundColor Green
}
function Sid([string]$account){
 if($account -match '^S-1-[0-9]+(?:-[0-9]+)+$'){return $account}
 return ([Security.Principal.NTAccount]::new($account)).Translate(
  [Security.Principal.SecurityIdentifier]).Value
}
function Get-Ps1Path([string]$text){
 $rx = @(
  '(?i)"(?<path>[A-Z]:\\[^"]+?\.ps1)"',
  "(?i)'(?<path>[A-Z]:\\[^']+?\.ps1)'",
  '(?i)(?<path>[A-Z]:\\[^\s"'';]+?\.ps1)'
 )
 foreach($p in $rx){
  $m=[regex]::Match($text,$p)
  if($m.Success){return [string]$m.Groups["path"].Value}
 }
 return $null
}
function Inspect-RiskyACL([string]$target){
 $acl=Get-Acl -LiteralPath $target -ErrorAction Stop
 $unsafe=@()
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  $sidValue=$rule.IdentityReference.Value
  $flags=[int]$rule.FileSystemRights
  $writeFlags=[int]([Security.AccessControl.FileSystemRights]::Write -bor
   [Security.AccessControl.FileSystemRights]::Modify -bor
   [Security.AccessControl.FileSystemRights]::FullControl -bor
   [Security.AccessControl.FileSystemRights]::WriteData -bor
   [Security.AccessControl.FileSystemRights]::AppendData -bor
   [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
   [Security.AccessControl.FileSystemRights]::TakeOwnership)
  if($rule.AccessControlType -eq "Allow" -and ($flags -band $writeFlags) -ne 0 -and
   $sidValue -in @("S-1-1-0","S-1-5-11","S-1-5-32-545")){
   $unsafe+=1
  }
 }
 return [pscustomobject]@{
  protected=$acl.AreAccessRulesProtected
  broad_write_entries=$unsafe.Count
 }
}
Write-Host ""
Write-Host "=== K-X: AUDITORIA LANZADOR CADDY Y AUTOSAVE ===" -ForegroundColor Cyan
try {
 $p=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($file in @($root,$state,$caddyFile,$manifestFile,$certFile,
  $backupTask,$backupFile,$integrationFile)){
  Check (Test-Path -LiteralPath $file) "Evidencia requerida presente"
  Check (((Get-Item -LiteralPath $file -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta sin redireccion"
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected -and
  (Get-Acl -LiteralPath $state).AreAccessRulesProtected) "Directorios K-X protegidos"
 $manifest=Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
 $cert=Get-Content -LiteralPath $certFile -Raw | ConvertFrom-Json
 $integration=Get-Content -LiteralPath $integrationFile -Raw | ConvertFrom-Json
 Check ($manifest.mode -eq "loopback_only_not_public" -and
  $manifest.caddy_changed -eq $false -and
  $manifest.physical_control_enabled -eq $false) "K-V no publicado"
 Check ($cert.mode -eq "kx_real_boot_verified" -and $cert.bootstrap_status -eq "PASS") "Boot real certificado"
 Check ($integration.mode -eq "local_caddy_real_kv_get_only" -and
  $integration.public_https_tested -eq $false -and
  $integration.candidate_enabled_in_production -eq $false) "Caddy-KV local previamente validado"
 $hash=(Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash
 Check ($hash -eq $manifest.original_caddy_sha256 -and
  $hash -eq $cert.caddy_original_sha256 -and
  $hash -eq (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash) "Caddy y backup identicos"
 $tasks=@("VehiculoIoT-FastAPI","VehiculoIoT-Caddy","VehiculoIoT-Admission-Virtual")
 foreach($name in $tasks){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea activa: "+$name)
 }

 Write-Host ""
 Write-Host "=== ORIGEN DEL LANZADOR (SIN ARGUMENTOS) ===" -ForegroundColor Cyan
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 $actions=@($task.Actions|Where-Object{$null -ne $_})
 Check ($actions.Count -eq 1) "Una accion Caddy definida"
 Check ((Sid ([string]$task.Principal.UserId)) -eq "S-1-5-18") "Tarea Caddy bajo SYSTEM"
 Check ([string]$task.Principal.LogonType -eq "ServiceAccount") "Tipo de logon de cuenta de servicio"
 Check ([IO.Path]::GetFileName(([string]$actions[0].Execute).Trim('"')) -eq "powershell.exe") "Accion invoca PowerShell"
 $exported=Export-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 $saved=[IO.File]::ReadAllText($backupTask)
 Check ($exported.Trim() -eq $saved.Trim()) "Definicion de tarea coincide con snapshot"

 $launcher=Get-Ps1Path ([string]$actions[0].Arguments)
 Check (-not [string]::IsNullOrWhiteSpace($launcher)) "Lanzador PS1 absoluto identificado"
 Check (Test-Path -LiteralPath $launcher -PathType Leaf) "Lanzador PS1 existente"
 Check (((Get-Item -LiteralPath $launcher -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) "Lanzador sin ruta redirigida"
 $scriptHash=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash
 $tokens=$null
 $parseErrors=$null
 [System.Management.Automation.Language.Parser]::ParseFile(
  $launcher,[ref]$tokens,[ref]$parseErrors)|Out-Null
 Check (@($parseErrors).Count -eq 0) "Lanzador PowerShell parsea correctamente"
 $text=Get-Content -LiteralPath $launcher -Raw -ErrorAction Stop
 $acl=Inspect-RiskyACL $launcher
 Check ($acl.broad_write_entries -eq 0) "Lanzador sin permisos de escritura amplios"
 Write-Host ("LANZADOR: "+[IO.Path]::GetFileName($launcher))
 Write-Host ("LAUNCHER SHA256: "+$scriptHash)
 Write-Host ("ACL LANZADOR HERENCIA DESHABILITADA: "+$acl.protected)
 Write-Host ("LANZADOR MENCIONA CADDY.EXE: "+[bool]($text -match '(?i)caddy(?:\.exe)?'))
 Write-Host ("LANZADOR MENCIONA CADDYFILE: "+[bool]($text -match '(?i)Caddyfile'))
 Write-Host ("LANZADOR INICIA PROCESO: "+[bool]($text -match '(?i)Start-Process|\bcaddy\s+(?:run|start)\b'))
 Write-Host ("LANZADOR USA --RESUME: "+[bool]($text -match '(?i)(?:--resume|\s-resume)\b'))
 Write-Host ("LANZADOR USA --ENVIRON: "+[bool]($text -match '(?i)--environ\b'))
 Write-Host ("LANZADOR MENCIONA XDG_CONFIG_HOME: "+[bool]($text -match '(?i)XDG_CONFIG_HOME'))
 Write-Host ("LANZADOR MENCIONA PROOF K-X: "+[bool]($text -match '(?i)KX_STAGING_PROXY_PROOF'))
 Write-Host "CONTENIDO DEL LANZADOR: NO MOSTRADO"

 Write-Host ""
 Write-Host "=== PROCESO REAL Y CONFIGURACION AUTOSAVE ===" -ForegroundColor Cyan
 $https=@(Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue)
 Check ($https.Count -gt 0) "HTTPS original 443 activo"
 $ids=@($https|ForEach-Object{[int]$_.OwningProcess}|Select-Object -Unique)
 Check ($ids.Count -eq 1) "Unico proceso HTTPS"
 $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$ids[0]) -ErrorAction Stop
 Check ([IO.Path]::GetFileName([string]$proc.ExecutablePath) -eq "caddy.exe") "HTTPS pertenece a Caddy"
 Check ((Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid).Sid -eq "S-1-5-18") "Caddy sigue bajo SYSTEM"
 Write-Host ("CADDY PROCESS PARENT PID: "+$proc.ParentProcessId)
 Write-Host ("CADDY EJECUTABLE SHA256: "+(Get-FileHash -LiteralPath $proc.ExecutablePath -Algorithm SHA256).Hash)
 Write-Host ("PROCESO USA --RESUME: "+[bool](([string]$proc.CommandLine) -match '(?i)--resume'))
 Write-Host ("PROCESO USA --ENVIRON: "+[bool](([string]$proc.CommandLine) -match '(?i)--environ'))
 Write-Host "ARGUMENTOS COMPLETOS: NO MOSTRADOS"

 # Windows SYSTEM usual roaming configuration directory. Other XDG layouts may exist.
 $paths=@(
  (Join-Path $env:WINDIR "System32\config\systemprofile\AppData\Roaming\Caddy\autosave.json"),
  (Join-Path $env:WINDIR "SysWOW64\config\systemprofile\AppData\Roaming\Caddy\autosave.json")
 )
 $found=0
 foreach($target in $paths){
  if(-not (Test-Path -LiteralPath $target -PathType Leaf)){continue}
  Check (((Get-Item -LiteralPath $target -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) "Autosave sin ruta redirigida"
  $found++
  $security=Inspect-RiskyACL $target
  Check ($security.broad_write_entries -eq 0) "Autosave sin escritura de identidades amplias"
  $auto=Get-Content -LiteralPath $target -Raw -ErrorAction Stop
  Write-Host ("AUTOSAVE "+$found+" EXISTE: True")
  Write-Host ("AUTOSAVE "+$found+" ACL PROTEGIDA: "+$security.protected)
  Write-Host ("AUTOSAVE "+$found+" CONTIENE CABECERA PROXY K-X: "+
   [bool]($auto -match '(?i)X-Admission-Proxy-Token'))
  Write-Host ("AUTOSAVE "+$found+" SHA256: "+(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash)
 }
 if($found -eq 0){
  Write-Host "AUTOSAVE RUTAS WINDOWS SYSTEM COMUNES: NO ENCONTRADO"
  Write-Host "NOTA: XDG_CONFIG_HOME PUEDE REUBICAR AUTOSAVE"
 }
 $admin=@(Get-NetTCPConnection -LocalPort 2019 -State Listen -ErrorAction SilentlyContinue)
 Check ($admin.Count -eq 0 -or
  @($admin|Where-Object{$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "Admin API Caddy 2019 no expuesta externamente"
 $kv=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
 Check ($kv.Count -eq 1 -and $kv[0].LocalAddress -eq "127.0.0.1") "K-V conserva loopback"
 Check ((Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash -eq $hash) "Caddyfile sin cambios"
 Write-Host ""
 Write-Host "=== RESULTADO: AUDITORIA LANZADOR Y AUTOSAVE COMPLETA ===" -ForegroundColor Green
 Write-Host "LANZADOR CADDY: IDENTIFICADO Y REVISADO"
 Write-Host "CUENTA CADDY: SYSTEM"
 Write-Host "AUTOSAVE: UBICACIONES COMUNES INSPECCIONADAS"
 Write-Host "K-V PUBLICO: NO ACTIVADO"
 Write-Host "CONTROL FISICO: OFF"
}
catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO AUDITORIA LANZADOR ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("ERROR: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO CAMBIAR CADDY NI ACTIVAR K-V"
}
finally {
 Write-Host "SIN ESCRITURAS, PROCESOS NUEVOS, HTTP, RELOAD, RDS, ESP O MOTORES"
 Write-Host "=== FIN K-X LAUNCHER INVENTORY ===" -ForegroundColor Cyan
}
