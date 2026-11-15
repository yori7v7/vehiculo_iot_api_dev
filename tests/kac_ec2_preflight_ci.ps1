# K-AC: ensayo Windows PowerShell 5.1 SOLO en runner temporal.
# No usa tarea EC2, no abre sockets ni escribe fuera del fixture CI.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT') {
    throw 'K-AC solo GitHub Actions Windows.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$script = Join-Path $root 'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tokens = $null
$errors = $null
$null = [Management.Automation.Language.Parser]::ParseFile(
    $script, [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) { throw 'K-AC: sintaxis PowerShell 5.1 inválida' }
Write-Output '[K-AC CI] OK: parser Windows PowerShell 5.1'

& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Mode Repository
if ($LASTEXITCODE -ne 0) { throw 'K-AC: repositorio válido rechazado' }
Write-Output '[K-AC CI] OK: repository no altera servicios'

$fixture = Join-Path $env:RUNNER_TEMP ('kac-negative-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($dir in @('deploy\staging\kw','deploy\windows','app\public_control')) {
        New-Item -Path (Join-Path $fixture $dir) -ItemType Directory -Force | Out-Null
    }
    foreach ($file in @(
        'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1',
        'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY',
        'deploy\windows\Caddyfile',
        'deploy\windows\install.ps1',
        'app\public_control\kab_windows_staging.py'
    )) {
        Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $fixture $file)
    }
    # El intento de copiar un valor fijo de CI al proxy real debe fallar.
    $wrong = Join-Path $fixture 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY'
    $replaced = (Get-Content -LiteralPath $wrong -Raw) -replace
        'header_up X-Admission-Client-IP \{remote_host\}',
        'header_up X-Admission-Client-IP 8.8.8.8'
    $replaced | Set-Content -LiteralPath $wrong -Encoding UTF8
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $fixture 'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1') -Mode Repository
    if ($LASTEXITCODE -ne 2) { throw 'K-AC: proxy inseguro no produjo NO-GO' }
    Write-Output '[K-AC CI] OK: identidad de cliente sintética detectada y bloqueada'
}
finally {
    if (Test-Path -LiteralPath $fixture) {
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
}
# No heredar el código 2 esperado del subproceso de prueba negativa.
exit 0
