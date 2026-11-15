# K-X: diagnosis of broad write ACLs on original Caddy PowerShell launcher.
# READ ONLY. Never prints launcher contents or task arguments.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$manifestFile="C:\ProgramData\VehiculoIoT-KX-State\service\install.json"
$caddyFile="C:\ProgramData\VehiculoIoT\Caddyfile"
$backupFile=Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$integrationReport=Join-Path $root "kx_real_caddy_local_contract.json"
$rights=[Security.AccessControl.FileSystemRights]

function Assert-KX([bool]$condition,[string]$label){
 if(-not $condition){throw ("NO-GO: "+$label)}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function Resolve-Launcher([string]$arguments){
 $patterns=@(
  '(?i)"(?<path>[A-Z]:\\[^"]+?\.ps1)"',
  "(?i)'(?<path>[A-Z]:\\[^']+?\.ps1)'",
  '(?i)(?<path>[A-Z]:\\[^\s"'';]+?\.ps1)'
 )
 foreach($pattern in $patterns){
  $match=[regex]::Match($arguments,$pattern)
  if($match.Success){return [string]$match.Groups["path"].Value}
 }
 return $null
}
function Audit-KXACL([string]$path,[string]$label){
 Assert-KX (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Assert-KX (((Get-Item -LiteralPath $path -Force).Attributes -band
  [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin redireccion: "+$label)
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 $broad=@{
  "S-1-1-0"="TODOS"
  "S-1-5-11"="AUTENTICADOS"
  "S-1-5-32-545"="USUARIOS"
 }
 $contentMask=[int](
  [Security.AccessControl.FileSystemRights]::WriteData -bor
  [Security.AccessControl.FileSystemRights]::AppendData)
 $deleteMask=[int](
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles)
 $adminMask=[int](
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership)
 $metaMask=[int](
  [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
  [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes)
 Write-Host ""
 Write-Host ("=== ACL: "+$label+" ===") -ForegroundColor Cyan
 Write-Host ("RUTA: "+$path)
 Write-Host ("HERENCIA PROTEGIDA: "+$acl.AreAccessRulesProtected)
 Write-Host ("ACE TOTALES: "+$rules.Count)
 $owner=[string]$acl.Owner
 $ownerClass=if($owner -match '(?i)SYSTEM|S-1-5-18'){"SYSTEM"}elseif($owner -match '(?i)Administrators|Administradores|S-1-5-32-544'){"ADMINISTRADORES"}else{"OTRO"}
 Write-Host ("PROPIETARIO CLASE: "+$ownerClass)
 $index=0
 $warning=0
 foreach($rule in $rules){
  $sid=[string]$rule.IdentityReference.Value
  if(-not $broad.ContainsKey($sid)){continue}
  $index++
  $mask=[int]$rule.FileSystemRights
  $content=(($mask -band $contentMask) -ne 0)
  $deletion=(($mask -band $deleteMask) -ne 0)
  $changeAcl=(($mask -band $adminMask) -ne 0)
  $metadata=(($mask -band $metaMask) -ne 0)
  $isAllow=($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow)
  if($isAllow -and ($content -or $deletion -or $changeAcl -or $metadata)){$warning++}
  Write-Host ("ACE "+$index+": GRUPO="+$broad[$sid]+
   "; TIPO="+$rule.AccessControlType+
   "; HEREDADA="+$rule.IsInherited+
   "; DERECHOS="+$rule.FileSystemRights+
   "; CONTENIDO="+$content+
   "; BORRADO="+$deletion+
   "; ACL_PROPIEDAD="+$changeAcl+
   "; METADATOS="+$metadata+
   "; INHERIT_FLAGS="+$rule.InheritanceFlags+
   "; PROPAGATION_FLAGS="+$rule.PropagationFlags)
 }
 if($index -eq 0){Write-Host "ACE DE GRUPOS AMPLIOS: 0"}
 Write-Host ("ACE ALLOW DE ESCRITURA/ALTERACION AMPLIA: "+$warning)
 Write-Host "NOTA: Una ACE Allow no equivale automaticamente a acceso efectivo; revisar Deny/herencia/membresia"
 return $warning
}
Write-Host ""
Write-Host "=== K-X: DIAGNOSTICO ACL DEL LANZADOR SIN MODIFICACIONES ===" -ForegroundColor Cyan
try{
 $principal=[Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent())
 Assert-KX ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$manifestFile,$caddyFile,$backupFile,$integrationReport)){
  Assert-KX (Test-Path -LiteralPath $p) "Evidencia presente"
  Assert-KX (((Get-Item -LiteralPath $p -Force).Attributes -band
   [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta sin reparse point"
 }
 Assert-KX ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador K-X privado"
 $m=Get-Content -LiteralPath $manifestFile -Raw|ConvertFrom-Json
 $r=Get-Content -LiteralPath $integrationReport -Raw|ConvertFrom-Json
 Assert-KX ($m.mode -eq "loopback_only_not_public" -and
  $m.physical_control_enabled -eq $false -and
  $m.caddy_changed -eq $false) "K-V solo virtual"
 Assert-KX ($r.mode -eq "local_caddy_real_kv_get_only" -and
  $r.public_https_tested -eq $false -and
  $r.candidate_enabled_in_production -eq $false) "Integracion probada solo local"
 $original=(Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash
 Assert-KX ($original -eq $m.original_caddy_sha256 -and
  $original -eq (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash) "Caddy activo y backup intactos"
 foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea intacta: "+$name)
 }
 $task=Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
 $actions=@($task.Actions|Where-Object{$null -ne $_})
 Assert-KX ($actions.Count -eq 1) "Accion original unica"
 Assert-KX ([IO.Path]::GetFileName(([string]$actions[0].Execute).Trim('"')) -eq "powershell.exe") "Lanzador ejecutado via PowerShell"
 $launcher=Resolve-Launcher ([string]$actions[0].Arguments)
 Assert-KX (-not [string]::IsNullOrWhiteSpace($launcher)) "Ruta PS1 absoluta identificada"
 Assert-KX (Test-Path -LiteralPath $launcher -PathType Leaf) "Lanzador existente"
 $fileHash=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash

 $count=Audit-KXACL -path $launcher -label "LANZADOR PS1"
 $parent=Split-Path -Parent $launcher
 if(-not [string]::IsNullOrWhiteSpace($parent)){
  $null=Audit-KXACL -path $parent -label "CARPETA CONTENEDORA DEL LANZADOR"
  $grandparent=Split-Path -Parent $parent
  if(-not [string]::IsNullOrWhiteSpace($grandparent) -and
   $grandparent -ne $parent){
   $null=Audit-KXACL -path $grandparent -label "CARPETA PADRE SUPERIOR"
  }
 }
 $null=Audit-KXACL -path $caddyFile -label "CADDYFILE ORIGINAL"

 Write-Host ""
 Assert-KX ((Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash -eq $fileHash) "Lanzador sin cambios"
 Assert-KX ((Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash -eq $original) "Caddyfile original sin cambios"
 Write-Host ""
 Write-Host "=== RESULTADO: DIAGNOSTICO ACL COMPLETADO ===" -ForegroundColor Green
 Write-Host ("REGLAS AMPLIAS DE RIESGO EN LANZADOR: "+$count)
 Write-Host "PERMISOS: SOLO INSPECCIONADOS"
 Write-Host "CADDY HTTPS: NO MODIFICADO"
 Write-Host "K-V PUBLICO: NO ACTIVADO"
 Write-Host "CONTROL FISICO: OFF"
}
catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO DIAGNOSTICO ACL ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 Write-Host "NO CAMBIAR ACL NI REINICIAR"
}
finally{
 Write-Host "SIN SET-ACL, ICACLS, ESCRITURAS, RELOAD, HTTP, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X DIAGNOSTICO ACL ===" -ForegroundColor Cyan
}
