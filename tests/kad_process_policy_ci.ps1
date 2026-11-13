# K-AD: matriz de identidad de proceso PURE DATA, sin red ni procesos reales.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT') {
    throw 'K-AD solo Windows GitHub Actions.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
. (Join-Path $root 'deploy\staging\kw\kad_process_policy.ps1')
$binary = 'C:\VehiculoIoT\.venv\Scripts\python.exe'
$other = 'C:\Users\Public\python.exe'
$date = [DateTime]::SpecifyKind([datetime]'2026-11-13T13:00:00', [DateTimeKind]::Utc)
$ticks = $date.Ticks.ToString()
$record = [pscustomobject]@{process_id=4242;creation_ticks=$ticks;executable_path=$binary}
$process = [pscustomobject]@{ProcessId=4242;CreationDate=$date;ExecutablePath=$binary}
function Mock-KADPort([object]$PidValue) {
    return [pscustomobject]@{OwningProcess=$PidValue}
}
function Mock-KADRecord([object]$PidValue, [string]$TimeValue, [string]$ImageValue) {
    return [pscustomobject]@{process_id=$PidValue;creation_ticks=$TimeValue;executable_path=$ImageValue}
}
function Mock-KADProcess([object]$PidValue,[datetime]$Created,[string]$ImageValue) {
    return [pscustomobject]@{ProcessId=$PidValue;CreationDate=$Created;ExecutablePath=$ImageValue}
}
$ports = @((Mock-KADPort 4242))
$cases = @(
    @{Name='PID, inicio, imagen y dueño exactos'; L=$ports; R=$record; P=$process; E=$binary; Safe=$true},
    @{Name='IPv4 e IPv6: dos listeners mismo proceso'; L=@((Mock-KADPort 4242),(Mock-KADPort 4242)); R=$record; P=$process; E=$binary; Safe=$true},
    @{Name='imagen con distinto casing de Windows'; L=$ports; R=$record; P=$process; E=$binary.ToUpperInvariant(); Safe=$true},
    @{Name='sin listeners'; L=@(); R=$record; P=$process; E=$binary; Safe=$false},
    @{Name='PID extraño posee listener'; L=@((Mock-KADPort 5252)); R=$record; P=$process; E=$binary; Safe=$false},
    @{Name='un listener propio y otro intruso'; L=@((Mock-KADPort 4242),(Mock-KADPort 5252)); R=$record; P=$process; E=$binary; Safe=$false},
    @{Name='PID recirculado con inicio diferente'; L=$ports; R=(Mock-KADRecord 4242 '123' $binary); P=$process; E=$binary; Safe=$false},
    @{Name='registro apunta a otro PID'; L=$ports; R=(Mock-KADRecord 3000 $ticks $binary); P=$process; E=$binary; Safe=$false},
    @{Name='proceso vivo posee otro PID'; L=$ports; R=$record; P=(Mock-KADProcess 3333 $date $binary); E=$binary; Safe=$false},
    @{Name='imagen del proceso sustituida'; L=$ports; R=$record; P=(Mock-KADProcess 4242 $date $other); E=$binary; Safe=$false},
    @{Name='imagen del registro sustituida'; L=$ports; R=(Mock-KADRecord 4242 $ticks $other); P=$process; E=$binary; Safe=$false},
    @{Name='sin registro de supervisor'; L=$ports; R=$null; P=$process; E=$binary; Safe=$false},
    @{Name='sin proceso real'; L=$ports; R=$record; P=$null; E=$binary; Safe=$false},
    @{Name='PID nulo o invalido'; L=$ports; R=(Mock-KADRecord 0 $ticks $binary); P=$process; E=$binary; Safe=$false},
    @{Name='PID de owner no numerico'; L=@((Mock-KADPort 'fake')); R=$record; P=$process; E=$binary; Safe=$false},
    @{Name='ruta esperada ausente'; L=$ports; R=$record; P=$process; E=''; Safe=$false},
    @{Name='registro no tiene campos'; L=$ports; R=[pscustomobject]@{}; P=$process; E=$binary; Safe=$false}
)
$passed = 0
foreach ($test in $cases) {
    $verdict = Test-KADProcessOwnership -Listeners $test.L -Record $test.R -Process $test.P -ExpectedImagePath $test.E
    if ($verdict.IsSafe -ne $test.Safe) {
        throw ('[K-AD] Resultado inesperado: ' + $test.Name)
    }
    if ($verdict.IsSafe -and (-not $verdict.HasListeners -or
                             -not $verdict.IdentityMatches -or
                             -not $verdict.AllListenersOwned)) {
        throw ('[K-AD] Componentes inconsistentes: ' + $test.Name)
    }
    $passed++
    Write-Output ('[K-AD CI] OK: ' + $test.Name)
}
Write-Output ('[K-AD CI] ' + $passed + '/' + $cases.Count + ' casos de identidad; sin sockets, credenciales ni hardware.')
exit 0
