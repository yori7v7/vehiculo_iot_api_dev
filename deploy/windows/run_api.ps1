param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
try {
    $StateDirectory = Get-VehicleStateDirectory $StateDirectory
    $configuration = Get-VehicleConfiguration $StateDirectory
    $env:PYTHONUNBUFFERED = '1'
    # Only the local Caddy proxy may supply forwarded headers. Managers are local
    # to this ONE process; more workers would split WebSocket clients and DEMO.
    $arguments = @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000',
        '--workers', '1', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1',
        '--no-access-log', '--log-level', 'warning'
    )
    exit (Invoke-VehicleProcess $StateDirectory 'api' $configuration.python_path $arguments)
}
catch {
    Write-VehicleFailureLog $StateDirectory 'api'
    Write-Error 'La tarea FastAPI no pudo continuar. Revisa requisitos, rutas y logs protegidos.' -ErrorAction Continue
    exit 1
}
