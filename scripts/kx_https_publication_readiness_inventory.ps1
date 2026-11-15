# K-X 5.5: HTTPS publication readiness audit, READ ONLY, no secrets printed.
# Checks original Caddy task/worker/runtime ownership to design safe proxy credential injection.
# DO NOT reload Caddy, publish K-V or modify any service during this audit.
$ErrorActionPreference = "Stop"
$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$state = "C:\ProgramData\VehiculoIoT-KX-State\service"
$caddyPath = "C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestPath = Join-Path $state "install.json"
$configPath = Join-Path $state "config.json"
$certificatePath = Join-Path $root "kx_postboot_verified.json"
$backupPath = Join-Path $root "kx_caddy_release_preflight\Caddyfile.original.copy"
$rollbackReportPath = Join-Path $root "kx_caddy_rollback_rehearsal\rehearsal_results.json"
$integrationReportPath = Join-Path $root "kx_real_caddy_local_contract.json"
$candidatePath = Join-Path $root "kx_caddy_offline_disabled\Caddyfile.kx.offline"

function Check([bool]$value,[string]$message) {
    if(-not $value){throw ("NO-GO: "+$message)}
    Write-Host ("OK: "+$message) -ForegroundColor Green
}
function As-Sid([string]$account) {
    if($account -match '^S-1-[0-9]+(?:-[0-9]+)+$') {return $account}
    return ([Security.Principal.NTAccount]::new($account)).Translate(
        [Security.Principal.SecurityIdentifier]).Value
}
function Listening([int]$port) {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
Write-Host ""
Write-Host "=== K-X: AUDITORIA PREPUBLICACION HTTPS DE SOLO LECTURA ===" -ForegroundColor Cyan
try {
    $current = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    Check ($current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
    foreach($path in @($root,$state,$caddyPath,$manifestPath,$configPath,$certificatePath,
        $backupPath,$rollbackReportPath,$integrationReportPath,$candidatePath)) {
        Check (Test-Path -LiteralPath $path) "Evidencia requerida presente"
        Check (((Get-Item -LiteralPath $path -Force).Attributes -band
            [IO.FileAttributes]::ReparsePoint) -eq 0) "Sin ruta redirigida"
    }
    Check ((Get-Acl $root).AreAccessRulesProtected -and
        (Get-Acl $state).AreAccessRulesProtected) "Directorios privados protegidos"

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $certificate = Get-Content -LiteralPath $certificatePath -Raw | ConvertFrom-Json
    $rollback = Get-Content -LiteralPath $rollbackReportPath -Raw | ConvertFrom-Json
    $integration = Get-Content -LiteralPath $integrationReportPath -Raw | ConvertFrom-Json
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    Check ($manifest.mode -eq "loopback_only_not_public" -and
        $manifest.caddy_changed -eq $false -and
        $manifest.physical_control_enabled -eq $false) "K-V aun no publicado y sin control fisico"
    Check ($certificate.mode -eq "kx_real_boot_verified" -and
        $certificate.bootstrap_status -eq "PASS" -and
        $certificate.physical_control_enabled -eq $false) "Recuperacion real certificada"
    Check ($rollback.mode -eq "copy_only_restore_rehearsal_no_reload" -and
        $rollback.new_public_routes_enabled -eq $false) "Restauracion en copia aprobada"
    Check ($integration.mode -eq "local_caddy_real_kv_get_only" -and
        $integration.public_https_tested -eq $false -and
        $integration.candidate_enabled_in_production -eq $false -and
        $integration.physical_control_enabled -eq $false) "Integracion Caddy K-V local y virtual"

    $hash = (Get-FileHash -LiteralPath $caddyPath -Algorithm SHA256).Hash
    Check ($hash -eq $manifest.original_caddy_sha256 -and
        $hash -eq $certificate.caddy_original_sha256 -and
        $hash -eq (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash) "Caddy original y respaldo SHA256 intactos"

    $candidate = Get-Content -LiteralPath $candidatePath -Raw
    Check ($candidate.Contains("OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT") -and
        $candidate.Contains("reverse_proxy 127.0.0.1:9444") -and
        $candidate.Contains("reverse_proxy 127.0.0.1:8000")) "Candidato todavia offline con token invalido"

    Check ($config.mode -eq "virtual_loopback_only" -and
        $config.bind_host -eq "127.0.0.1" -and
        [int]$config.bind_port -eq 9444) "Modo virtual de K-V conservado"
    Check ($config.admin_proof -is [string] -and
        $config.proxy_proof -is [string] -and
        $config.admin_proof.Length -ge 32 -and
        $config.proxy_proof.Length -ge 32 -and
        $config.admin_proof -cne $config.proxy_proof) "Credenciales privadas separadas sin imprimir"

    Write-Host ""
    Write-Host "=== TAREAS, ACCIONES E IDENTIDAD DE CADDY ===" -ForegroundColor Cyan

    foreach($taskName in @("VehiculoIoT-Caddy","VehiculoIoT-FastAPI","VehiculoIoT-Admission-Virtual")){
        $task = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
        Check ($task.State -eq "Running") ("Tarea funcionando: "+$taskName)
    }
    $caddyTask = Get-ScheduledTask -TaskPath "\" -TaskName "VehiculoIoT-Caddy" -ErrorAction Stop
    $actions = @($caddyTask.Actions | Where-Object { $null -ne $_ })
    Check ($actions.Count -ge 1) "Accion de Caddy registrada"
    $taskSid = As-Sid ([string]$caddyTask.Principal.UserId)
    Write-Host ("IDENTIDAD TAREA CADDY: "+ $(if($taskSid -eq "S-1-5-18"){"SYSTEM"}else{"NO_SYSTEM"}))
    Write-Host ("LOGON TYPE CADDY: "+[string]$caddyTask.Principal.LogonType)
    Write-Host ("NUMERO DE ACCIONES CADDY: "+$actions.Count)
    for($i=0;$i -lt $actions.Count;$i++){
        $action = $actions[$i]
        $name = [IO.Path]::GetFileName(([string]$action.Execute).Trim('"'))
        if([string]::IsNullOrWhiteSpace($name)){$name="NO_IDENTIFICADO"}
        Write-Host ("ACCION "+($i+1)+" EJECUTABLE: "+$name)
        $arguments = [string]$action.Arguments
        Write-Host ("ACCION "+($i+1)+" MENCIONA CADDYFILE: "+[bool]($arguments -match "Caddyfile"))
        Write-Host ("ACCION "+($i+1)+" MENCIONA LANZADOR PS1: "+[bool]($arguments -match "\.ps1\b"))
        Write-Host ("ACCION "+($i+1)+" MENCIONA PROOF K-X: "+[bool]($arguments -match "KX_STAGING_PROXY_PROOF"))
    }
    $https = @(Listening 443)
    Check ($https.Count -gt 0) "HTTPS 443 escuchando"
    $pids = @($https | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    Check ($pids.Count -eq 1 -and $pids[0] -gt 0) "Un unico proceso posee el listener HTTPS"
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId = "+$pids[0]) -ErrorAction Stop
    Check ([IO.Path]::GetFileName([string]$process.ExecutablePath) -eq "caddy.exe") "Listener 443 pertenece a Caddy original"
    $ownerSid = (Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid -ErrorAction Stop).Sid
    Check (-not [string]::IsNullOrWhiteSpace($ownerSid)) "SID de proceso Caddy disponible"
    Write-Host ("IDENTIDAD PROCESO CADDY: "+ $(if($ownerSid -eq "S-1-5-18"){"SYSTEM"}else{"NO_SYSTEM"}))
    Write-Host ("IDENTIDAD TAREA Y PROCESO COINCIDEN: "+[bool]($taskSid -eq $ownerSid))
    Write-Host ("LINEA DE COMANDOS EN PROCESO MENCIONA CADDYFILE: "+[bool](([string]$process.CommandLine) -match "Caddyfile"))
    Write-Host "NOTA: Nunca se imprimen argumentos completos ni variables de entorno"

    $k = @(Listening 9444)
    Check ($k.Count -eq 1 -and $k[0].LocalAddress -eq "127.0.0.1") "K-V sigue escuchando solo loopback"
    $kvProc = Get-CimInstance Win32_Process -Filter ("ProcessId = "+$k[0].OwningProcess) -ErrorAction Stop
    $kvSid = (Invoke-CimMethod -InputObject $kvProc -MethodName GetOwnerSid -ErrorAction Stop).Sid
    Check ($kvSid -eq $manifest.dedicated_sid) "K-V usa identidad dedicada"

    $legacy = @(Listening 8000)
    Check ($legacy.Count -gt 0 -and
        @($legacy | Where-Object { $_.LocalAddress -notin @("127.0.0.1","::1") }).Count -eq 0) "FastAPI 8000 solo loopback"
    $adminPort = @(Listening 2019)
    if($adminPort.Count -eq 0){
        Write-Host "CADDY API ADMIN 2019: SIN LISTENER"
    } elseif(@($adminPort | Where-Object { $_.LocalAddress -notin @("127.0.0.1","::1") }).Count -gt 0){
        throw "NO-GO: Caddy admin 2019 no esta restringido a loopback"
    } else {
        Write-Host "CADDY API ADMIN 2019: SOLO LOOPBACK"
    }

    Write-Host ""
    Write-Host "=== RESULTADO: INVENTARIO DE PUBLICACION HTTPS COMPLETO ===" -ForegroundColor Green
    Write-Host "CADDY ORIGINAL: SHA256 PASS"
    Write-Host "AUTOARRANQUE K-V: CERTIFICADO"
    Write-Host "LABORATORIO K-V: END-TO-END LOCAL PASS"
    Write-Host "CONFIGURACION ACTIVA: SIN MODIFICACIONES"
    Write-Host "K-V: NO PUBLICADO"
    Write-Host "PENDIENTE: MECANISMO DE INYECCION SEGURA DEL PROXY PROOF Y ROLLBACK REAL"
    Write-Host "CONTROL FISICO: OFF"
}
catch {
    Write-Host ""
    Write-Host "=== RESULTADO: NO-GO AUDITORIA PREPUBLICACION ===" -ForegroundColor Red
    Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
    Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
    Write-Host "NO PUBLICAR NI MODIFICAR CADDY"
}
finally {
    Write-Host "SIN ESCRITURAS, RELOAD, RESTART, PETICIONES HTTP NI CAMBIOS DE TAREAS"
    Write-Host "=== FIN K-X INVENTARIO HTTPS ===" -ForegroundColor Cyan
}
