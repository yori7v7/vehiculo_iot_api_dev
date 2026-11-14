# K-AC Server: datos sintéticos, sin consultas reales de tareas, ACL, CIM o puertos.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT' -or
    $PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'K-AC Server requiere Windows PowerShell 5.1 con el entorno de pruebas.'
}

$repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$preflight = Join-Path $repository 'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1'
$legacy = Join-Path $env:SystemDrive 'KAC-Fixture\Legacy instalacion estable'
$state = Join-Path $env:ProgramData 'KAC-Fixture-Legacy-ReadOnly'
$caddyfile = Join-Path $state 'Caddyfile'
$caddyImage = Join-Path $state 'bin\caddy.exe'
$launcherImage = Join-Path $legacy '.venv\Scripts\python.exe'
$venvRoot = Join-Path $legacy '.venv'
$venvConfig = Join-Path $venvRoot 'pyvenv.cfg'
$baseHome = Join-Path $env:SystemDrive 'KAC-Fixture\Python312'
$baseImage = Join-Path $baseHome 'python.exe'
$powerShellImage = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runner = Join-Path $legacy 'deploy\windows'
$app = Join-Path $legacy 'app'
$configPath = Join-Path $state 'deployment.json'
$apiRecordPath = Join-Path $state 'run\api.json'
$caddyRecordPath = Join-Path $state 'run\caddy.json'
$created = [DateTime]::SpecifyKind([datetime]'2026-11-13T14:00:00', [DateTimeKind]::Utc)
$configuration = [ordered]@{
    schema_version = 1; state_directory = $state; project_root = $legacy
    caddyfile_path = $caddyfile; python_path = $launcherImage; caddy_path = $caddyImage
}
$fixtureFiles = @{
    $configPath = ($configuration | ConvertTo-Json -Compress)
    $caddyfile = "example.invalid {`n    reverse_proxy 127.0.0.1:8000`n}"
    $venvConfig = @(
        "home = $baseHome"
        'include-system-site-packages = false'
        'version = 3.12.9'
        "executable = $baseImage"
        ('command = {0} -m venv {1}' -f $baseImage, $venvRoot)
    ) -join "`r`n"
}
$knownFixturePaths = @(
    $legacy, $state, $caddyfile, $caddyImage, $launcherImage, $venvRoot, $venvConfig, $baseHome, $baseImage,
    $powerShellImage, $runner, $app, $configPath, $apiRecordPath, $caddyRecordPath,
    (Join-Path $state 'run'), (Join-Path $state 'bin'), (Join-Path $legacy '.venv\Scripts'),
    (Join-Path $legacy 'deploy'), (Join-Path $runner 'run_api.ps1'), (Join-Path $runner 'run_caddy.ps1'),
    (Join-Path $env:SystemDrive 'KAC-Fixture'), $env:ProgramData, $env:SystemRoot,
    (Join-Path $env:SystemRoot 'System32'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell'),
    (Split-Path -Parent $powerShellImage), ($env:SystemDrive + '\')
)

function New-FixtureProcess([int]$ProcessId, [int]$ParentId, [datetime]$Started,
        [string]$Image, [string]$Command) {
    [pscustomobject]@{
        ProcessId = $ProcessId; ParentProcessId = $ParentId; CreationDate = $Started
        ExecutablePath = $Image; CommandLine = $Command
    }
}
function New-FixtureRecord($Supervisor, $Child) {
    $identities = foreach ($process in @($Supervisor,$Child)) {
        @{ process_id=$process.ProcessId; creation_ticks=[string]$process.CreationDate.Ticks; executable_path=$process.ExecutablePath }
    }
    return @{ supervisor=$identities[0]; child=$identities[1] } | ConvertTo-Json -Compress
}

$apiArguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -StateDirectory "{1}"' -f (Join-Path $runner 'run_api.ps1'), $state
$caddyArguments = $apiArguments.Replace('run_api.ps1','run_caddy.ps1')
$uvicornArgs = '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --log-level warning'
$uvicornCommand = '"{0}" {1}' -f $launcherImage, $uvicornArgs
$apiSupervisor = New-FixtureProcess 4100 4000 $created $powerShellImage ('"{0}" {1}' -f $powerShellImage, $apiArguments)
$launcherProcess = New-FixtureProcess 4200 4100 $created.AddSeconds(1) $launcherImage $uvicornCommand
$listenerOwner = New-FixtureProcess 4300 4200 $created.AddSeconds(2) $baseImage $uvicornCommand
$caddySupervisor = New-FixtureProcess 5100 4000 $created $powerShellImage ('"{0}" {1}' -f $powerShellImage, $caddyArguments)
$caddyProcess = New-FixtureProcess 5200 5100 $created.AddSeconds(1) $caddyImage $caddyImage
$fixtureFiles[$apiRecordPath] = New-FixtureRecord $apiSupervisor $launcherProcess
$fixtureFiles[$caddyRecordPath] = New-FixtureRecord $caddySupervisor $caddyProcess

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath, [string]$TaskName)
    if ($TaskPath -ne '\' -or $TaskName -notin @('VehiculoIoT-FastAPI','VehiculoIoT-Caddy')) { throw 'Unexpected task read.' }
    $arguments = if ($TaskName -eq 'VehiculoIoT-FastAPI') { $apiArguments } else { $caddyArguments }
    $workingDirectory = if ($scenario -eq 'wrong-working-directory') { $repository } else { $legacy }
    [pscustomobject]@{
        State='Running'; Principal=[pscustomobject]@{UserId='S-1-5-18'}
        Actions=@([pscustomobject]@{Execute=$powerShellImage;Arguments=$arguments;WorkingDirectory=$workingDirectory})
    }
}

function Get-NetTCPConnection {
    [CmdletBinding()]
    param([int]$LocalPort, [string]$State)
    if ($State -ne 'Listen' -or $PSBoundParameters.ContainsKey('LocalPort')) { throw 'Unexpected socket query.' }
    if ($scenario -eq 'socket-error') { throw 'Socket inspection failed.' }
    $observations.Sockets++
    $ownerId = switch ($scenario) {
        'direct' { 4200 }
        'socket-changed' { if ($observations.Sockets -gt 1) { 4444 } else { 4300 } }
        default { 4300 }
    }
    [pscustomobject]@{OwningProcess=$ownerId;LocalPort=8000;LocalAddress='127.0.0.1';State='Listen'}
    $caddyOwner = if ($scenario -eq 'invalid-caddy-owner') { 4300 } else { 5200 }
    [pscustomobject]@{OwningProcess=$caddyOwner;LocalPort=443;LocalAddress='0.0.0.0';State='Listen'}
    if ($scenario -eq 'extra-listener') {
        [pscustomobject]@{OwningProcess=4300;LocalPort=8000;LocalAddress='127.0.0.1';State='Listen'}
    }
    if ($scenario -eq 'sidecar-listener') {
        [pscustomobject]@{OwningProcess=5200;LocalPort=9444;LocalAddress='127.0.0.1';State='Listen'}
    }
}

function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [string]$Filter)
    if ($ClassName -ne 'Win32_Process') { throw 'Unexpected CIM class.' }
    switch ($Filter) {
        'ProcessId = 4100' { $apiSupervisor }
        'ProcessId = 4200' { $launcherProcess }
        'ProcessId = 4300' {
            if ($scenario -eq 'cim-error') { throw 'Process inspection failed.' }
            $observations.Owner++
            if ($scenario -eq 'invalid-parent') {
                New-FixtureProcess 4300 4400 $listenerOwner.CreationDate $baseImage $uvicornCommand
            } elseif ($scenario -eq 'cim-changed' -and $observations.Owner -gt 1) {
                New-FixtureProcess 4300 4200 $listenerOwner.CreationDate.AddSeconds(1) $baseImage $uvicornCommand
            } else { $listenerOwner }
        }
        'ProcessId = 5100' { $caddySupervisor }
        'ProcessId = 5200' { $caddyProcess }
        default { throw 'Unexpected process query.' }
    }
}

