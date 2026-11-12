# Etapa 5.5-F: Prueba de WSS en la PC; NUNCA en AWS ni con motores.
# Ejecutar desde raiz del repo: powershell.exe -ExecutionPolicy Bypass -File .\scripts\prueba_55f_windows.ps1
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

$env:APP_ENV = 'development'
$env:CONTROL_PUBLICO_ENABLED = 'false'
$env:CONTROL_PUBLICO_SIMULATION = 'false'
$env:DEVICE_LAB_ENABLED = 'true'
$env:DEVICE_LAB_KEY = (py -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($env:DEVICE_LAB_KEY)) {
    throw 'No se pudo crear una clave aleatoria local.'
}

$server = $null
try {
    $portFree = $true
    try {
        $p = New-Object System.Net.Sockets.TcpClient
        $p.Connect('127.0.0.1', 8001)
        $portFree = $false
    } catch {
        $portFree = $true
    } finally {
        if ($null -ne $p) { $p.Dispose() }
    }
    if (-not $portFree) { throw 'El puerto 8001 ya esta ocupado. Deten el servidor anterior.' }

    Write-Host '[55-F] Iniciando FastAPI local (sin AWS)...'
    # Start-Process hereda DEVICE_LAB_KEY. Nunca escribir la clave a disco.
    $pythonExe = (py -c "import sys; print(sys.executable)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonExe)) {
        throw 'No se encontro python.exe.'
    }
    $server = Start-Process -FilePath $pythonExe -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
        '--port', '8001', '--workers', '1', '--no-proxy-headers'
    ) -WorkingDirectory $repo -PassThru

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if ($server.HasExited) { throw 'Uvicorn cerro antes de la prueba.' }
        $p = $null
        try {
            $p = New-Object System.Net.Sockets.TcpClient
            $p.Connect('127.0.0.1', 8001)
            $ready = $true
            break
        } catch {
        } finally {
            if ($null -ne $p) { $p.Dispose() }
        }
    }
    if (-not $ready) { throw 'FastAPI no respondio en el puerto 8001.' }
    Write-Host '[55-F] Ejecutando cliente WSS virtual autenticado...'
    py -m scripts.prueba_wss_55f
    if ($LASTEXITCODE -ne 0) { throw 'La prueba WSS fallo. Revisa el mensaje anterior.' }
    Write-Host '[55-F] Comprobacion local completada; sin movimiento fisico.'
}
finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item Env:\DEVICE_LAB_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\DEVICE_LAB_ENABLED -ErrorAction SilentlyContinue
}
