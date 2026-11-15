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

$venvRoot = 'C:\Program Files\VehiculoIoT\.venv'
$launcherImage = Join-Path $venvRoot 'Scripts\python.exe'
$baseHome = 'C:\Python312'
$baseImage = Join-Path $baseHome 'python.exe'
$supervisorImage = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$supervisorArgs = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Program Files\VehiculoIoT\deploy\windows\run_api.ps1" -StateDirectory "C:\ProgramData\VehiculoIoT"'
$supervisorCommand = '"{0}" {1}' -f $supervisorImage, $supervisorArgs
$uvicorn = '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --log-level warning'
$command = '"{0}" {1}' -f $launcherImage, $uvicorn
$supervisorDate = $date.AddSeconds(-1)
$ownerDate = $date.AddMilliseconds(1)
$config = @(
    "home = $baseHome"
    'include-system-site-packages = false'
    'version = 3.12.9'
    "executable = $baseImage"
    ('command = {0} -m venv {1}' -f $baseImage, $venvRoot)
)

function Mock-KADChainProcess([int]$ProcessId, [int]$ParentProcessId, [datetime]$Created,
        [string]$Image, [AllowNull()][string]$CommandLine) {
    [pscustomobject]@{
        ProcessId = $ProcessId; ParentProcessId = $ParentProcessId; CreationDate = $Created
        ExecutablePath = $Image; CommandLine = $CommandLine
    }
}

$owner = Mock-KADChainProcess 5252 4242 $ownerDate $baseImage $command
$supervisor = Mock-KADChainProcess 2121 1111 $supervisorDate $supervisorImage $supervisorCommand
$launcher = Mock-KADChainProcess 4242 2121 $date $launcherImage $command
$apiListener = [pscustomobject]@{OwningProcess=5252;LocalAddress='127.0.0.1';LocalPort=8000}
$directApiListener = [pscustomobject]@{OwningProcess=4242;LocalAddress='127.0.0.1';LocalPort=8000}
$caddyImage = 'C:\ProgramData\VehiculoIoT\bin\caddy.exe'
$caddyRecord = Mock-KADRecord 4242 $ticks $caddyImage
$caddyProcess = Mock-KADProcess 4242 $date $caddyImage
$caddyListener = [pscustomobject]@{OwningProcess=4242;LocalAddress='0.0.0.0';LocalPort=443}

$baseline = @{
    Listeners = @($apiListener)
    Record = Mock-KADRecord 4242 $ticks $launcherImage
    Process = $launcher
    ExpectedImagePath = $launcherImage
    AllowPythonVenvRedirector = $true
    ListenerProcess = $owner
    VenvConfigLines = $config
    SupervisorRecord = Mock-KADRecord 2121 $supervisorDate.Ticks.ToString() $supervisorImage
    SupervisorProcess = $supervisor
    ExpectedSupervisorImagePath = $supervisorImage
    ExpectedSupervisorArguments = $supervisorArgs
}

