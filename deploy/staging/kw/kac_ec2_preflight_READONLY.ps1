# K-AC — PREVUELO DE DESPLIEGUE, EXCLUSIVAMENTE LECTURA (PowerShell 5.1).
# Nunca instala/modifica Task Scheduler, Caddy, Firewall, EC2 ni credenciales.
# Modo Repository funciona desconectado. Modo Server requiere Windows/EC2
# previamente encendido por el operador en una ventana AUTORIZADA; no lo hace.
[CmdletBinding()]
param(
    [ValidateSet('Repository','Server')][string]$Mode = 'Repository',
    [string]$LegacyStateDirectory,
    [string]$LegacyProjectRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).ProviderPath
$script:failures = New-Object 'System.Collections.Generic.List[string]'
$script:passed = New-Object 'System.Collections.Generic.List[string]'
# Public status contains only fixed diagnostic categories, never OS exception text.
$script:phase = 'repositorio'

function Test-KAC([bool]$Ok, [string]$Message) {
    if ($Ok) { $script:passed.Add($Message) }
    else { $script:failures.Add($Message) }
}
function Read-KAC([string]$Name) {
    if (-not (Test-Path -LiteralPath $Name -PathType Leaf)) {
        throw 'Falta uno de los archivos estructurales.'
    }
    return [string](Get-Content -LiteralPath $Name -Raw -Encoding UTF8)
}
function Normalize-KAC([string]$Value) { return (($Value -replace "`r`n?", "`n").Trim()) }
function HasUnsafeWrite-KAC([string]$Path) {
    $mask = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    $everyone = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    foreach ($r in $rules) {
        if ($r.AccessControlType -eq 'Allow' -and
            $r.IdentityReference.Value -in $everyone -and
            (($r.FileSystemRights -band $mask) -ne 0)) { return $true }
    }
    return $false
}

function Get-KACLocalPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2) -match '[:*\?"<>\|\x00-\x1f]') {
        throw 'Se espera una ruta absoluta de un volumen local.'
    }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Get-KACArtifact([string]$Path, [bool]$Directory, [switch]$Protected, [switch]$Ancestor) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -ne $Directory -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'KAC_ARTEFACTO_TIPO_O_REPARSE'
    }
    if ($Protected -or $Ancestor) {
        # SYSTEM, Administrators and TrustedInstaller can replace these artifacts.
        $trusted = @('S-1-5-18', 'S-1-5-32-544',
            'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
        $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
        $write = [Security.AccessControl.FileSystemRights]::Delete -bor
            [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
            [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [Security.AccessControl.FileSystemRights]::TakeOwnership -bor 0x10000000 # GENERIC_ALL
        if ($Protected) {
            $write = $write -bor [Security.AccessControl.FileSystemRights]::Write -bor 0x40000000 # GENERIC_WRITE
        }
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted) {
            throw 'KAC_ACL_PROPIETARIO'
        }
        foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
            if ($rule.AccessControlType -eq 'Allow' -and
                $rule.IdentityReference.Value -notin $trusted -and
                -not ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -and
                ($rule.FileSystemRights -band $write)) {
                if ($rule.IsInherited) { throw 'KAC_ACL_ESCRITURA_HEREDADA' }
                throw 'KAC_ACL_ESCRITURA_EXPLICITA'
            }
        }
    }
    return $item
}

function Assert-KACLocalParents([string]$Path) {
    $parent = [IO.Path]::GetDirectoryName($Path)
    while ($parent) {
        # A parent may allow creation of unrelated entries, but cannot allow
        # ordinary users to replace the protected path beneath it.
        $null = Get-KACArtifact $parent $true -Ancestor
        $parent = [IO.Path]::GetDirectoryName($parent)
    }
}

function Get-KACProcess([int]$ProcessId) {
    if ($ProcessId -le 0) { throw 'Identificador de proceso invalido.' }
    $matches = @(Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $ProcessId) -ErrorAction Stop)
    if ($matches.Count -ne 1 -or $matches[0].ProcessId -ne $ProcessId) {
        throw 'El proceso registrado no tiene una identidad viva unica.'
    }
    return $matches[0]
}

