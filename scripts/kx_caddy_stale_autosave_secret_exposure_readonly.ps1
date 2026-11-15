# K-X: identify retained proxy proof in old Administrator-profile Caddy autosave.
# READ ONLY for all production and profile files. Never print file content,
# credentials, identities, full profile paths, exception message or JSON data.
# The service has NOT been published. Do not delete or rotate credentials here.
$ErrorActionPreference = "Stop"
$installer = "C:\ProgramData\VehiculoIoT-KX-Installer"
$service = "C:\ProgramData\VehiculoIoT-KX-State\service"
$manifestPath = Join-Path $service "install.json"
$configPath = Join-Path $service "config.json"
$caddyFile = "C:\ProgramData\VehiculoIoT\Caddyfile"
$prodAutosave = "C:\ProgramData\VehiculoIoT\caddy-config\caddy\autosave.json"
$originalBackup = Join-Path $installer "kx_caddy_release_preflight\Caddyfile.original.copy"
$principal = $null
$config = $null
$proof = $null
$liveHash = $null
$found = 0
$withProof = 0
$withBroadRead = 0
$withOtherReader = 0
$phase = "INICIO"

function Check([bool]$yes,[string]$message){
    if(-not $yes){throw ("NO-GO: "+$message)}
    Write-Host ("OK: "+$message) -ForegroundColor Green
}
function NoReparse([string]$path,[string]$label){
    Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
    Check (((Get-Item -LiteralPath $path -Force).Attributes -band
      [IO.FileAttributes]::ReparsePoint) -eq 0) ("Ruta normal: "+$label)
}
function AuditFile([string]$path,[string]$label,[string]$currentSid){
    $security = Get-Acl -LiteralPath $path -ErrorAction Stop
    $allowRules = @($security.GetAccessRules(
      $true,$true,[Security.Principal.SecurityIdentifier]) |
      Where-Object {$_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow})
    $broad=@("S-1-1-0","S-1-5-11","S-1-5-32-545",
      "S-1-5-4","S-1-5-14","S-1-5-32-546","S-1-5-32-547",
      "S-1-5-2","S-1-5-113")
    $trusted=@("S-1-5-18","S-1-5-32-544",$currentSid)
    $readMask=[int][Security.AccessControl.FileSystemRights]::ReadData
    $mutateMask=[int](
      [Security.AccessControl.FileSystemRights]::WriteData -bor
      [Security.AccessControl.FileSystemRights]::AppendData -bor
      [Security.AccessControl.FileSystemRights]::Delete -bor
      [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
      [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
      [Security.AccessControl.FileSystemRights]::TakeOwnership)
    $broadRead=0
    $broadWrite=0
    $otherRead=0
    foreach($ace in $allowRules){
      $sid=[string]$ace.IdentityReference.Value
      $rights=[int]$ace.FileSystemRights
      if($sid -in $broad){
        if(($rights -band $readMask) -ne 0){$broadRead++}
        if(($rights -band $mutateMask) -ne 0){$broadWrite++}
      } elseif($sid -notin $trusted) {
        if(($rights -band $readMask) -ne 0){$otherRead++}
      }
    }
    Write-Host ("PERMISOS "+$label+": HERENCIA_PROTEGIDA="+
      $security.AreAccessRulesProtected+
      "; LECTURA_GRUPOS_AMPLIOS="+$broadRead+
      "; MUTACION_GRUPOS_AMPLIOS="+$broadWrite+
      "; LECTURA_IDENTIDADES_NO_CLASIFICADAS="+$otherRead)
    return [pscustomobject]@{
      BroadRead = $broadRead
      BroadWrite = $broadWrite
      OtherRead = $otherRead
    }
}
Write-Host ""
Write-Host "=== K-X: DIAGNOSTICO DE TOKEN EN AUTOSAVE DE PERFIL ===" -ForegroundColor Cyan
try{
  $phase = "PRIVILEGIOS"
  $principal=[Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent())
  Check ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
  $currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  foreach($p in @($installer,$service,$manifestPath,$configPath,$caddyFile,
      $prodAutosave,$originalBackup)){
    NoReparse $p ([IO.Path]::GetFileName($p))
  }
  Check ((Get-Acl -LiteralPath $installer).AreAccessRulesProtected -and
    (Get-Acl -LiteralPath $service).AreAccessRulesProtected) "Directorios de K-X privados"
  $m=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  Check ($m.mode -eq "loopback_only_not_public" -and
    $m.caddy_changed -eq $false -and
    $m.physical_control_enabled -eq $false) "K-V sigue aislado y virtual"
  $liveHash=(Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash
  Check ($liveHash -eq $m.original_caddy_sha256 -and
    $liveHash -eq (Get-FileHash -LiteralPath $originalBackup -Algorithm SHA256).Hash) "Caddyfile original sin alteraciones"
  foreach($name in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
    Check ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Tarea intacta: "+$name)
  }
  $sidecar=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
  Check ($sidecar.Count -eq 1 -and $sidecar[0].LocalAddress -eq "127.0.0.1") "K-V sigue solo loopback"

  $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
  Check ($config.mode -eq "virtual_loopback_only") "K-V en modo virtual"
  Check ($config.proxy_proof -is [string] -and $config.proxy_proof.Length -ge 32) "Token de proxy legible en memoria (no mostrado)"
  $proof=[string]$config.proxy_proof
  $production= [IO.File]::ReadAllText($prodAutosave)
  Check (-not $production.Contains($proof)) "Autosave PRODUCTIVO sin token privado"
  $production=$null
  $config=$null

  Write-Host ""
  Write-Host "=== BUSCANDO SOLO EN UBICACIONES DE PERFIL YA DETECTADAS ===" -ForegroundColor Cyan
  $userProfile=[IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
  $profileAppData=Join-Path $userProfile "AppData"
  $candidateRoots=@(
    [pscustomobject]@{Label="APPDATA";Base=[Environment]::GetEnvironmentVariable("APPDATA","Process")},
    [pscustomobject]@{Label="LOCALAPPDATA";Base=[Environment]::GetEnvironmentVariable("LOCALAPPDATA","Process")}
  )
  foreach($candidate in $candidateRoots){
    $phase="PERFIL_"+$candidate.Label
    Check (-not [string]::IsNullOrWhiteSpace($candidate.Base)) ("Raiz de "+$candidate.Label+" definida")
    $root=[IO.Path]::GetFullPath($candidate.Base).TrimEnd('\')
    Check ($root.StartsWith($profileAppData + '\',[StringComparison]::OrdinalIgnoreCase)) ("Ruta de "+$candidate.Label+" bajo perfil actual")
    Check (((Get-Item -LiteralPath $root -Force).Attributes -band
      [IO.FileAttributes]::ReparsePoint) -eq 0) ("Raiz "+$candidate.Label+" sin reparse point")
    $profileCaddy=Join-Path $root "Caddy"
    $target=Join-Path $profileCaddy "autosave.json"
    if(-not (Test-Path -LiteralPath $target -PathType Leaf)){
      Write-Host ("AUTOSAVE "+$candidate.Label+": NO EXISTE")
      continue
    }
    $found++
    NoReparse $profileCaddy ($candidate.Label+" directorio Caddy")
    NoReparse $target ($candidate.Label+" autosave")
    $dirACL=AuditFile $profileCaddy ($candidate.Label+" directorio") $currentSid
    $fileACL=AuditFile $target ($candidate.Label+" autosave") $currentSid
    $raw=[IO.File]::ReadAllText($target)
    $contains=$raw.Contains($proof)
    $hasHeader=($raw.IndexOf("X-Admission-Proxy-Token",[StringComparison]::OrdinalIgnoreCase) -ge 0)
    $raw=$null
    Write-Host ("AUTOSAVE "+$candidate.Label+": TOKEN_REAL_PRESENTE="+$contains+
      "; CABECERA_KV_PRESENTE="+$hasHeader)
    if($contains){
      $withProof++
      if($fileACL.BroadRead -gt 0){$withBroadRead++}
      if($fileACL.OtherRead -gt 0){$withOtherReader++}
    }
  }
  $proof=$null
  Check ($withProof -gt 0) "Hallazgo anterior reproducido sin mostrar el secreto"
  Check ((Get-FileHash -LiteralPath $caddyFile -Algorithm SHA256).Hash -eq $liveHash) "Caddy original preservado"
  Write-Host ""
  Write-Host "=== RESULTADO: CONTENCION DE CREDENCIAL PENDIENTE ===" -ForegroundColor Yellow
  Write-Host ("AUTOSAVES DE PERFIL DETECTADOS: "+$found)
  Write-Host ("AUTOSAVES CON TOKEN REAL: "+$withProof)
  Write-Host ("ARCHIVOS CON REGLAS AMPLIAS DE LECTURA: "+$withBroadRead)
  Write-Host ("ARCHIVOS CON OTRAS IDENTIDADES LECTORAS: "+$withOtherReader)
  Write-Host "DIAGNOSTICO: SOLO LECTURA; TOKEN NO MOSTRADO"
  Write-Host "SIGUIENTE: CONTENCION LOCAL + ROTACION DE PROXY_PROOF"
  Write-Host "API KEY ORIGINAL Y ADMIN_PROOF: NO MODIFICADOS"
  Write-Host "CADDY PUBLICO: INTACTO"
  Write-Host "K-V PUBLICO: DESHABILITADO"
  Write-Host "CONTROL FISICO: OFF"
}
catch{
  Write-Host ""
  Write-Host "=== RESULTADO: NO-GO AUDITORIA DE CREDENCIAL ===" -ForegroundColor Red
  Write-Host ("FASE: "+$phase) -ForegroundColor Yellow
  Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
  Write-Host "ERROR DETALLADO OMITIDO PARA EVITAR FILTRACION DE CREDENCIALES"
  Write-Host "NO REPETIR, NO BORRAR AUTOSAVES NI PUBLICAR K-V"
}
finally{
  $proof=$null
  $config=$null
  Write-Host "SIN BORRADOS, SET-ACL, RESTART, HTTP, RDS, ESP NI MOTORES"
  Write-Host "=== FIN K-X DIAGNOSTICO DE TOKEN ===" -ForegroundColor Cyan
}
