# K-X: prepara candidato Caddy offline CON TOKEN INVALIDO deliberadamente.
# No cambia el Caddyfile original, no recarga, no abre puertos, no lee secretos K-V.
# PowerShell 5.1; genera artefactos solo en directorio privado.
$ErrorActionPreference = "Stop"

$originalPath = "C:\ProgramData\VehiculoIoT\Caddyfile"
$installerRoot = "C:\ProgramData\VehiculoIoT-KX-Installer"
$stageDir = Join-Path $installerRoot "kx_caddy_offline_disabled"
$candidatePath = Join-Path $stageDir "Caddyfile.kx.offline"
$adaptedPath = Join-Path $stageDir "candidate-adapted.json"
$errorPath = Join-Path $stageDir "adapt-stderr.txt"
$serviceDir = "C:\ProgramData\VehiculoIoT-KX-State\service"
$manifestPath = Join-Path $serviceDir "install.json"
$certificatePath = Join-Path $installerRoot "kx_postboot_verified.json"
$createdStage = $false
$complete = $false
$caddyHash = $null

function Assert-KX([bool]$ok, [string]$label) {
    if (-not $ok) { throw ("NO-GO: " + $label) }
    Write-Host ("OK: " + $label) -ForegroundColor Green
}

Write-Host ""
Write-Host "=== K-X: CADDY CANDIDATO OFFLINE Y DESACTIVADO ===" -ForegroundColor Cyan
try {
    $self = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    Assert-KX ($self.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"

    foreach ($path in @($originalPath, $manifestPath, $certificatePath)) {
        Assert-KX (Test-Path -LiteralPath $path -PathType Leaf) "Evidencia presente"
        Assert-KX (((Get-Item -LiteralPath $path -Force).Attributes -band
            [IO.FileAttributes]::ReparsePoint) -eq 0) "Sin ruta redirigida"
    }

    Assert-KX ((Get-Acl -LiteralPath $installerRoot).AreAccessRulesProtected) "Raiz privada protegida"
    Assert-KX (-not (Test-Path -LiteralPath $stageDir)) "Candidato no creado anteriormente"

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $certificate = Get-Content -LiteralPath $certificatePath -Raw | ConvertFrom-Json
    Assert-KX ($manifest.schema_version -eq 1 -and
        $manifest.mode -eq "loopback_only_not_public" -and
        $manifest.caddy_changed -eq $false -and
        $manifest.physical_control_enabled -eq $false) "K-V sigue virtual"
    Assert-KX ($certificate.mode -eq "kx_real_boot_verified" -and
        $certificate.bootstrap_status -eq "PASS" -and
        $certificate.sidecar_loopback_verified -eq $true) "Arranque real certificado"

    $caddyHash = (Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash
    Assert-KX ($caddyHash -eq $manifest.original_caddy_sha256 -and
        $caddyHash -eq $certificate.caddy_original_sha256) "Caddy original sin alteraciones"

    $original = Get-Content -LiteralPath $originalPath -Raw -ErrorAction Stop
    $exactOriginal = '(?s)\A\s*(?:https://)?100-30-4-62\.nip\.io\s*\{\s*reverse_proxy\s+127\.0\.0\.1:8000\s*\}\s*\z'
    Assert-KX ($original -match $exactOriginal) "Caddyfile original de una sola ruta (sin opciones ocultas)"

    foreach ($taskName in @("VehiculoIoT-FastAPI", "VehiculoIoT-Caddy", "VehiculoIoT-Admission-Virtual")) {
        Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Tarea operativa: " + $taskName)
    }
    $kPort = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    Assert-KX ($kPort.Count -eq 1 -and $kPort[0].LocalAddress -eq "127.0.0.1") "K-V aislado 9444"
    Assert-KX (@(Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "HTTPS original 443"

    $caddyProcesses = @(Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction Stop)
    $executables = @(
        $caddyProcesses | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
            [IO.Path]::GetFileName($_.ExecutablePath) -eq "caddy.exe"
        } | ForEach-Object { $_.ExecutablePath } | Select-Object -Unique
    )
    Assert-KX ($executables.Count -eq 1 -and
        (Test-Path -LiteralPath $executables[0] -PathType Leaf)) "Binario original Caddy identificado"
    $caddyExe = [string]$executables[0]

    Write-Host ""
    Write-Host "=== GENERANDO CADDYFILE CANDIDATO PRIVADO ===" -ForegroundColor Cyan

    New-Item -ItemType Directory -Path $stageDir -ErrorAction Stop | Out-Null
    $createdStage = $true

    & icacls.exe $stageDir /inheritance:r | Out-Null
    Assert-KX ($LASTEXITCODE -eq 0) "Herencia deshabilitada"

    & icacls.exe $stageDir /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    Assert-KX ($LASTEXITCODE -eq 0) "Solo SYSTEM y Administradores"

    $candidate = @'
# K-X DISABLED OFFLINE CANDIDATE - NEVER RELOAD OR DEPLOY AS-IS
# El token es INVALIDO intencionalmente. NO contiene secretos reales.
100-30-4-62.nip.io {
    @kv_virtual {
        path /publico/vehiculos/1/solicitudes /publico/vehiculos/1/solicitudes/* /admin/vehiculos/1/control-publico/solicitudes /admin/vehiculos/1/control-publico/solicitudes/*
    }
    handle @kv_virtual {
        reverse_proxy 127.0.0.1:9444 {
            header_up -Forwarded
            header_up -X-Forwarded-For
            header_up -X-Forwarded-Host
            header_up -X-Forwarded-Proto
            header_up -X-Real-IP
            header_up Host 100-30-4-62.nip.io
            header_up X-Admission-Client-IP {http.request.remote.host}
            header_up X-Admission-Scheme https
            header_up X-Admission-Proxy-Token OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT_000000000000000000
        }
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
'@

    Set-Content -LiteralPath $candidatePath -Value $candidate -Encoding UTF8 -ErrorAction Stop
    Assert-KX (Test-Path -LiteralPath $candidatePath -PathType Leaf) "Candidato offline escrito"

    # Caddy adapt solo parsea y serializa. No inicia servidor ni carga la config activa.
    Write-Host ""
    Write-Host "=== CADDY ADAPT EN ARCHIVO AISLADO ===" -ForegroundColor Cyan

    $args = '--config "' + $candidatePath + '" --adapter caddyfile'
    $proc = Start-Process -FilePath $caddyExe -ArgumentList ("adapt " + $args) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $adaptedPath -RedirectStandardError $errorPath -ErrorAction Stop
    Assert-KX ($proc.ExitCode -eq 0) "Caddy adapt acepto sintaxis offline"
    Assert-KX (Test-Path -LiteralPath $adaptedPath -PathType Leaf) "JSON de candidato generado"

    $jsonText = Get-Content -LiteralPath $adaptedPath -Raw -ErrorAction Stop
    $json = $jsonText | ConvertFrom-Json
    Assert-KX ($null -ne $json.apps.http.servers) "Configuracion JSON de servidor HTTP valida"
    Assert-KX ($jsonText -match '127\.0\.0\.1:8000') "Fallback legacy 8000 conservado"
    Assert-KX ($jsonText -match '127\.0\.0\.1:9444') "Ruta virtual 9444 separada"
    Assert-KX ($jsonText -match 'X-Admission-Proxy-Token') "Encabezado de proxy declarado"
    Assert-KX ($jsonText -match 'OFFLINE_INVALID_TOKEN_NOT_FOR_DEPLOYMENT') "Solo token deliberadamente invalido"
    Assert-KX ($jsonText -match 'X-Admission-Client-IP') "IP del cliente a inyectar"
    Assert-KX ($jsonText -match 'X-Admission-Scheme') "Esquema HTTPS a verificar"

    Assert-KX ((Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash -eq $caddyHash) "Caddy original intacto tras adapt"
    $kPort = @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    Assert-KX ($kPort.Count -eq 1 -and $kPort[0].LocalAddress -eq "127.0.0.1") "K-V sigue en loopback"

    foreach ($taskName in @("VehiculoIoT-FastAPI", "VehiculoIoT-Caddy")) {
        Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Running") ("Servicio original intacto: " + $taskName)
    }

    $complete = $true
    Write-Host ""
    Write-Host "=== RESULTADO: CANDIDATO CADDY OFFLINE PREPARADO ===" -ForegroundColor Green
    Write-Host "SINTAXIS: ADAPT PASS"
    Write-Host "PROXY K-V: 9444 SOLO EN CANDIDATO"
    Write-Host "TOKEN: INVALIDO DELIBERADAMENTE"
    Write-Host "CONFIGURACION ACTIVA CADDY: INTACTA"
    Write-Host "443 / RUTAS PUBLICAS: SIN CAMBIOS"
    Write-Host "CANDIDATO: C:\ProgramData\VehiculoIoT-KX-Installer\kx_caddy_offline_disabled"
    Write-Host "FALTA PROBAR CABECERAS REALES ANTES DE ACTIVAR"
}
catch {
    Write-Host ""
    Write-Host "=== RESULTADO: NO-GO CADDY OFFLINE ===" -ForegroundColor Red
    Write-Host ("TIPO: " + $_.Exception.GetType().Name) -ForegroundColor Yellow
    Write-Host ("MENSAJE: " + $_.Exception.Message) -ForegroundColor Yellow
}
finally {
    if (-not $complete -and $createdStage -and (Test-Path -LiteralPath $stageDir)) {
        try {
            Remove-Item -LiteralPath $stageDir -Force -Recurse -ErrorAction Stop
            Write-Host "OK: Candidato fallido eliminado" -ForegroundColor Green
        }
        catch {
            Write-Host "NO-GO: Candidato temporal pendiente; no activar" -ForegroundColor Red
        }
    }
    if ($null -ne $caddyHash -and (Test-Path -LiteralPath $originalPath)) {
        if ((Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash -eq $caddyHash) {
            Write-Host "OK: Hash Caddy original sin cambios" -ForegroundColor Green
        }
        else {
            Write-Host "NO-GO: Caddy original diferente; detener" -ForegroundColor Red
        }
    }
    Write-Host "SIN RELOAD, RUN, RESTART, HTTP, RDS, ESP O MOTORES"
    Write-Host "=== FIN K-X CANDIDATO OFFLINE ===" -ForegroundColor Cyan
}
