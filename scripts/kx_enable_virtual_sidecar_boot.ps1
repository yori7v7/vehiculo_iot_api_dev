# K-X: activar inicio automatico exclusivamente del sidecar K-V virtual.
# Windows PowerShell 5.1 elevado. No reinicia Windows, no toca Caddy, RDS ni control fisico.
# Ante fallo POST-cambio, deshabilita la tarea para bloquear nuevos inicios hasta auditoria.
$ErrorActionPreference = "Stop"

$root = "C:\ProgramData\VehiculoIoT-KX-Installer"
$serviceDir = "C:\ProgramData\VehiculoIoT-KX-State\service"
$taskName = "VehiculoIoT-Admission-Virtual"
$manifestPath = Join-Path $serviceDir "install.json"
$configPath = Join-Path $serviceDir "config.json"
$caddy = "C:\ProgramData\VehiculoIoT\Caddyfile"
$checkpoint = Join-Path $root "startup-checkpoint"
$checkpointCreated = $false
$changed = $false
$success = $false
$hashBefore = $null
$manifestRaw = $null

function Assert-KX([bool]$value, [string]$message) {
    if (-not $value) {
        throw ("NO-GO: " + $message)
    }
    Write-Host ("OK: " + $message) -ForegroundColor Green
}

function Read-Listener {
    return @(
        Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue
    )
}

Write-Host ""
Write-Host "=== K-X: ACTIVACION DEL ARRANQUE AUTOMATICO VIRTUAL ===" -ForegroundColor Cyan

