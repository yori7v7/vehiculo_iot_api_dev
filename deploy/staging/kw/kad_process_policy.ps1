# K-AD: politica pura de identidad y propiedad TCP para Windows PowerShell 5.1.
# El preflight obtiene los datos del host; estas funciones solo los cotejan.
function Test-KADEqualPath {
    param([string]$Actual, [string]$Expected)
    return [string]::Equals($Actual, $Expected, [StringComparison]::OrdinalIgnoreCase)
}

function Test-KADAbsoluteWindowsPath {
    param([string]$Path)
    # Solo rutas DOS absolutas y canonicas, sin UNC, ADS ni componentes ambiguos.
    if ($Path -notmatch '^[A-Za-z]:\\[^\\]+(?:\\[^\\]+)*$' -or
        $Path.Substring(2) -match '[<>:"/|?*\x00-\x1f]' -or
        @($Path.Substring(3) -split '\\' | Where-Object {
            $_ -match '[. ]$' -or $_ -match '^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)'
        }).Count -gt 0) {
        return $false
    }
    return [string]::Equals($Path, [IO.Path]::GetFullPath($Path), [StringComparison]::OrdinalIgnoreCase)
}

function Get-KADVenvMetadata {
    param([string[]]$VenvConfigLines, [string]$ExpectedImagePath)
    try {
        if ($VenvConfigLines.Count -lt 3 -or $VenvConfigLines.Count -gt 16 -or
            -not (Test-KADAbsoluteWindowsPath $ExpectedImagePath) -or
            $ExpectedImagePath -notmatch '\\Scripts\\python\.exe$') {
            return $null
        }

        $metadata = @{}
        foreach ($line in $VenvConfigLines) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            if ($line.Length -gt 2048 -or $line -cnotmatch '\A(home|include-system-site-packages|version|executable|command|prompt)[ \t]*=[ \t]*(\S.*)\z') {
                return $null
            }
            $key = $Matches[1]
            $value = $Matches[2]
            if ($metadata.ContainsKey($key) -or $value -match '[\x00-\x1f\x7f]') { return $null }
            $metadata[$key] = $value
        }
        if ($metadata['include-system-site-packages'] -cne 'false' -or
            $metadata['version'] -cnotmatch '^3\.(?:[89]|[1-9][0-9])\.(?:0|[1-9][0-9]?)$' -or
            -not (Test-KADAbsoluteWindowsPath $metadata['home'])) {
            return $null
        }
        $base = $metadata['home'] + '\python.exe'
        if ((Test-KADEqualPath $base $ExpectedImagePath) -or
            ($metadata.ContainsKey('executable') -and -not (Test-KADEqualPath $metadata['executable'] $base))) {
            return $null
        }
        if ($metadata.ContainsKey('command')) {
            $root = [IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($ExpectedImagePath))
            # CPython escribe el comando informativo con las rutas literales, aun con espacios.
            $pattern = '\A' + [regex]::Escape($base) + ' -m venv' +
                '(?: --(?:copies|without-pip|clear|upgrade|upgrade-deps|without-scm-ignore-files|prompt="[^"]*"))*' +
                ' ' + [regex]::Escape($root) + '\z'
            if (-not [regex]::IsMatch($metadata['command'], $pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase)) { return $null }
        }
        if ($metadata.ContainsKey('prompt') -and $metadata['prompt'] -cnotmatch '^(''.*''|".*")$') { return $null }
        return [pscustomobject]@{BaseImagePath = $base; Version = $metadata['version']}
    }
    catch { return $null }
}

function Get-KADMatchingProcessTicks {
    param($Record, $Process, [string]$ExpectedImagePath)
    if ($null -eq $Record -or $null -eq $Process -or [string]::IsNullOrWhiteSpace($ExpectedImagePath)) { return 0L }
    $recordPid = 0
    $actualPid = 0
    if (-not [int]::TryParse([string]$Record.process_id, [ref]$recordPid) -or
        -not [int]::TryParse([string]$Process.ProcessId, [ref]$actualPid) -or
        $recordPid -le 0 -or $recordPid -ne $actualPid -or
        -not (Test-KADEqualPath $Record.executable_path $ExpectedImagePath) -or
        -not (Test-KADEqualPath $Process.ExecutablePath $ExpectedImagePath) -or
        $Process.CreationDate -isnot [datetime] -or $Process.CreationDate.Kind -eq [DateTimeKind]::Unspecified) {
        return 0L
    }
    $ticks = $Process.CreationDate.ToUniversalTime().Ticks
    if ([string]$ticks -cne [string]$Record.creation_ticks) { return 0L }
    return $ticks
}