$venvCases = @(
    @{Name='venv CPython: el hijo directo posee el unico listener'; Changes=@{}; Safe=$true; Redirected=$true},
    @{Name='venv CPython anterior con solo metadatos obligatorios'; Changes=@{VenvConfigLines=$config[0..2]}; Safe=$true; Redirected=$true},
    @{Name='Start-Process puede agregar un espacio final a ambos comandos'; Changes=@{
        Process=(Mock-KADChainProcess 4242 2121 $date $launcherImage ($command + ' '));
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command + ' '))}; Safe=$true; Redirected=$true},
    @{Name='API posee su propio listener'; Changes=@{Listeners=@($directApiListener);ListenerProcess=$null}; Safe=$true},
    @{Name='Caddy conserva atribucion directa incluso con dos listeners'; Changes=@{
        Listeners=@($caddyListener,[pscustomobject]@{OwningProcess=4242;LocalAddress='::';LocalPort=443});
        Record=$caddyRecord;Process=$caddyProcess;ExpectedImagePath=$caddyImage;AllowPythonVenvRedirector=$false}; Safe=$true},
    @{Name='Caddy no hereda la excepcion de Python'; Changes=@{
        Listeners=@([pscustomobject]@{OwningProcess=5252;LocalAddress='0.0.0.0';LocalPort=443});
        Record=$caddyRecord;Process=$caddyProcess;ExpectedImagePath=$caddyImage;AllowPythonVenvRedirector=$false}; Safe=$false},
    @{Name='requiere habilitacion explicita de la excepcion'; Changes=@{AllowPythonVenvRedirector=$false}; Safe=$false},
    @{Name='rechaza proxy intermedio en vez de hijo directo'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4222 $ownerDate $baseImage $command)}; Safe=$false},
    @{Name='rechaza hijo fuera de la identidad del listener'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5253 4242 $ownerDate $baseImage $command)}; Safe=$false},
    @{Name='rechaza launcher desligado del supervisor'; Changes=@{
        Process=(Mock-KADChainProcess 4242 2000 $date $launcherImage $command)}; Safe=$false},
    @{Name='rechaza supervisor ausente'; Changes=@{SupervisorProcess=$null}; Safe=$false},
    @{Name='rechaza supervisor con PID reciclado'; Changes=@{
        SupervisorProcess=(Mock-KADChainProcess 2121 1111 $supervisorDate.AddTicks(-10) $supervisorImage $supervisorCommand)}; Safe=$false},
    @{Name='rechaza supervisor con ejecutable sustituido'; Changes=@{
        SupervisorProcess=(Mock-KADChainProcess 2121 1111 $supervisorDate $other $supervisorCommand)}; Safe=$false},
    @{Name='rechaza supervisor con otro comando de tarea'; Changes=@{
        SupervisorProcess=(Mock-KADChainProcess 2121 1111 $supervisorDate $supervisorImage ($supervisorCommand.Replace('run_api.ps1','run_caddy.ps1')))}; Safe=$false},
    @{Name='rechaza supervisor posterior al launcher'; Changes=@{
        SupervisorProcess=(Mock-KADChainProcess 2121 1111 $ownerDate $supervisorImage $supervisorCommand);
        SupervisorRecord=(Mock-KADRecord 2121 $ownerDate.Ticks.ToString() $supervisorImage)}; Safe=$false},
    @{Name='rechaza hijo creado antes del launcher'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $supervisorDate $baseImage $command)}; Safe=$false},
    @{Name='rechaza hijo creado en el mismo instante'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $date $baseImage $command)}; Safe=$false},
    @{Name='rechaza ejecutable base ajeno a home'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $other $command)}; Safe=$false},
    @{Name='rechaza launcher que no coincide con el registro'; Changes=@{
        Record=(Mock-KADRecord 4242 $ticks $other)}; Safe=$false},
    @{Name='rechaza launcher con PID reciclado'; Changes=@{
        Record=(Mock-KADRecord 4242 $ownerDate.Ticks.ToString() $launcherImage)}; Safe=$false},
    @{Name='rechaza propietario sin metadata CIM'; Changes=@{ListenerProcess=$null}; Safe=$false},
    @{Name='rechaza proceso sin linea de comandos'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage $null)}; Safe=$false},
    @{Name='rechaza argv0 distinto del launcher'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace($launcherImage, $other)))}; Safe=$false},
    @{Name='rechaza launcher con --reload aunque el hijo parezca valido'; Changes=@{
        Process=(Mock-KADChainProcess 4242 2121 $date $launcherImage ($command + ' --reload'))}; Safe=$false},
    @{Name='rechaza otro modulo con Uvicorn citado incidentalmente'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace('-m uvicorn', '-m unrelated uvicorn')))}; Safe=$false},
    @{Name='rechaza otro destino ASGI'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace('app.main:app', 'app.other:app')))}; Safe=$false},
    @{Name='rechaza host abierto'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace('--host 127.0.0.1', '--host 0.0.0.0')))}; Safe=$false},
    @{Name='rechaza otro puerto'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace('--port 8000', '--port 9444')))}; Safe=$false},
    @{Name='rechaza workers adicionales'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command.Replace('--workers 1', '--workers 2')))}; Safe=$false},
    @{Name='rechaza bandera extra que redefine host'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command + ' --host 0.0.0.0'))}; Safe=$false},
    @{Name='rechaza salto de linea en el comando de proceso'; Changes=@{
        ListenerProcess=(Mock-KADChainProcess 5252 4242 $ownerDate $baseImage ($command + "`n"))}; Safe=$false},
    @{Name='rechaza salida de pyvenv.cfg ausente'; Changes=@{VenvConfigLines=$null}; Safe=$false},
    @{Name='rechaza home relativo'; Changes=@{VenvConfigLines=@('home = Python312') + $config[1..2]}; Safe=$false},
    @{Name='rechaza home UNC'; Changes=@{VenvConfigLines=@('home = \\share\python') + $config[1..2]}; Safe=$false},
    @{Name='rechaza home ambiguo con dos declaraciones'; Changes=@{VenvConfigLines=$config + "HOME = $baseHome"}; Safe=$false},
    @{Name='rechaza version no numerica'; Changes=@{VenvConfigLines=$config[0..1] + 'version = false'}; Safe=$false},
    @{Name='rechaza inclusion de paquetes del sistema'; Changes=@{
        VenvConfigLines=@($config[0], 'include-system-site-packages = true', $config[2])}; Safe=$false},
    @{Name='rechaza ejecutable de pyvenv.cfg contradictorio'; Changes=@{
        VenvConfigLines=$config[0..2] + "executable = $other"}; Safe=$false},
    @{Name='rechaza command de pyvenv.cfg con otro entorno'; Changes=@{
        VenvConfigLines=$config[0..3] + ('command = {0} -m venv C:\OtroEntorno' -f $baseImage)}; Safe=$false},
    @{Name='rechaza metadato de pyvenv.cfg desconocido'; Changes=@{
        VenvConfigLines=$config + 'unrecognized = true'}; Safe=$false},
    @{Name='rechaza listener de API no-loopback'; Changes=@{
        Listeners=@([pscustomobject]@{OwningProcess=5252;LocalAddress='0.0.0.0';LocalPort=8000})}; Safe=$false},
    @{Name='rechaza listener fuera del puerto API'; Changes=@{
        Listeners=@([pscustomobject]@{OwningProcess=5252;LocalAddress='127.0.0.1';LocalPort=9444})}; Safe=$false},
    @{Name='rechaza listener adicional aunque tenga mismo propietario'; Changes=@{
        Listeners=@($apiListener,$apiListener)}; Safe=$false},
    @{Name='rechaza listeners mezclados de launcher e hijo'; Changes=@{
        Listeners=@($apiListener,$directApiListener)}; Safe=$false},
    @{Name='rechaza listeners mezclados de hijo e intruso'; Changes=@{
        Listeners=@($apiListener,[pscustomobject]@{OwningProcess=7777;LocalAddress='127.0.0.1';LocalPort=8000})}; Safe=$false}
)

$passed = 0
foreach ($test in $venvCases) {
    $parameters = $baseline.Clone()
    foreach ($field in $test.Changes.Keys) { $parameters[$field] = $test.Changes[$field] }
    $verdict = Test-KADProcessOwnership @parameters
    if ($verdict.IsSafe -ne $test.Safe) { throw ('[K-AD] Resultado inesperado: ' + $test.Name) }
    if ($verdict.UsesVenvRedirector -ne ($test.ContainsKey('Redirected') -and $test.Redirected)) {
        throw ('[K-AD] Atribucion incorrecta del redireccionador: ' + $test.Name)
    }
    if ($verdict.IsSafe -and (-not $verdict.IdentityMatches -or -not $verdict.AllListenersOwned)) {
        throw ('[K-AD] Componentes inconsistentes: ' + $test.Name)
    }
    $passed++
    Write-Output ('[K-AD CI] OK: ' + $test.Name)
}
Write-Output ('[K-AD CI] ' + $passed + '/' + $venvCases.Count + ' casos de redireccion CPython y aislamiento de Caddy.')
exit 0
