# K-X: offline-only HTTPS release candidate. No production Caddy, launcher or task modifications.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$service="C:\ProgramData\VehiculoIoT-KX-State\service"
$live="C:\ProgramData\VehiculoIoT\Caddyfile"
$liveAutosave="C:\ProgramData\VehiculoIoT\caddy-config\caddy\autosave.json"
$template=Join-Path $root "kx_caddy_offline_disabled\Caddyfile.kx.offline"
$backup=Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$rotation=Join-Path $root "kx_proxy_proof_rotation_result.json"
$runtime=Join-Path $root "kx_runtime_env_caddy_lab_result.json"
$manifestPath=Join-Path $service "install.json"
$configPath=Join-Path $service "config.json"
$release=Join-Path $root "kx_https_public_release_v1_offline"
$candidate=Join-Path $release "Caddyfile.kx.ready.NOT_ACTIVE"
$adapt=Join-Path $release "candidate-adapted.json"
$stderr=Join-Path $release "adapt.stderr"
$report=Join-Path $release "preparation.json"
$exe="C:\ProgramData\VehiculoIoT\bin\caddy.exe"
$created=$false
$done=$false
$liveHash=$null
$autosaveHash=$null
$config=$null
$secret=$null

function Check([bool]$yes,[string]$label) {
 if(-not $yes){throw "NO-GO: "+$label}
 Write-Host ("OK: "+$label) -ForegroundColor Green
}
function CheckPath([string]$path,[string]$label){
 Check (Test-Path -LiteralPath $path) ("Existe: "+$label)
 Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ("Sin reparse point: "+$label)
}
function Listeners([int]$port){
 return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
Write-Host ""
Write-Host "=== K-X: PREPARACION HTTPS PUBLICA SOLO OFFLINE ===" -ForegroundColor Cyan
try{
 $me=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Check ($me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$service,$live,$liveAutosave,$template,$backup,$rotation,$runtime,$manifestPath,$configPath,$exe)){
  CheckPath $p ([IO.Path]::GetFileName($p))
 }
 Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected -and (Get-Acl -LiteralPath $service).AreAccessRulesProtected) "Directorios protegidos"
 Check (-not (Test-Path -LiteralPath $release)) "Nuevo kit offline disponible"
 $m=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $r=Get-Content -LiteralPath $rotation -Raw|ConvertFrom-Json
 $v=Get-Content -LiteralPath $runtime -Raw|ConvertFrom-Json
 Check ($m.mode -eq "loopback_only_not_public" -and $m.caddy_changed -eq $false -and $m.physical_control_enabled -eq $false) "K-V virtual sin publicar"
 Check ($r.mode -eq "proxy_proof_rotated_kv_loopback_only" -and $r.old_proxy_rejected -eq 403 -and
  $r.new_proxy_authenticated -eq 200 -and $r.stale_profile_autosave_deleted -eq $true -and
  $r.old_ntfs_backup_deleted_before_restart -eq $true) "Rotacion del token certificada"
 Check ($v.mode -eq "runtime_env_proxy_proof_local_get_only" -and
  $v.real_proxy_proof_saved_to_file -eq $false -and
  $v.runtime_env_placeholder_in_adapted_json -eq $true -and
  $v.caddy_autosave_disabled_in_lab -eq $true -and
  $v.public_https_tested -eq $false -and $v.production_caddy_modified -eq $false) "Laboratorio runtime certificado"
 $cases=@{ADMIN_VALIDO_POR_CADDY=200;ADMIN_SIN_CLAVE_POR_CADDY=401;ADMIN_CLAVE_FALSA_POR_CADDY=403;ORIGIN_FALSO_POR_CADDY=403;HEADERS_SPOOFED_FILTRADOS=200}
 foreach($name in $cases.Keys){
  Check (@($v.expected_outcomes | Where-Object {$_.case -ceq $name -and $_.status -eq $cases[$name]}).Count -eq 1) ("Resultado esperado: "+$name)
 }
 $liveHash=(Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
 $autosaveHash=(Get-FileHash -LiteralPath $liveAutosave -Algorithm SHA256).Hash
 Check ($liveHash -eq $m.original_caddy_sha256 -and $liveHash -eq (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash) "Caddy original y respaldo iguales"
 foreach($task in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
  Check ((Get-ScheduledTask -TaskPath "\" -TaskName $task -ErrorAction Stop).State -eq "Running") ("Tarea intacta: "+$task)
 }
 Check (@(Listeners 9481).Count -eq 0) "Puerto temporal 9481 libre"
 Check (@(Listeners 9444).Count -eq 1 -and @(Listeners 9444)[0].LocalAddress -eq "127.0.0.1") "K-V loopback 9444"
 Check (@(Listeners 443).Count -gt 0) "Caddy HTTPS 443 activo"
 Check (@(Listeners 2019 | Where-Object {$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "API admin Caddy no expuesta"
 $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
 Check ($config.mode -eq "virtual_loopback_only" -and $config.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$') "Token privado de 64 caracteres, no mostrado"
 $secret=[string]$config.proxy_proof
 Check (-not ([IO.File]::ReadAllText($liveAutosave)).Contains($secret)) "Autosave de produccion sin token"
 Check (-not (Test-Path -LiteralPath (Join-Path $env:APPDATA "Caddy\autosave.json"))) "Autosave obsoleto ausente"
 $source=[IO.File]::ReadAllText($template)
 $invalid="OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT_000000000000000000"
 Check ($source.Contains($invalid) -and $source.Contains("reverse_proxy 127.0.0.1:8000") -and
  $source.Contains("reverse_proxy 127.0.0.1:9444")) "Candidato inactivo conserva fallback legacy"
 $content=$source.Replace($invalid,'{env.KX_STAGING_PROXY_PROOF}')
 $prefix=[string]::Join([Environment]::NewLine,@("{"," admin 127.0.0.1:2019"," persist_config off","}","# K-X OFFLINE ONLY - NOT ACTIVE",""))
 $content=$prefix+[Environment]::NewLine+$content
 Check ($content.Contains("{env.KX_STAGING_PROXY_PROOF}") -and
  $content.Contains(" persist_config off") -and $content.Contains(" admin 127.0.0.1:2019") -and
  -not $content.Contains($secret) -and -not $content.Contains($invalid)) "Placeholder presente, token real ausente"
 Write-Host ""
 Write-Host "=== GENERANDO ARCHIVOS PRIVADOS OFFLINE ===" -ForegroundColor Cyan
 New-Item -ItemType Directory -Path $release -ErrorAction Stop | Out-Null
 $created=$true
 & icacls.exe $release /inheritance:r | Out-Null
 Check ($LASTEXITCODE -eq 0) "Herencia NTFS deshabilitada"
 & icacls.exe $release /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
 Check ($LASTEXITCODE -eq 0) "Permisos solo SYSTEM y Administradores"
 Check ((Get-Acl -LiteralPath $release).AreAccessRulesProtected) "Kit protegido"
 [IO.File]::WriteAllText($candidate,$content,([Text.UTF8Encoding]::new($false)))
 $argsString='adapt --config "'+$candidate+'" --adapter caddyfile'
 $proc=Start-Process -FilePath $exe -ArgumentList $argsString -NoNewWindow -Wait -PassThru -RedirectStandardOutput $adapt -RedirectStandardError $stderr -ErrorAction Stop
 Check ($proc.ExitCode -eq 0) "Caddy adapt acepta el candidato"
 $json=[IO.File]::ReadAllText($adapt)
 Check ($json.Contains("{env.KX_STAGING_PROXY_PROOF}") -and -not $json.Contains($secret)) "JSON adaptado contiene placeholder, no token"
 Check ($json -match '"persist"\s*:\s*false') "Autosave deshabilitado en candidato"
 Check ($json.Contains("127.0.0.1:2019") -and $json.Contains("127.0.0.1:8000") -and
  $json.Contains("127.0.0.1:9444")) "Admin loopback y ambos upstreams en JSON"
 Check ((Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash -eq $liveHash) "Caddyfile productivo igual"
 Check ((Get-FileHash -LiteralPath $liveAutosave -Algorithm SHA256).Hash -eq $autosaveHash) "Autosave de produccion igual"
 [ordered]@{
  schema_version=1;mode="offline_public_https_candidate_never_activated"
  prepared_utc=[DateTime]::UtcNow.ToString("o")
  candidate_sha256=(Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
  adapted_sha256=(Get-FileHash -LiteralPath $adapt -Algorithm SHA256).Hash
  production_sha256=$liveHash
  original_autosave_sha256=$autosaveHash
  runtime_placeholder_retained=$true
  real_secret_written_to_candidate=$false
  caddy_persist_config_disabled=$true
  caddy_admin_loopback_only=$true
  legacy_backend_preserved=$true
  production_caddy_changed=$false
  task_action_changed=$false
  new_public_routes_enabled=$false
  physical_control_enabled=$false
 }|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $report -Encoding UTF8 -ErrorAction Stop
 $done=$true
 Write-Host ""
 Write-Host "=== RESULTADO: KIT HTTPS PUBLICO OFFLINE APROBADO ===" -ForegroundColor Green
 Write-Host "CANDIDATO CADDYFILE: GENERADO, NO ACTIVADO"
 Write-Host "RUTAS LEGACY 8000 Y K-V 9444: PRESERVADAS"
 Write-Host "TOKEN REAL EN CADDYFILE/JSON: NO"
 Write-Host "ADMIN CADDY: LOOPBACK, AUTOSAVE: OFF"
 Write-Host "CADDY PUBLICO Y TAREAS: SIN CAMBIOS"
 Write-Host "SIGUIENTE: PREPARAR ARRANQUE CON VARIABLE DE ENTORNO Y ROLLBACK REAL"
 Write-Host "CONTROL FISICO: OFF"
}catch{
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO KIT HTTPS OFFLINE ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host "MENSAJE OMITIDO; NO ACTIVAR CADDY"
}finally{
 $secret=$null;$config=$null
 if(-not $done -and $created -and (Test-Path -LiteralPath $release)){
  try{Remove-Item -LiteralPath $release -Recurse -Force -ErrorAction Stop
   Write-Host "OK: Kit incompleto retirado" -ForegroundColor Green
  }catch{Write-Host "NO-GO: No pudo limpiarse kit incompleto" -ForegroundColor Red}
 }
 if($null -ne $liveHash -and (Test-Path -LiteralPath $live)){
  if((Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash -eq $liveHash){
   Write-Host "OK: Caddy original intacto" -ForegroundColor Green
  }else{Write-Host "NO-GO: Caddy original difiere" -ForegroundColor Red}
 }
 Write-Host "SIN RELOAD, RESTART, POST, RDS, ESP NI MOTORES"
 Write-Host "=== FIN K-X KIT OFFLINE ===" -ForegroundColor Cyan
}