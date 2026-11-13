# K-AD: tabla de verdad ejecutable en Windows PowerShell 5.1, SIN redes.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT') {
    throw 'Prueba K-AD reservada al runner Windows de GitHub Actions.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
. (Join-Path $root 'deploy\staging\kw\kad_listener_policy.ps1')

function Mock-KADListener([string]$Address) {
    return [pscustomobject]@{LocalAddress = $Address}
}
$cases = @(
    @{ Name = 'legacy IPv4 local, sidecar apagado'; Legacy = @((Mock-KADListener '127.0.0.1')); Sidecar = @(); Safe = $true;  Present = $true;  Loopback = $true;  Absent = $true },
    @{ Name = 'legacy IPv6 local, sidecar apagado'; Legacy = @((Mock-KADListener '::1')); Sidecar = @(); Safe = $true; Present = $true; Loopback = $true; Absent = $true },
    @{ Name = 'legacy IPv4+IPv6 locales'; Legacy = @((Mock-KADListener '127.0.0.1'),(Mock-KADListener '::1')); Sidecar = @(); Safe = $true; Present = $true; Loopback = $true; Absent = $true },
    @{ Name = 'backend legacy no escucha'; Legacy = @(); Sidecar = @(); Safe = $false; Present = $false; Loopback = $false; Absent = $true },
    @{ Name = 'legacy expuesto en toda IPv4'; Legacy = @((Mock-KADListener '0.0.0.0')); Sidecar = @(); Safe = $false; Present = $true; Loopback = $false; Absent = $true },
    @{ Name = 'legacy expuesto en toda IPv6'; Legacy = @((Mock-KADListener '::')); Sidecar = @(); Safe = $false; Present = $true; Loopback = $false; Absent = $true },
    @{ Name = 'legacy expuesto en LAN'; Legacy = @((Mock-KADListener '192.168.1.82')); Sidecar = @(); Safe = $false; Present = $true; Loopback = $false; Absent = $true },
    @{ Name = 'legacy local y expuesto simultaneamente'; Legacy = @((Mock-KADListener '127.0.0.1'),(Mock-KADListener '0.0.0.0')); Sidecar = @(); Safe = $false; Present = $true; Loopback = $false; Absent = $true },
    @{ Name = 'sidecar 9444 ocupado en loopback'; Legacy = @((Mock-KADListener '127.0.0.1')); Sidecar = @((Mock-KADListener '127.0.0.1')); Safe = $false; Present = $true; Loopback = $true; Absent = $false },
    @{ Name = 'sidecar 9444 publico'; Legacy = @((Mock-KADListener '127.0.0.1')); Sidecar = @((Mock-KADListener '0.0.0.0')); Safe = $false; Present = $true; Loopback = $true; Absent = $false },
    @{ Name = 'ausencia legacy con sidecar presente'; Legacy = @(); Sidecar = @((Mock-KADListener '::1')); Safe = $false; Present = $false; Loopback = $false; Absent = $false }
)
$passed = 0
foreach ($test in $cases) {
    $verdict = Test-KADPortPolicy -LegacyListeners $test.Legacy -SidecarListeners $test.Sidecar
    if ($verdict.IsSafe -ne $test.Safe -or
        $verdict.LegacyPresent -ne $test.Present -or
        $verdict.LegacyLoopbackOnly -ne $test.Loopback -or
        $verdict.SidecarAbsent -ne $test.Absent) {
        throw ('[K-AD] Política incorrecta: ' + $test.Name)
    }
    $passed += 1
    Write-Output ('[K-AD CI] OK: ' + $test.Name)
}
Write-Output ('[K-AD CI] ' + $passed + '/' + $cases.Count + ' casos de listeners aprobados; sin sockets ni servicio EC2.')
exit 0