try {
    $who = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    Assert-KX ($who.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "PowerShell elevado"

    foreach ($path in @($root, $serviceDir, $manifestPath, $configPath, $caddy)) {
        Assert-KX (Test-Path -LiteralPath $path) "Precondicion presente"
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        Assert-KX (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta sin reparse point"
    }

    Assert-KX ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador privado protegido"
    Assert-KX ((Get-Acl -LiteralPath $serviceDir).AreAccessRulesProtected) "Estado del sidecar privado"
    Assert-KX (-not (Test-Path -LiteralPath $checkpoint)) "Checkpoint de arranque aun no existe"

    $manifestRaw = Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop
    $manifest = $manifestRaw | ConvertFrom-Json

    Assert-KX ($manifest.schema_version -eq 1 -and
        $manifest.mode -eq "loopback_only_not_public" -and
        $manifest.task_name -eq $taskName -and
        $manifest.dedicated_user -eq "VehIoT_KXSvc" -and
        $manifest.caddy_changed -eq $false -and
        $manifest.physical_control_enabled -eq $false -and
        $manifest.task_has_startup_trigger -eq $false) "Manifiesto virtual sin autoarranque"

    $hashBefore = (Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash
    Assert-KX ($hashBefore -eq $manifest.original_caddy_sha256) "Hash del Caddy original"
    Assert-KX ((Get-FileHash -LiteralPath (Join-Path $serviceDir "launcher.py") -Algorithm SHA256).Hash -eq
        $manifest.launcher_sha256) "Lanzador inalterado"

    $account = Get-LocalUser -Name $manifest.dedicated_user -ErrorAction Stop
    Assert-KX ($account.SID.Value -eq $manifest.dedicated_sid -and $account.Enabled) "Cuenta dedicada vigente"

    $task = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
    Assert-KX ($task.State -eq "Running") "Sidecar actualmente en ejecucion"
    Assert-KX (@($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) "No existe disparador previo"
    Assert-KX ([string]$task.Principal.RunLevel -eq "Limited" -and
        [string]$task.Principal.LogonType -eq "Password") "Principal limitado con credenciales administradas"
    Assert-KX ($task.Principal.UserId.EndsWith("\VehIoT_KXSvc", [StringComparison]::OrdinalIgnoreCase)) "Cuenta del task coincide"
    $beforeUserId = [string]$task.Principal.UserId
    $beforeRunLevel = [string]$task.Principal.RunLevel
    $beforeLogon = [string]$task.Principal.LogonType
    $beforeExec = [string]$task.Actions[0].Execute
    $beforeArgs = [string]$task.Actions[0].Arguments
    Assert-KX (@($task.Actions).Count -eq 1 -and $beforeExec -match 'python\.exe$') "Una sola accion Python"

    foreach ($name in @("VehiculoIoT-FastAPI", "VehiculoIoT-Caddy")) {
        $original = Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop
        Assert-KX ($original.State -eq "Running") ("Tarea original activa: " + $name)
    }
    $port8000 = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    Assert-KX ($port8000.Count -gt 0 -and
        @($port8000 | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }).Count -eq 0) "8000 legacy solo loopback"

    $listeners = @(Read-Listener)
    Assert-KX ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1") "9444 solo loopback"
    $ownerProc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $listeners[0].OwningProcess) -ErrorAction Stop
    $processSid = (Invoke-CimMethod -InputObject $ownerProc -MethodName GetOwnerSid -ErrorAction Stop).Sid
    Assert-KX ($processSid -eq $manifest.dedicated_sid) "9444 pertenece a identidad dedicada"

    $config = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop | ConvertFrom-Json
    Assert-KX ($config.mode -eq "virtual_loopback_only" -and
        $config.bind_host -eq "127.0.0.1" -and
        $config.bind_port -eq 9444 -and
        $config.admin_proof -ne $config.proxy_proof) "Configuracion sigue siendo virtual y aislada"
    $config = $null

    Write-Host ""
    Write-Host "=== GUARDANDO CHECKPOINT PRIVADO ===" -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $checkpoint -ErrorAction Stop | Out-Null
    $checkpointCreated = $true
    & icacls.exe $checkpoint /inheritance:r | Out-Null
    Assert-KX ($LASTEXITCODE -eq 0) "Checkpoint sin herencia"
    & icacls.exe $checkpoint /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    Assert-KX ($LASTEXITCODE -eq 0) "Checkpoint reservado a administradores y SYSTEM"
    $definition = Export-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
    Assert-KX ($definition -match '<Task' -and $definition -notmatch 'BootTrigger') "Definicion anterior sin trigger de arranque"
    Set-Content -LiteralPath (Join-Path $checkpoint "before-task.xml") -Value $definition -Encoding UTF8 -ErrorAction Stop
    Set-Content -LiteralPath (Join-Path $checkpoint "before-manifest.json") -Value $manifestRaw -Encoding UTF8 -ErrorAction Stop
    Assert-KX ((Get-Acl -LiteralPath $checkpoint).AreAccessRulesProtected) "Checkpoint privado guardado"

    Write-Host ""
    Write-Host "=== CONFIGURANDO DISPARADOR ATSTARTUP ===" -ForegroundColor Cyan
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Assert-KX ($null -ne $trigger -and [string]$trigger.CimClass.CimClassName -like '*BootTrigger') "Disparador de arranque valido"
    Set-ScheduledTask -TaskPath "\" -TaskName $taskName -Trigger $trigger -ErrorAction Stop | Out-Null
    $changed = $true

    $afterTask = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
    $triggers = @($afterTask.Triggers | Where-Object { $null -ne $_ })
    Assert-KX ($triggers.Count -eq 1 -and
        [string]$triggers[0].CimClass.CimClassName -like '*BootTrigger' -and
        $triggers[0].Enabled -eq $true) "Unico trigger de arranque habilitado"
    Assert-KX ($afterTask.Principal.UserId -eq $beforeUserId -and
        [string]$afterTask.Principal.RunLevel -eq $beforeRunLevel -and
        [string]$afterTask.Principal.LogonType -eq $beforeLogon) "Principal y credenciales conservados"
    Assert-KX (@($afterTask.Actions).Count -eq 1 -and
        [string]$afterTask.Actions[0].Execute -eq $beforeExec -and
        [string]$afterTask.Actions[0].Arguments -eq $beforeArgs) "Accion original conservada"
    Assert-KX ($afterTask.State -eq "Running") "K-V sigue ejecutandose"

    $newListeners = @(Read-Listener)
    Assert-KX ($newListeners.Count -eq 1 -and $newListeners[0].LocalAddress -eq "127.0.0.1") "9444 sigue restringido a loopback"
    Assert-KX ((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $hashBefore) "Caddy original intacto"
    foreach ($name in @("VehiculoIoT-FastAPI", "VehiculoIoT-Caddy")) {
        Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $name -ErrorAction Stop).State -eq "Running") ("Legacy intacta: " + $name)
    }
    Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "Backend 8000 sigue disponible"

    Write-Host ""
    Write-Host "=== ACTUALIZANDO MANIFIESTO DE DESPLIEGUE ===" -ForegroundColor Cyan
    $manifest.task_has_startup_trigger = $true
    $manifest | Add-Member -NotePropertyName "boot_trigger_configured_utc" -NotePropertyValue ([DateTime]::UtcNow.ToString("o")) -Force
    $manifest | Add-Member -NotePropertyName "boot_recovery_verified" -NotePropertyValue $false -Force
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -ErrorAction Stop
    $checkManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    Assert-KX ($checkManifest.task_has_startup_trigger -eq $true -and
        $checkManifest.boot_recovery_verified -eq $false) "Manifiesto refleja configuracion, sin fingir reinicio validado"

    $success = $true
    Write-Host ""
    Write-Host "=== RESULTADO: AUTOARRANQUE K-V CONFIGURADO ===" -ForegroundColor Green
    Write-Host "TAREA: RUNNING CON ATSTARTUP"
    Write-Host "REINICIO COMPLETO EC2: NO EJECUTADO NI CERTIFICADO"
    Write-Host "9444: SOLO LOOPBACK"
    Write-Host "CADDY Y LEGACY: INTACTOS; CONTROL FISICO: OFF"
}
catch {
    Write-Host ""
    Write-Host "=== RESULTADO: NO-GO AUTOARRANQUE ===" -ForegroundColor Red
    Write-Host ("TIPO: " + $_.Exception.GetType().Name) -ForegroundColor Yellow
    Write-Host ("MENSAJE: " + $_.Exception.Message) -ForegroundColor Yellow
    if ($_.FullyQualifiedErrorId) {
        Write-Host ("ERROR ID: " + $_.FullyQualifiedErrorId) -ForegroundColor Yellow
    }
    # Incluso si Set-ScheduledTask devuelve error, verificar si hubo cambio parcial.
    try {
        $current = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -ne $current) {
            $boot = @($current.Triggers | Where-Object {
                $null -ne $_ -and [string]$_.CimClass.CimClassName -like '*BootTrigger' -and $_.Enabled -eq $true
            })
            if ($boot.Count -gt 0) {
                $changed = $true
                Write-Host "ALERTA: Trigger detectado aun cuando el cmdlet fallo; contencion obligatoria" -ForegroundColor Yellow
            }
        }
    }
    catch {
        Write-Host "NO-GO: No se pudo auditar el trigger tras el error" -ForegroundColor Red
    }
}
finally {
    if (-not $success) {
        Write-Host ""
        Write-Host "=== CONTENCION DE AUTOARRANQUE ANTE NO-GO ===" -ForegroundColor Cyan
        if ($changed) {
            try {
                Disable-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop | Out-Null
                Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop).State -eq "Disabled") "Nuevo arranque bloqueado; tarea deshabilitada"
            }
            catch {
                Write-Host "NO-GO: No se confirmo deshabilitacion del trigger; NO REINICIAR EC2" -ForegroundColor Red
            }
        }
        if ($checkpointCreated -and $null -ne $manifestRaw) {
            try {
                Set-Content -LiteralPath $manifestPath -Value $manifestRaw -Encoding UTF8 -ErrorAction Stop
                Write-Host "OK: Manifiesto anterior restituido" -ForegroundColor Green
            }
            catch {
                Write-Host "NO-GO: Manifiesto no restaurado; NO REINICIAR EC2" -ForegroundColor Red
            }
        }
        if ($null -ne $hashBefore -and (Test-Path -LiteralPath $caddy)) {
            if ((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $hashBefore) {
                Write-Host "OK: Caddy original intacto" -ForegroundColor Green
            }
            else {
                Write-Host "NO-GO: Hash de Caddy inesperado" -ForegroundColor Red
            }
        }
        Write-Host "NO REPETIR LA OPERACION; REVISAR SALIDA Y CHECKPOINT"
    }
    Write-Host "SIN PUBLICAR RUTAS, REINICIAR EC2, USAR RDS NI ACCIONAR MOTORES"
    Write-Host "=== FIN K-X AUTOARRANQUE ===" -ForegroundColor Cyan
}