function Get-Acl {
    [CmdletBinding()]
    param([string]$LiteralPath)
    if ($LiteralPath -notin $knownFixturePaths) { throw 'Unexpected ACL read.' }
    $acl = New-Object PSObject
    $rules = @()
    if ($LiteralPath -eq (Join-Path $env:SystemDrive 'KAC-Fixture') -and
        $scenario -in @('unsafe-parent-acl','inherit-only-parent-acl')) {
        $propagation = if ($scenario -eq 'inherit-only-parent-acl') {
            [Security.AccessControl.PropagationFlags]::InheritOnly
        } else { [Security.AccessControl.PropagationFlags]::None }
        $rules = @([pscustomobject]@{
            AccessControlType = 'Allow'
            IdentityReference = [pscustomobject]@{Value = 'S-1-5-32-545'}
            FileSystemRights = [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
            PropagationFlags = $propagation
        })
    }
    $acl | Add-Member NoteProperty FixtureRules $rules
    $acl | Add-Member ScriptMethod GetAccessRules {
        param($Explicit, $Inherited, $IdentityType)
        return $this.FixtureRules
    }
    $ownerSid = if ($scenario -eq 'untrusted-config-owner' -and $LiteralPath -eq $venvConfig) {
        'S-1-5-32-545'
    } else { 'S-1-5-32-544' }
    $acl | Add-Member NoteProperty FixtureOwnerSid $ownerSid
    $acl | Add-Member ScriptMethod GetOwner {
        param($IdentityType)
        return [pscustomobject]@{Value=$this.FixtureOwnerSid}
    }
    return $acl
}

function Resolve-Path {
    [CmdletBinding()]
    param([string]$LiteralPath)
    if ($LiteralPath -in $knownFixturePaths) { return [pscustomobject]@{ProviderPath=$LiteralPath} }
    if ($LiteralPath.StartsWith($repository, [StringComparison]::OrdinalIgnoreCase)) {
        return Microsoft.PowerShell.Management\Resolve-Path -LiteralPath $LiteralPath
    }
    throw 'Unexpected path resolution.'
}

function Test-Path {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -in $knownFixturePaths) { return $true }
    if ($LiteralPath.StartsWith($repository, [StringComparison]::OrdinalIgnoreCase)) {
        return Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
    }
    return $false
}

function Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Force)
    if ($LiteralPath -notin $knownFixturePaths) { throw 'Unexpected file metadata read.' }
    $attributes = if ($scenario -eq 'linked-config' -and $LiteralPath -eq $venvConfig) {
        [IO.FileAttributes]::ReparsePoint
    } else { [IO.FileAttributes]::Normal }
    $container = $LiteralPath -notmatch '\.(?:exe|cfg|json|ps1)$' -and $LiteralPath -ne $caddyfile
    $version = if ($scenario -eq 'wrong-base-version' -and $LiteralPath -eq $baseImage) { '3.12.8' } else { '3.12.9' }
    [pscustomobject]@{
        FullName=$LiteralPath; Attributes=$attributes; PSIsContainer=$container; Length=256
        LastWriteTimeUtc=$created.AddSeconds(-1); CreationTimeUtc=$created.AddSeconds(-2)
        VersionInfo=[pscustomobject]@{ProductVersion=$version}
    }
}

function Get-Content {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Raw, [string]$Encoding)
    if ($LiteralPath.StartsWith($repository, [StringComparison]::OrdinalIgnoreCase)) {
        return Microsoft.PowerShell.Management\Get-Content @PSBoundParameters
    }
    if (-not $fixtureFiles.ContainsKey($LiteralPath)) { throw 'Unexpected file read.' }
    if ($LiteralPath -eq $venvConfig -and $scenario -eq 'config-error') { throw 'Config read failed.' }
    $text = $fixtureFiles[$LiteralPath]
    if ($Raw) { return $text }
    return $text -split '\r?\n'
}

$cases = @(
    @{Name='redirector';ExpectedExit=0;Root=$legacy;Message='FastAPI: redireccionador de Python validado'},
    @{Name='direct';ExpectedExit=0;Root=$legacy;Message='Propiedad de proceso y listeners api confirmada'},
    @{Name='inherit-only-parent-acl';ExpectedExit=0;Root=$legacy;Message='FastAPI: redireccionador de Python validado'},
    @{Name='wrong-project';ExpectedExit=2;Root=$repository;Message='deployment.json corresponde'},
    @{Name='wrong-working-directory';ExpectedExit=2;Root=$legacy;Message='de tarea legacy coincide'},
    @{Name='invalid-parent';ExpectedExit=2;Root=$legacy;Message='Propiedad de proceso y listeners api confirmada'},
    @{Name='invalid-caddy-owner';ExpectedExit=2;Root=$legacy;Message='Propiedad de proceso y listeners caddy confirmada'},
    @{Name='extra-listener';ExpectedExit=2;Root=$legacy;Message='FastAPI tiene un unico listener'},
    @{Name='sidecar-listener';ExpectedExit=2;Root=$legacy;Message='Puerto staging 9444 desocupado'},
    @{Name='socket-error';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='socket-changed';ExpectedExit=2;Root=$legacy;Message='Listeners estables durante'},
    @{Name='cim-error';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='cim-changed';ExpectedExit=2;Root=$legacy;Message='Identidad de proceso estable durante'},
    @{Name='config-error';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='linked-config';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='untrusted-config-owner';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='unsafe-parent-acl';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'},
    @{Name='wrong-base-version';ExpectedExit=2;Root=$legacy;Message='Preflight incompleto'}
)
foreach ($case in $cases) {
    $scenario = $case.Name
    $observations = @{Sockets=0;Owner=0}
    $output = @(& $preflight -Mode Server -LegacyStateDirectory $state -LegacyProjectRoot $case.Root)
    $actual = $LASTEXITCODE
    $statusPattern = if ($case.ExpectedExit -eq 0) { 'OK:' } else { 'NO-GO:' }
    $expectedLine = '^\[K-AC\] ' + $statusPattern + ' .*' + [regex]::Escape($case.Message)
    if ($actual -ne $case.ExpectedExit -or -not ($output -match $expectedLine) -or
        ($scenario -eq 'direct' -and ($output -match 'redireccionador de Python validado'))) {
        $output | Write-Output
        throw ('K-AC Server: resultado inesperado en ' + $case.Name + ' (exit ' + $actual + ').')
    }
    Write-Output ('[K-AC Server CI] OK: ' + $case.Name)
}
Write-Output ('[K-AC Server CI] {0}/{0} casos sin consultas reales al host.' -f $cases.Count)
exit 0