function Test-KADWindowsCommand {
    param([string]$CommandLine, [string]$ExpectedImagePath, [string]$ExpectedArguments, [switch]$AllowPathCase)
    if ([string]::IsNullOrWhiteSpace($ExpectedArguments) -or [string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    # PowerShell 5.1 Start-Process may append a space to the native command line.
    $CommandLine = $CommandLine.TrimEnd([char[]]" `t")
    if ($CommandLine -cmatch '\A"(?<image>[^"]+)"[ \t]+(?<args>.+)\z' -or
        $CommandLine -cmatch '\A(?<image>[^" \t]+)[ \t]+(?<args>.+)\z') {
        $argumentComparison = if ($AllowPathCase) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
        return (Test-KADEqualPath $Matches.image $ExpectedImagePath) -and
            [string]::Equals($Matches.args, $ExpectedArguments, $argumentComparison)
    }
    return $false
}

function Test-KADProcessOwnership {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()][object[]]$Listeners = @(),
        [AllowNull()][object]$Record,
        [AllowNull()][object]$Process,
        [AllowNull()][string]$ExpectedImagePath,
        [switch]$AllowPythonVenvRedirector,
        [AllowNull()][object]$ListenerProcess,
        [AllowNull()][string[]]$VenvConfigLines,
        [AllowNull()][object]$SupervisorRecord,
        [AllowNull()][object]$SupervisorProcess,
        [AllowNull()][string]$ExpectedSupervisorImagePath,
        [AllowNull()][string]$ExpectedSupervisorArguments
    )
    $result = [ordered]@{
        HasListeners       = $false
        IdentityMatches    = $false
        AllListenersOwned  = $false
        UsesVenvRedirector = $false
        IsSafe             = $false
    }
    try {
        $result.HasListeners = @($Listeners).Count -gt 0
        $created = Get-KADMatchingProcessTicks $Record $Process $ExpectedImagePath
        if ($created -le 0 -or -not $result.HasListeners) { return [pscustomobject]$result }

        $recordPid = [int]$Record.process_id
        $ownerPid = $recordPid
        if ($AllowPythonVenvRedirector) {
            $apiArguments = '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --log-level warning'
            $supervisorTicks = Get-KADMatchingProcessTicks $SupervisorRecord $SupervisorProcess $ExpectedSupervisorImagePath
            $launcherParentId = 0
            if (@($Listeners).Count -ne 1 -or $Listeners[0].LocalAddress -cne '127.0.0.1' -or
                [string]$Listeners[0].LocalPort -cne '8000' -or $supervisorTicks -le 0 -or $supervisorTicks -ge $created -or
                -not [int]::TryParse([string]$Process.ParentProcessId, [ref]$launcherParentId) -or
                $launcherParentId -ne [int]$SupervisorRecord.process_id -or $launcherParentId -eq $recordPid -or
                -not (Test-KADWindowsCommand $SupervisorProcess.CommandLine $ExpectedSupervisorImagePath $ExpectedSupervisorArguments -AllowPathCase) -or
                -not (Test-KADWindowsCommand $Process.CommandLine $ExpectedImagePath $apiArguments)) {
                return [pscustomobject]$result
            }
            $result.IdentityMatches = $true

            if ([string]$Listeners[0].OwningProcess -cne [string]$recordPid) {
                $metadata = Get-KADVenvMetadata $VenvConfigLines $ExpectedImagePath
                $basePid = 0
                $baseParentId = 0
                if ($null -eq $ListenerProcess -or $null -eq $metadata -or
                    -not [int]::TryParse([string]$ListenerProcess.ProcessId, [ref]$basePid) -or
                    $basePid -le 0 -or $basePid -in @($recordPid, $launcherParentId) -or
                    -not [int]::TryParse([string]$ListenerProcess.ParentProcessId, [ref]$baseParentId) -or
                    $baseParentId -ne $recordPid -or
                    $ListenerProcess.CreationDate -isnot [datetime] -or
                    $ListenerProcess.CreationDate.Kind -eq [DateTimeKind]::Unspecified -or
                    $ListenerProcess.CreationDate.ToUniversalTime().Ticks -le $created -or
                    -not (Test-KADEqualPath $ListenerProcess.ExecutablePath $metadata.BaseImagePath) -or
                    -not (Test-KADWindowsCommand $ListenerProcess.CommandLine $ExpectedImagePath $apiArguments)) {
                    return [pscustomobject]$result
                }
                $ownerPid = $basePid
            }
        }
        else { $result.IdentityMatches = $true }

        foreach ($listener in $Listeners) {
            $reportedPid = 0
            if ($null -eq $listener -or
                -not [int]::TryParse([string]$listener.OwningProcess, [ref]$reportedPid) -or
                $reportedPid -ne $ownerPid) {
                return [pscustomobject]$result
            }
        }
        $result.AllListenersOwned = $true
        $result.UsesVenvRedirector = $ownerPid -ne $recordPid
        $result.IsSafe = $true
    }
    catch {
        # Propiedades ausentes o metadatos no verificables: NO-GO.
    }
    return [pscustomobject]$result
}
