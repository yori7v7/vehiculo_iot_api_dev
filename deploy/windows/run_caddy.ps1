param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
try {
    $StateDirectory = Get-VehicleStateDirectory $StateDirectory
    $configuration = Get-VehicleConfiguration $StateDirectory
    Set-VehicleCaddyEnvironment $StateDirectory
    $arguments = @('run', '--config', $configuration.caddyfile_path, '--adapter', 'caddyfile')
    exit (Invoke-VehicleProcess $StateDirectory 'caddy' $configuration.caddy_path $arguments)
}
catch {
    Write-VehicleFailureLog $StateDirectory 'caddy'
    Write-Error 'La tarea Caddy no pudo continuar. Revisa requisitos, rutas y logs protegidos.' -ErrorAction Continue
    exit 1
}
