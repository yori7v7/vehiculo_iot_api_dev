param([string]$CaddyPath, [string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-VehicleAdministrator
$StateDirectory = Get-VehicleStateDirectory $StateDirectory
$root = Get-VehicleProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

foreach ($required in @($python, (Join-Path $root '.env'), (Join-Path $root '.certs\rds-global-bundle.pem'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw ('Falta un requisito: {0}. Sigue docs/despliegue_ec2.md.' -f $required)
    }
}
# Importing libraries does not import app.main or load the project's .env.
& $python -c 'import uvicorn, fastapi, pymysql, pydantic_settings' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Instala requirements.txt dentro de .venv antes de continuar.' }

if ([string]::IsNullOrWhiteSpace($CaddyPath)) {
    $command = Get-Command caddy.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        throw 'No se encontro Caddy. Instalalo primero o especifica -CaddyPath con la ruta de caddy.exe.'
    }
    $CaddyPath = $command.Source
}
if (-not (Test-Path -LiteralPath $CaddyPath -PathType Leaf)) { throw 'CaddyPath no es un archivo existente.' }
$CaddyPath = (Resolve-Path -LiteralPath $CaddyPath).ProviderPath
if ([IO.Path]::GetFileName($CaddyPath) -ne 'caddy.exe') { throw 'CaddyPath debe apuntar a caddy.exe.' }
Assert-VehicleTaskOwnership $StateDirectory

$configurationPath = Join-Path $StateDirectory 'deployment.json'
if (Test-Path -LiteralPath $configurationPath -PathType Leaf) {
    $null = Get-VehicleConfiguration $StateDirectory
}

# SYSTEM executes this repository: detect ordinary-users write permissions.
# Do not rewrite the developer's checkout ACL automatically.
$writeMask = Get-VehicleWriteRightsMask
$ordinarySids = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
$unsafePaths = @()
foreach ($path in @($root, (Join-Path $root 'deploy\windows'), $python)) {
    $rules = (Get-Acl -LiteralPath $path).GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    foreach ($rule in $rules) {
        if ($rule.AccessControlType -eq 'Allow' -and
            $ordinarySids -contains $rule.IdentityReference.Value -and
            ($rule.FileSystemRights -band $writeMask) -ne 0) {
            $unsafePaths += $path
        }
    }
}
if ($unsafePaths.Count -gt 0) {
    throw 'El repositorio o Python permiten escritura a usuarios generales. Restringe sus ACL a administradores antes de ejecutar codigo como SYSTEM; no se modificaron sus permisos.'
}

New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
Protect-VehicleStateDirectory $StateDirectory
foreach ($directory in @('bin', 'logs', 'run', 'caddy-data', 'caddy-config')) {
    New-Item -ItemType Directory -Path (Join-Path $StateDirectory $directory) -Force | Out-Null
}
$deployedCaddyfile = Join-Path $StateDirectory 'Caddyfile'
if (-not (Test-Path -LiteralPath $deployedCaddyfile -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Caddyfile') -Destination $deployedCaddyfile
}
Set-VehicleCaddyEnvironment $StateDirectory
# Validate the preserved configuration before stopping a working installation.
Test-VehicleCaddyConfiguration $CaddyPath $deployedCaddyfile

Stop-VehicleDeployment $StateDirectory
$stagedCaddy = Join-Path $StateDirectory 'bin\caddy.exe'
if ($CaddyPath -ne $stagedCaddy -and
    (-not (Test-Path -LiteralPath $stagedCaddy -PathType Leaf) -or
    (Get-FileHash -LiteralPath $CaddyPath -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath $stagedCaddy -Algorithm SHA256).Hash)) {
    Copy-Item -LiteralPath $CaddyPath -Destination $stagedCaddy -Force
}
$configuration = [ordered]@{
    schema_version = 1
    project_root = $root
    python_path = $python
    caddy_path = $stagedCaddy
    caddyfile_path = $deployedCaddyfile
    state_directory = $StateDirectory
}
$configuration | ConvertTo-Json | Set-Content -LiteralPath $configurationPath -Encoding UTF8

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$names = Get-VehicleTaskNames
for ($index = 0; $index -lt $names.Count; $index++) {
    $component = @('api', 'caddy')[$index]
    $action = New-ScheduledTaskAction -Execute (Get-VehiclePowerShell) `
        -Argument (Get-VehicleTaskArguments $component $StateDirectory) -WorkingDirectory $root
    Register-ScheduledTask -TaskName $names[$index] -TaskPath '\' -Action $action `
        -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'Vehiculo IoT: arranque persistente administrado por deploy/windows.' -Force | Out-Null
}
Start-VehicleDeployment $StateDirectory
Write-Output 'Tareas instaladas y solicitadas: VehiculoIoT-FastAPI / VehiculoIoT-Caddy.'
Write-Output ('Estado, configuracion TLS y logs protegidos: {0}' -f $StateDirectory)
Write-Output 'Comprueba status.ps1 y las URL publicas. No se ha modificado .env ni reglas de AWS/Firewall.'
