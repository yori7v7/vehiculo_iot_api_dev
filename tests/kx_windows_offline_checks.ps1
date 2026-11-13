# K-X: tests nativos PowerShell 5.1. Nada se ejecuta en AWS ni en
# Task Scheduler real. Solo lee repositorio y un fixture descartable.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$audit = Join-Path $root 'deploy\staging\kw\kx_readonly_preflight.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tokens = $null
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    $audit, [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) { throw 'K-X: error de sintaxis PowerShell 5.1' }
Write-Output '[K-X TEST] Sintaxis Windows PowerShell 5.1 OK'

& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $audit -Mode Repository
if ($LASTEXITCODE -ne 0) {
    throw 'K-X: preflight del repositorio debe terminar exit 0 sin tocar Windows'
}
Write-Output '[K-X TEST] Preflight offline del repositorio OK'

# Cambiar Caddyfile UNICAMENTE dentro del fixture temporal. El preflight
# debe detectar una IP hardcodeada de CI en el candidato y devolver NO-GO.
$fixture = Join-Path $env:RUNNER_TEMP ('kx-fixture-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($d in @('deploy\windows','deploy\staging\kw','app\public_control')) {
        $null = New-Item -ItemType Directory -Force -Path (Join-Path $fixture $d)
    }
    Copy-Item -LiteralPath $audit -Destination (Join-Path $fixture 'deploy\staging\kw\kx_readonly_preflight.ps1')
    Copy-Item -LiteralPath (Join-Path $root 'deploy\windows\Caddyfile') -Destination (Join-Path $fixture 'deploy\windows\Caddyfile')
    Copy-Item -LiteralPath (Join-Path $root 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY') -Destination (Join-Path $fixture 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY')
    Copy-Item -LiteralPath (Join-Path $root 'deploy\staging\kw\Caddyfile.ci') -Destination (Join-Path $fixture 'deploy\staging\kw\Caddyfile.ci')
    Copy-Item -LiteralPath (Join-Path $root 'app\public_control\kv_virtual_staging.py') -Destination (Join-Path $fixture 'app\public_control\kv_virtual_staging.py')

    $fake = Join-Path $fixture 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY'
    $injected = (Get-Content -LiteralPath $fake -Raw) -replace '\{remote_host\}', '8.8.8.8'
    $injected | Set-Content -LiteralPath $fake -Encoding UTF8
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $fixture 'deploy\staging\kw\kx_readonly_preflight.ps1') -Mode Repository
    if ($LASTEXITCODE -ne 2) {
        throw 'K-X: preflight no detecto IP insegura; debe devolver exit 2'
    }
    Write-Output '[K-X TEST] Mutacion insegura bloqueada: NO-GO correcto'
}
finally {
    if (Test-Path -LiteralPath $fixture) {
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
}
# Modo Windows Server ejecutado en un runner SIN instalacion real:
# debe devolver NO-GO ante una carpeta de estado inexistente.
# No se crea carpeta bajo ProgramData ni se consulta una red.
$nonexistentState = Join-Path $env:ProgramData ('KX-NoInstall-' + [guid]::NewGuid().ToString('N'))
& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $audit -Mode Server -StateDirectory $nonexistentState
if ($LASTEXITCODE -ne 2) {
    throw 'K-X: Server debe negar un despliegue no instalado sin tocar tareas'
}
Write-Output '[K-X TEST] Modo Server sin instalacion => NO-GO correcto'
Write-Output '[K-X TEST] 4 comprobaciones Windows, sin tareas reales ni conexiones AWS'
# El ultimo subproceso fallo deliberadamente con 2 (NO-GO esperado);
# restaurar exit 0 del harness tras comprobarlo expresamente.
exit 0