function Read-KACObservedProcess([hashtable]$Observed, [int]$ProcessId) {
    if ($Observed.ContainsKey($ProcessId)) {
        throw 'El mismo PID aparece en mas de un rol de proceso.'
    }
    $process = Get-KACProcess $ProcessId
    $Observed[$ProcessId] = $process
    return $process
}

function Test-KACSameProcess($Before, $After) {
    return $Before.ProcessId -eq $After.ProcessId -and
        $Before.ParentProcessId -eq $After.ParentProcessId -and
        $Before.CreationDate -eq $After.CreationDate -and
        $Before.ExecutablePath -eq $After.ExecutablePath -and
        $Before.CommandLine -ceq $After.CommandLine
}

function Get-KACListeners {
    # A single full query distinguishes an unoccupied port from a provider failure.
    Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -in @(443, 8000, 9444) }
}

try {
    $originalPath = Join-Path $root 'deploy\windows\Caddyfile'
    $candidatePath = Join-Path $root 'deploy\staging\kw\Caddyfile.candidate_NOT_DEPLOY'
    $legacyInstallPath = Join-Path $root 'deploy\windows\install.ps1'
    $kabPath = Join-Path $root 'app\public_control\kab_windows_staging.py'
    $original = Normalize-KAC (Read-KAC $originalPath)
    $candidate = Read-KAC $candidatePath
    $installer = Read-KAC $legacyInstallPath
    $kab = Read-KAC $kabPath

    Test-KAC ($original -eq "100-30-4-62.nip.io {`n    reverse_proxy 127.0.0.1:8000`n}") 'Caddyfile plantilla conserva SOLO el puerto 8000'
    Test-KAC ($candidate.Contains('reverse_proxy 127.0.0.1:8000') -and
        $candidate.Contains('reverse_proxy 127.0.0.1:9444')) 'Candidato mantiene rutas legacy separadas de virtual'
    Test-KAC ($candidate.Contains('header_up X-Admission-Client-IP {remote_host}') -and
        (-not $candidate.Contains('8.8.8.8'))) 'Candidato no fija IP de prueba'
    Test-KAC ($candidate.Contains('header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}')) 'Caddy candidato requiere secreto ajeno al repositorio'
    Test-KAC ($kab.Contains('enabled') -and $kab.Contains('service_sid') -and
        $kab.Contains('127.0.0.1') -and $kab.Contains('9444') -and
        $kab.Contains('S-1-5-19')) 'Lanzador staging exige SID dedicada y activación explícita'
    Test-KAC (-not $installer.Contains('VehiculoIoT-Admission-Staging')) 'Instalador legacy no registra tareas experimentales'

    if ($Mode -eq 'Server') {
        if ($env:OS -ne 'Windows_NT') { throw 'Server solamente se revisa en Windows.' }
        $programData = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\')
        if ([string]::IsNullOrWhiteSpace($LegacyStateDirectory)) {
            $LegacyStateDirectory = Join-Path $programData 'VehiculoIoT'
        }
        $installed = Get-KACLocalPath $LegacyStateDirectory
        $legacyRoot = if ([string]::IsNullOrWhiteSpace($LegacyProjectRoot)) { $root }
            else { Get-KACLocalPath $LegacyProjectRoot }
        $stateInsideProgramData = $installed.StartsWith(($programData + '\'),
            [StringComparison]::OrdinalIgnoreCase)
        Test-KAC ($stateInsideProgramData) 'Estado legacy dentro de ProgramData'
        if (-not $stateInsideProgramData) {
            throw 'NO-GO: directorio de estado fuera de ProgramData'
        }
        if (-not (Test-Path -LiteralPath $installed -PathType Container)) {
            throw 'No existe el estado original de Windows.'
        }

        $script:phase = 'configuracion-estable'
        $configurationPath = Join-Path $installed 'deployment.json'
        $currentCaddyPath = Join-Path $installed 'Caddyfile'
        $null = Get-KACArtifact $installed $true -Protected
        Assert-KACLocalParents $configurationPath
        $null = Get-KACArtifact $configurationPath $false -Protected
        $null = Get-KACArtifact $currentCaddyPath $false
        $cfg = (Read-KAC $configurationPath) | ConvertFrom-Json
        $persistent = Normalize-KAC (Read-KAC $currentCaddyPath)
        # The audit checkout supplies templates, never the identity of installed binaries.
        $expectedPython = Join-Path $legacyRoot '.venv\Scripts\python.exe'
        $expectedCaddy = Join-Path $installed 'bin\caddy.exe'
        $configMatches = ($cfg.schema_version -eq 1) -and
            ($cfg.state_directory -eq $installed) -and
            ($cfg.project_root -eq $legacyRoot) -and
            ($cfg.caddyfile_path -eq $currentCaddyPath) -and
            ($cfg.python_path -eq $expectedPython) -and
            ($cfg.caddy_path -eq $expectedCaddy)
        Test-KAC $configMatches 'deployment.json corresponde a la instalacion legacy, binarios y estado real'
        if (-not $configMatches) { throw 'Configuracion legacy discrepante.' }
        Test-KAC (-not (HasUnsafeWrite-KAC $installed)) 'Directorio de estado legacy no editable por usuarios comunes'
        Test-KAC ($persistent.Contains('reverse_proxy 127.0.0.1:8000') -and
            (-not $persistent.Contains('127.0.0.1:9444'))) 'Caddy persistente conserva la ruta anterior antes de cambios'
        Test-KAC (-not (HasUnsafeWrite-KAC $currentCaddyPath)) 'Caddy persistente no editable por usuarios comunes'
        foreach ($path in @($legacyRoot, (Join-Path $legacyRoot 'app'), $expectedPython, $expectedCaddy)) {
            Test-KAC ((Test-Path -LiteralPath $path) -and (-not (HasUnsafeWrite-KAC $path))) 'Codigo/Python no modificable por usuarios comunes'
        }
        # No confundir plantilla y Caddy activo. La revisión verifica
        # autoridad y acciones EXACTAS, sin arrancar servicios.
        $script:phase = 'tareas-estables'
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $scriptNames = @('api','caddy')
        $taskNames = @('VehiculoIoT-FastAPI','VehiculoIoT-Caddy')
        $apiTaskArguments = $null
        for($i=0;$i -lt 2;$i++) {
            $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskNames[$i] -ErrorAction SilentlyContinue
            if($null -eq $task) {
                $script:failures.Add('No se encontró tarea legacy esperada')
                continue
            }
            $runScript = Join-Path $legacyRoot ('deploy\windows\run_' + $scriptNames[$i] + '.ps1')
            $arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -StateDirectory "{1}"' -f $runScript, $installed
            Test-KAC (@($task.Actions).Count -eq 1 -and
                $task.Actions[0].Execute -eq $powershell -and
                $task.Actions[0].Arguments -eq $arguments -and
                $task.Actions[0].WorkingDirectory -eq $legacyRoot) 'Acción de tarea legacy coincide sin modificaciones'
            Test-KAC ($task.Principal.UserId -in @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')) 'Principal de tarea legacy original'
            Test-KAC ([string]$task.State -eq 'Running') 'La tarea legacy original se mantiene ejecutando'
            $null = Get-KACArtifact $runScript $false
            Test-KAC (-not (HasUnsafeWrite-KAC $runScript)) 'Lanzador legacy no editable por usuarios comunes'
            if ($i -eq 0) { $apiTaskArguments = $arguments }
        }
        # Preflight ANTES del staging: sin 8000 no hay continuidad legacy;
        # con CUALQUIER 9444 activo no se debe asumir un estado limpio.
        # La política es una función pura, probada en Windows CI con fixtures.
        $script:phase = 'puertos'
        . (Join-Path $PSScriptRoot 'kad_listener_policy.ps1')
        $listeners = @(Get-KACListeners)
        $legacyListeners = @($listeners | Where-Object LocalPort -eq 8000)
        $sidecarListeners = @($listeners | Where-Object LocalPort -eq 9444)
        $portVerdict = Test-KADPortPolicy -LegacyListeners $legacyListeners -SidecarListeners $sidecarListeners
        Test-KAC ($portVerdict.LegacyPresent) 'Backend original 8000 tiene listener'
        Test-KAC ($portVerdict.LegacyLoopbackOnly) 'Todos los listeners legacy 8000 usan loopback'
        Test-KAC ($portVerdict.SidecarAbsent) 'Puerto staging 9444 desocupado antes de instalar'
        $expectedApiListener = $legacyListeners.Count -eq 1 -and $legacyListeners[0].LocalAddress -ceq '127.0.0.1'
        Test-KAC $expectedApiListener 'FastAPI tiene un unico listener en 127.0.0.1:8000'
        # K-AD: un puerto abierto no prueba identidad del servidor. Las tareas
        # originales registran PID + fecha de creación + imagen del proceso hijo
        # en ProgramData privado. El preflight solo lee y coteja ese registro
        # con el proceso Windows vivo y el PID dueño de cada socket.
        # NO se imprimen PID, rutas, tokens ni registros del host.
        . (Join-Path $PSScriptRoot 'kad_process_policy.ps1')
        $script:phase = 'registros-procesos'
        $runDirectory = Join-Path $installed 'run'
        $null = Get-KACArtifact $runDirectory $true -Protected
        $observed = @{}
        foreach ($component in @('api', 'caddy')) {
            $processRecordPath = Join-Path $installed ('run\' + $component + '.json')
            $null = Get-KACArtifact $processRecordPath $false -Protected
            $record = (Read-KAC $processRecordPath) | ConvertFrom-Json
            $child = $record.child
            $expectedImage = if ($component -eq 'api') { $expectedPython } else { $expectedCaddy }
            $processIdToInspect = [int]$child.process_id
            $livingProcess = Read-KACObservedProcess $observed $processIdToInspect
            $ownershipArgs = @{}
            $ownedListeners = if ($component -eq 'api') {
                # Recorded PowerShell -> venv redirector -> base Python.
                $ownershipArgs.AllowPythonVenvRedirector = $true
                $ownershipArgs.SupervisorRecord = $record.supervisor
                $supervisorId = [int]$record.supervisor.process_id
                $ownershipArgs.SupervisorProcess = Read-KACObservedProcess $observed $supervisorId
                $ownershipArgs.ExpectedSupervisorImagePath = $powershell
                $ownershipArgs.ExpectedSupervisorArguments = $apiTaskArguments
                if ($expectedApiListener -and $legacyListeners[0].OwningProcess -ne $processIdToInspect) {
                    $listenerId = [int]$legacyListeners[0].OwningProcess
                    $ownershipArgs.ListenerProcess = Read-KACObservedProcess $observed $listenerId
                    $venvDirectory = Join-Path $legacyRoot '.venv'
                    $script:phase = 'ancestros-venv'
                    Assert-KACLocalParents $expectedPython
                    $script:phase = 'archivos-venv'
                    $null = Get-KACArtifact $venvDirectory $true -Protected
                    $null = Get-KACArtifact (Join-Path $venvDirectory 'Scripts') $true -Protected
                    $launcher = Get-KACArtifact $expectedPython $false -Protected
                    $venvConfig = Join-Path $venvDirectory 'pyvenv.cfg'
                    $metadataFile = Get-KACArtifact $venvConfig $false -Protected
                    if ($metadataFile.Length -lt 1 -or $metadataFile.Length -gt 8192) {
                        throw 'Tamano invalido de pyvenv.cfg.'
                    }
                    $ownershipArgs.VenvConfigLines = @(Get-Content -LiteralPath $venvConfig -Encoding UTF8 -ErrorAction Stop)
                    $venv = Get-KADVenvMetadata -VenvConfigLines $ownershipArgs.VenvConfigLines -ExpectedImagePath $expectedPython
                    if ($null -eq $venv -or $ownershipArgs.ListenerProcess.ExecutablePath -ne $venv.BaseImagePath) {
                        throw 'El runtime del listener no coincide con pyvenv.cfg.'
                    }
                    $script:phase = 'ancestros-python-base'
                    Assert-KACLocalParents $venv.BaseImagePath
                    $script:phase = 'archivos-python-base'
                    $null = Get-KACArtifact ([IO.Path]::GetDirectoryName($venv.BaseImagePath)) $true -Protected
                    $basePython = Get-KACArtifact $venv.BaseImagePath $false -Protected
                    if ($launcher.VersionInfo.ProductVersion -cne $venv.Version -or
                        $basePython.VersionInfo.ProductVersion -cne $venv.Version) {
                        throw 'Version de Python incompatible con pyvenv.cfg.'
                    }
                }
                $legacyListeners
            } else {
                $listeners | Where-Object LocalPort -eq 443
            }
            $script:phase = if ($component -eq 'api') { 'identidad-api' } else { 'identidad-caddy' }
            $ownership = Test-KADProcessOwnership -Listeners @($ownedListeners) -Record $child -Process $livingProcess -ExpectedImagePath $expectedImage @ownershipArgs
            Test-KAC ($ownership.IsSafe) ('Propiedad de proceso y listeners '+ $component + ' confirmada')
            if ($ownership.IsSafe -and $ownership.UsesVenvRedirector) {
                $script:passed.Add('FastAPI: redireccionador de Python validado')
            }
        }
        $script:phase = 'estabilidad-procesos'
        foreach ($observedId in $observed.Keys) {
            Test-KAC (Test-KACSameProcess $observed[$observedId] (Get-KACProcess $observedId)) 'Identidad de proceso estable durante la inspeccion'
        }
        $latest = @(Get-KACListeners)
        $firstKeys = @($listeners | ForEach-Object { '{0}|{1}|{2}' -f $_.LocalPort,$_.LocalAddress,$_.OwningProcess } | Sort-Object)
        $latestKeys = @($latest | ForEach-Object { '{0}|{1}|{2}' -f $_.LocalPort,$_.LocalAddress,$_.OwningProcess } | Sort-Object)
        Test-KAC (($firstKeys -join ',') -ceq ($latestKeys -join ',')) 'Listeners estables durante la inspeccion'
        $script:phase = 'staging-deshabilitado'
        $staging = Join-Path $programData 'VehiculoIoT-Admission-Staging'
        # Un paquete preinstalado NO es una autorización de arranque.
        if (Test-Path -LiteralPath $staging -PathType Container) {
            Test-KAC (-not (HasUnsafeWrite-KAC $staging)) 'Carpeta de staging no editable por usuarios generales'
            $manifest = Join-Path $staging 'staging.json'
            if(Test-Path -LiteralPath $manifest -PathType Leaf) {
                # NO mostrar ni exportar manifiesto, SID ni secretos.
                $data = (Read-KAC $manifest) | ConvertFrom-Json
                Test-KAC ($data.enabled -eq $false) 'Staging sigue deshabilitado'
            }
        }
        else { $script:passed.Add('Staging aun no creado; estado esperado antes de instalacion') }
        $script:passed.Add('Solo consulta de tareas, ACL, puertos y metadata; ninguna escritura')
    }
}
catch {
    # Do not print exception messages: they may contain confidential host paths.
    $safeReasons = @{
        'KAC_ACL_PROPIETARIO' = 'propietario no autorizado'
        'KAC_ACL_ESCRITURA_HEREDADA' = 'permiso de escritura heredado fuera de la lista de confianza'
        'KAC_ACL_ESCRITURA_EXPLICITA' = 'permiso de escritura explicito fuera de la lista de confianza'
        'KAC_ARTEFACTO_TIPO_O_REPARSE' = 'tipo de archivo o redireccion inesperado'
    }
    $key = [string]$_.Exception.Message
    $reason = if ($safeReasons.ContainsKey($key)) { $safeReasons[$key] }
        else { 'comprobacion incompleta (detalle reservado)' }
    $script:failures.Add('Preflight incompleto; no iniciar ni modificar servicios')
    $script:failures.Add(('Categoria segura: {0}; {1}' -f $script:phase, $reason))
}
foreach ($line in $script:passed) { Write-Output ('[K-AC] OK: ' + $line) }
foreach ($line in $script:failures) { Write-Output ('[K-AC] NO-GO: ' + $line) }
if ($script:failures.Count -gt 0) { exit 2 }
Write-Output '[K-AC] Lectura finalizada. No autoriza instalación, reinicio ni apertura de puertos.'
exit 0
