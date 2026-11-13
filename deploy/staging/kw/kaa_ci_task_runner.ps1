# K-AA: adaptador EXCLUSIVO DE CI para comprobar identidad LocalService
# ejecutando el sidecar K-Y real por Task Scheduler, sin HTTP público.
# NO usar en EC2: este script crea el entorno CI falso deliberadamente.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Fixture,
    [Parameter(Mandatory=$true)][string]$PythonPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    if ($env:OS -ne 'Windows_NT' -or
        -not (Test-Path -LiteralPath (Join-Path $Fixture 'KAA_CI_ONLY.marker') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $Workspace 'app\public_control\ky_windows_sidecar.py') -PathType Leaf)) {
        throw 'No es un fixture CI de K-AA.'
    }
    $config = Join-Path $Fixture 'private.json'
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        throw 'Configuracion privada no disponible.'
    }
    # Instrumentación CI: SOLO estados y salida numérica, sin secretos.
    $stateFile = Join-Path $Fixture 'kaa-state.txt'
    'wrapper-started' | Set-Content -LiteralPath $stateFile
    # Esta asignacion SOLO permite probar la barrera K-Y en CI; no da
    # autorizacion de despliegue. La clave real nunca entra en argumentos.
    $env:GITHUB_ACTIONS = 'true'
    $env:KY_WINDOWS_CI_ONLY = 'isolated-sidecar'
    $env:APP_ENV = 'staging'
    $env:ADMISSION_VIRTUAL_ONLY = 'enabled'
    $env:RUNNER_TEMP = $Fixture
    Set-Location -LiteralPath $Workspace
    'python-start' | Add-Content -LiteralPath $stateFile
    # Los registros se quedan EN EL FIXTURE PRIVADO; no se suben a CI.
    & $PythonPath -m app.public_control.ky_windows_sidecar --config $config 1> (Join-Path $Fixture 'kaa.stdout.log') 2> (Join-Path $Fixture 'kaa.stderr.log')
    $code = $LASTEXITCODE
    ('python-exit-' + [string]$code) | Add-Content -LiteralPath $stateFile
    exit $code
}
catch {
    # El tipo de fallo no se revela en salida pública.
    if (Test-Path -LiteralPath (Join-Path $Fixture 'kaa-state.txt')) {
        'wrapper-failed' | Add-Content -LiteralPath (Join-Path $Fixture 'kaa-state.txt')
        $exceptionName = $_.Exception.GetType().Name
        if ($exceptionName -match '^[A-Za-z][A-Za-z0-9]{2,70}$') {
            ('exception-' + $exceptionName) | Add-Content -LiteralPath (Join-Path $Fixture 'kaa-state.txt')
        }
    }
    Write-Output '[K-AA] NO-GO: runner LocalService no pudo iniciar la admision virtual.'
    exit 2
}
