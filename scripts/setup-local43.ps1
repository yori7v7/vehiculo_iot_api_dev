param(
    [Parameter(Mandatory=$true)][string]$MySqlBin,
    [Parameter(Mandatory=$true)][string]$HistoricalSql
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$data = Join-Path $repo 'build/mysql43'
$build = Join-Path $repo 'build'
$server = Join-Path $MySqlBin 'mysqld.exe'
$mysql = Join-Path $MySqlBin 'mysql.exe'
$sql = (Resolve-Path -LiteralPath $HistoricalSql).Path
$OutputEncoding = [Text.UTF8Encoding]::new($false)

if (Test-Path -LiteralPath $data) { throw 'Ya existe build/mysql43. Conserva los datos y usa la instancia preparada.' }
if (Get-NetTCPConnection -LocalPort 33343 -State Listen -ErrorAction SilentlyContinue) { throw 'El puerto 33343 está ocupado.' }
New-Item -ItemType Directory -Path $build -Force | Out-Null
& $server --no-defaults --initialize-insecure --console "--datadir=$data"
if ($LASTEXITCODE) { throw 'No se pudo inicializar MySQL aislado.' }
$log = Join-Path $build 'mysql43-console.log'
$proc = Start-Process -FilePath $server -ArgumentList @(
    '--no-defaults','--console',('--datadir="' + $data + '"'),'--port=33343',
    '--bind-address=127.0.0.1','--mysqlx=OFF','--skip-log-bin','--require-secure-transport=ON'
) -WindowStyle Hidden -PassThru -RedirectStandardError $log

$connection = @('--no-defaults','--host=127.0.0.1','--port=33343','--protocol=TCP',
                '--user=root','--ssl-mode=VERIFY_CA',("--ssl-ca=" + (Join-Path $data 'ca.pem')),
                '--default-character-set=utf8mb4')
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { throw "MySQL terminó. Consulta $log" }
    $directory = & $mysql @connection --batch --skip-column-names '--execute=SELECT @@datadir' 2>$null
    if (!$LASTEXITCODE -and $directory -and
        ([IO.Path]::GetFullPath($directory).TrimEnd([char]92,[char]47) -eq $data)) {
        $ready = $true
        break
    }
}
if (!$ready) { throw 'No se pudo verificar la instancia aislada.' }
Get-Content -LiteralPath $sql -Raw -Encoding UTF8 | & $mysql @connection
if ($LASTEXITCODE) { throw 'Falló la carga del esquema histórico.' }
foreach ($migration in @('000_preflight','001_plataforma_schema','002_plataforma_data','003_verify')) {
    Get-Content -LiteralPath (Join-Path $repo "scripts/migrations/$migration.sql") -Raw -Encoding UTF8 |
        & $mysql @connection vehiculo_iot |
        Tee-Object -FilePath (Join-Path $build "$migration.txt")
    if ($LASTEXITCODE) { throw "Falló $migration." }
}
Write-Output "MySQL aislado listo en 127.0.0.1:33343. PID $($proc.Id)."
