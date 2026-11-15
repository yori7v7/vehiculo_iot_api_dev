# Adaptador local de K-V V1. Dot-source solamente desde controlador/recuperador.
# Las funciones de escritura se limitan a detener/iniciar la tarea virtual conocida.

function Require-KVWindows([bool]$Condition, [string]$Code) {
    if (-not $Condition) { throw ('KV_' + $Code) }
}

function Assert-KVUpgradeElevated {
    Require-KVWindows ($env:OS -eq 'Windows_NT' -and $PSVersionTable.PSVersion.Major -eq 5 -and
        $PSVersionTable.PSVersion.Minor -eq 1 -and [Environment]::Is64BitProcess -and
        $env:ProgramData -ieq 'C:\ProgramData') 'HOST'
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        $principal = [Security.Principal.WindowsPrincipal]::new($current)
        Require-KVWindows ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'ELEVATION'
    } finally { $current.Dispose() }
}

function Get-KVUpgradeArtifact([string]$Path, [bool]$Directory) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    Require-KVWindows ($item.PSIsContainer -eq $Directory -and
        -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'PATH'
    return $item
}

function Test-KVUpgradeStagingLocalServiceRead([string]$Path, [string]$Reader,
    [string]$Sid, [Security.AccessControl.FileSystemRights]$Rights) {
    # K-X: LOCAL SERVICE tiene solamente RX en code y runtime.
    # Nunca conceder a este SID acceso a estado, secretos, recovery ni Caddy.
    if ($Sid -cne 'S-1-5-19' -or
        $Reader -cnotmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$') { return $false }
    $rx = [Security.AccessControl.FileSystemRights]::ReadAndExecute -bor
        [Security.AccessControl.FileSystemRights]::Synchronize
    if ($Rights -ne $rx) { return $false }
    $canonical = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    foreach ($root in @('C:\ProgramData\VehiculoIoT-KX-Staging\code',
                        'C:\ProgramData\VehiculoIoT-KX-Staging\runtime')) {
        if ($canonical -ieq $root -or
            $canonical.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Assert-KVUpgradeAcl([string]$Path, [string]$Reader = '', [string]$Writer = '',
    [switch]$RequireProtected, [switch]$Ancestor, [switch]$AllowWriterOwner) {
    $system = 'S-1-5-18'
    $admins = 'S-1-5-32-544'
    $owners = @($system, $admins)
    if ($Ancestor) { $owners += 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464' }
    if ($AllowWriterOwner -and $Writer) { $owners += $Writer }
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $descriptor = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
    Require-KVWindows ($null -ne $descriptor.DiscretionaryAcl -and
        $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -in $owners -and
        (-not $RequireProtected -or $acl.AreAccessRulesProtected)) 'ACL'
    $write = [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership -bor 0x10000000
    if (-not $Ancestor) {
        $write = $write -bor [Security.AccessControl.FileSystemRights]::Write -bor 0x40000000
    }
    $writerRights = [Security.AccessControl.FileSystemRights]::Modify -bor
        [Security.AccessControl.FileSystemRights]::Synchronize
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -ne 'Allow') { continue }
        $sid = $rule.IdentityReference.Value
        if ($sid -in @($system, $admins)) { continue }
        if ($Ancestor -and ($sid -in $owners -or
                ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -or
                -not ($rule.FileSystemRights -band $write))) { continue }
        if ($Reader -and $sid -eq $Reader -and -not ($rule.FileSystemRights -band $write)) { continue }
        if (Test-KVUpgradeStagingLocalServiceRead $Path $Reader $sid $rule.FileSystemRights) { continue }
        if ($Writer -and $sid -eq $Writer -and -not ($rule.FileSystemRights -band (-bnot $writerRights))) { continue }
        throw 'KV_ACL'
    }
}

function Assert-KVUpgradePrivatePath([string]$Path, [switch]$Directory, [switch]$RequireProtected) {
    $null = Get-KVUpgradeArtifact $Path ([bool]$Directory)
    Assert-KVUpgradeAcl $Path -RequireProtected:$RequireProtected
}

function Get-KVUpgradeHash([string]$Path) {
    $null = Get-KVUpgradeArtifact $Path $false
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash
}

function Read-KVUpgradeJson([string]$Path, [int]$SizeLimit = 16384) {
    $item = Get-KVUpgradeArtifact $Path $false
    Require-KVWindows ($item.Length -gt 0 -and $item.Length -le $SizeLimit) 'JSON_SIZE'
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
}

function Get-KVUpgradeContext {
    Assert-KVUpgradeElevated
    $stage = 'C:\ProgramData\VehiculoIoT-KX-Staging'
    $stateRoot = 'C:\ProgramData\VehiculoIoT-KX-State'
    $candidate = 'C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE'
    $v4 = 'C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v4_RELEASE_READY'
    $ctx = [pscustomobject]@{
        TaskName = 'VehiculoIoT-Admission-Virtual'
        UserName = 'VehIoT_KXSvc'
        Candidate = $candidate
        BackupRoot = Join-Path $candidate 'recovery'
        Stage = $stage
        Live = Join-Path $stage 'code\app\public_control'
        Runtime = Join-Path $stage 'runtime'
        Python = Join-Path $stage 'runtime\venv\Scripts\python.exe'
        BasePython = Join-Path $stage 'runtime\python-base\python.exe'
        State = Join-Path $stateRoot 'service'
        Data = Join-Path $stateRoot 'service\data'
        Database = Join-Path $stateRoot 'service\data\admission.sqlite'
        Launcher = Join-Path $stateRoot 'service\launcher.py'
        Config = Join-Path $stateRoot 'service\config.json'
        Manifest = Join-Path $stateRoot 'service\install.json'
        DedicatedSid = ''
        Caddy = 'C:\ProgramData\VehiculoIoT\Caddyfile'
        CaddyLauncher = 'C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
        V4 = $v4
        V4Hashes = $null
        Legacy = $null
        CapturedKv = @()
        Files = @(
            [pscustomobject]@{Name='kv_virtual_staging.py'; Blob='dc42f5992b6a14bc17adb27f36a032491d884d56'; Length=10838
                OriginalHash='083DA2C3D359DB5631852A56126CD1522AC1B94C733AC74801362971095B307A'
                CandidateHash='FB79C8C3D630A1C97C127551FE5934D5E6663FB94E59750200545AF10CEA9B1E'},
            [pscustomobject]@{Name='kr_ticket_ledger.py'; Blob='e8f1b143faea73851abdebfd6c874efa2b72f96e'; Length=24787
                OriginalHash='1D7B301EEB4EF818A726010F686C325D44CF4E53CBCC6F63DC280EE09D7548D6'
                CandidateHash='F88482EA4DF87682A41DA21FE2B52E1BB69CCFEB014D6741EA9967191E6DA792'}
        )
    }
    foreach ($ancestor in @('C:\', 'C:\ProgramData')) {
        $null = Get-KVUpgradeArtifact $ancestor $true
        Assert-KVUpgradeAcl $ancestor -Ancestor
    }
    Assert-KVUpgradePrivatePath $stage -Directory -RequireProtected
    Assert-KVUpgradePrivatePath $candidate -Directory -RequireProtected
    $null = Get-KVUpgradeArtifact $stateRoot $true
    Assert-KVUpgradeAcl $stateRoot -Writer 'S-1-5-19' -RequireProtected
    $rootRules = @((Get-Acl -LiteralPath $stateRoot -ErrorAction Stop).GetAccessRules(
        $true, $true, [Security.Principal.SecurityIdentifier]) |
        Where-Object { $_.IdentityReference.Value -ceq 'S-1-5-19' })
    $localServiceRights = [Security.AccessControl.FileSystemRights]::Modify -bor
        [Security.AccessControl.FileSystemRights]::Synchronize
    Require-KVWindows ($rootRules.Count -eq 1 -and -not $rootRules[0].IsInherited -and
        $rootRules[0].AccessControlType -eq 'Allow' -and $rootRules[0].FileSystemRights -eq $localServiceRights) 'STATE_ACL'
    $account = Get-LocalUser -Name $ctx.UserName -ErrorAction Stop
    $ctx.DedicatedSid = [string]$account.SID.Value
    $admins = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    $administratorMembers = @(Get-LocalGroupMember -SID $admins -ErrorAction Stop |
        Where-Object { $_.SID.Value -ceq $ctx.DedicatedSid })
    Require-KVWindows ($account.Enabled -eq $true -and $ctx.DedicatedSid -cmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$' -and
        $administratorMembers.Count -eq 0) 'SERVICE_ACCOUNT'
    $null = Get-KVUpgradeArtifact $ctx.State $true
    Assert-KVUpgradeAcl $ctx.State -Reader $ctx.DedicatedSid -RequireProtected
    foreach ($item in @($ctx.Config, $ctx.Manifest, $ctx.Launcher)) {
        $null = Get-KVUpgradeArtifact $item $false
        Assert-KVUpgradeAcl $item -Reader $ctx.DedicatedSid
    }
    $install = Read-KVUpgradeJson $ctx.Manifest
    Require-KVWindows ($install.schema_version -eq 1 -and $install.mode -ceq 'loopback_only_not_public' -and
        $install.physical_control_enabled -is [bool] -and -not $install.physical_control_enabled -and
        $install.task_has_startup_trigger -is [bool] -and -not $install.task_has_startup_trigger -and
        $install.caddy_changed -is [bool] -and -not $install.caddy_changed -and
        $install.dedicated_user -ceq $ctx.UserName -and $install.dedicated_sid -ceq $ctx.DedicatedSid -and
        $install.task_name -ceq $ctx.TaskName -and (Get-KVUpgradeHash $ctx.Launcher) -ceq $install.launcher_sha256) 'INSTALL_MANIFEST'
    $null = Get-KVUpgradeArtifact $ctx.Data $true
    Assert-KVUpgradeAcl $ctx.Data -Writer $ctx.DedicatedSid -RequireProtected
    $null = Get-KVUpgradeArtifact $ctx.Database $false
    Assert-KVUpgradeAcl $ctx.Database -Writer $ctx.DedicatedSid -AllowWriterOwner
    $code = Join-Path $stage 'code'
    foreach ($path in @($code, (Join-Path $code 'app'), $ctx.Live, $ctx.Runtime,
            (Join-Path $ctx.Runtime 'venv'), (Join-Path $ctx.Runtime 'venv\Scripts'),
            (Join-Path $ctx.Runtime 'python-base'))) {
        $null = Get-KVUpgradeArtifact $path $true
        Assert-KVUpgradeAcl $path -Reader $ctx.DedicatedSid
    }
    $venvConfig = Join-Path $ctx.Runtime 'venv\pyvenv.cfg'
    foreach ($path in @($ctx.Python, $ctx.BasePython, $venvConfig)) {
        $null = Get-KVUpgradeArtifact $path $false
        Assert-KVUpgradeAcl $path -Reader $ctx.DedicatedSid
    }
    $venvCfg = @(Get-Content -LiteralPath $venvConfig -Encoding UTF8 -ErrorAction Stop)
    $venvHomeEntries = @($venvCfg | Where-Object { $_ -match '^home\s*=' })
    $sitePackages = @($venvCfg | Where-Object { $_ -match '^include-system-site-packages\s*=' })
    Require-KVWindows ($venvHomeEntries.Count -eq 1 -and ($venvHomeEntries[0] -replace '^home\s*=\s*') -ieq
        [IO.Path]::GetDirectoryName($ctx.BasePython) -and $sitePackages.Count -eq 1 -and
        $sitePackages[0] -cmatch '^include-system-site-packages\s*=\s*false$') 'PYTHON_VENV'
    # In recovery, the current pair may contain one old and one new file.
    foreach ($file in $ctx.Files) {
        $path = Join-Path $ctx.Live $file.Name
        if (Test-Path -LiteralPath $path) {
            $null = Get-KVUpgradeArtifact $path $false
            Assert-KVUpgradeAcl $path -Reader $ctx.DedicatedSid
        }
    }
    $null = Get-KVUpgradeTask $ctx
    $null = Get-KVUpgradeArtifact (Split-Path -Parent $v4) $true
    Assert-KVUpgradeAcl (Split-Path -Parent $v4) -Ancestor
    Assert-KVUpgradePrivatePath $v4 -Directory -RequireProtected
    foreach ($name in @('package.json', 'transaction.json')) {
        Assert-KVUpgradePrivatePath (Join-Path $v4 $name)
    }
    $transaction = Read-KVUpgradeJson (Join-Path $v4 'transaction.json')
    $package = Read-KVUpgradeJson (Join-Path $v4 'package.json')
    Require-KVWindows ($transaction.phase -ceq 'COMMITTED_VERIFIED' -and $package.schema_version -eq 1 -and
        $package.mode -ceq 'prod_cutover_bundle_v4_release_ready' -and
        $package.hashes.caddy_candidate -cmatch '^[A-F0-9]{64}$' -and
        $package.hashes.launcher_candidate -cmatch '^[A-F0-9]{64}$') 'CADDY_V4'
    $ctx.V4Hashes = $package.hashes
    $ctx.Legacy = @(Get-KVUpgradeLegacySnapshot $ctx)
    return $ctx
}

function Assert-KVUpgradeCandidate($Context) {
    $commit = '6a6e4bdf42f51f5592ded4b8186cd430920d1631'
    Assert-KVUpgradePrivatePath $Context.Candidate -Directory -RequireProtected
    $manifestFile = Join-Path $Context.Candidate 'candidate.json'
    Assert-KVUpgradePrivatePath $manifestFile
    $manifest = Read-KVUpgradeJson $manifestFile
    Require-KVWindows ($manifest.schema_version -eq 1 -and $manifest.candidate_commit -ceq $commit -and
        $manifest.mode -ceq 'candidate_staged_offline_not_installed' -and
        $manifest.active_task_untouched -is [bool] -and $manifest.active_task_untouched -and
        $manifest.legacy_untouched -is [bool] -and $manifest.legacy_untouched -and
        $manifest.caddy_untouched -is [bool] -and $manifest.caddy_untouched -and
        $manifest.sqlite_untouched -is [bool] -and $manifest.sqlite_untouched -and
        $manifest.physical_control_enabled -is [bool] -and -not $manifest.physical_control_enabled -and
        @($manifest.files).Count -eq 2) 'CANDIDATE_MANIFEST'
    foreach ($file in $Context.Files) {
        $path = Join-Path $Context.Candidate $file.Name
        Assert-KVUpgradePrivatePath $path
        $entry = @($manifest.files | Where-Object { $_.name -ceq $file.Name })
        Require-KVWindows ($entry.Count -eq 1 -and $entry[0].git_blob -ceq $file.Blob -and
            $entry[0].sha256 -ceq $file.CandidateHash -and $entry[0].length -eq $file.Length -and
            (Get-KVUpgradeArtifact $path $false).Length -eq $file.Length -and
            (Get-KVUpgradeHash $path) -ceq $file.CandidateHash) 'CANDIDATE_HASH'
    }
}

function Assert-KVUpgradeRuntime($Context) {
    $probe = 'import pydantic; print(pydantic.__version__); assert callable(pydantic.model_validator)'
    $version = @(& $Context.Python '-B' '-I' '-c' $probe 2>$null)
    Require-KVWindows ($LASTEXITCODE -eq 0 -and $version.Count -eq 1 -and $version[0] -ceq '2.14.1') 'PYDANTIC_VERSION'
}

function Assert-KVUpgradeStablePair($Context, [ValidateSet('Original','Candidate')][string]$Version) {
    $cache = Join-Path $Context.Live '__pycache__'
    if (Test-Path -LiteralPath $cache) {
        $null = Get-KVUpgradeArtifact $cache $true
        $bytecode = @(Get-ChildItem -LiteralPath $cache -Force -ErrorAction Stop |
            Where-Object { $_.Name -imatch '^(kv_virtual_staging|kr_ticket_ledger)\..+\.pyc$' })
        Require-KVWindows ($bytecode.Count -eq 0) 'BYTECODE'
    }
    foreach ($file in $Context.Files) {
        $path = Join-Path $Context.Live $file.Name
        $null = Get-KVUpgradeArtifact $path $false
        Assert-KVUpgradeAcl $path -Reader $Context.DedicatedSid
        Require-KVWindows (-not (Test-Path -LiteralPath ($path + 'c'))) 'BYTECODE'
        $expected = if ($Version -eq 'Candidate') { $file.CandidateHash } else { $file.OriginalHash }
        Require-KVWindows ((Get-KVUpgradeHash $path) -ceq $expected) 'SOURCE_PAIR'
    }
}

function Test-KVUpgradeTaskPrincipal([string]$Principal, [string]$UserName, [string]$DedicatedSid) {
    # Task Scheduler may store a local principal without COMPUTERNAME\ prefix.
    # Accept only the pinned name forms and resolve the actual SID on Windows.
    if ($Principal -ceq $DedicatedSid) { return $true }
    if ($Principal -ine $UserName -and
        $Principal -ine ($env:COMPUTERNAME + '\' + $UserName)) { return $false }
    try {
        $resolved = [Security.Principal.NTAccount]::new($Principal).Translate(
            [Security.Principal.SecurityIdentifier]).Value
        return ($resolved -ceq $DedicatedSid)
    } catch {
        return $false
    }
}

function Get-KVUpgradeTask($Context) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $Context.TaskName -ErrorAction Stop
    $principal = [string]$task.Principal.UserId
    $expectedArgs = '-B -I "' + $Context.Launcher + '"'
    Require-KVWindows (@($task.Actions).Count -eq 1 -and
        $task.Actions[0].Execute -ieq $Context.Python -and
        $task.Actions[0].Arguments -ceq $expectedArgs -and
        [string]::IsNullOrWhiteSpace([string]$task.Actions[0].WorkingDirectory) -and
        (Test-KVUpgradeTaskPrincipal $principal $Context.UserName $Context.DedicatedSid) -and
        $task.Principal.LogonType -eq 'Password' -and $task.Principal.RunLevel -eq 'Limited' -and
        @($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0 -and
        $task.Settings.MultipleInstances -eq 'IgnoreNew') 'TASK_IDENTITY'
    return $task
}

function Get-KVUpgradeListeners {
    Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -in @(443, 8000, 9444) }
}

function Assert-KVUpgradeProcess($Process, [string]$Sid) {
    Require-KVWindows ($Process.ProcessId -gt 0 -and
        $Process.CreationDate -is [datetime] -and
        -not [string]::IsNullOrWhiteSpace($Process.ExecutablePath)) 'PROCESS_IDENTITY'
    $owner = Invoke-CimMethod -InputObject $Process -MethodName GetOwnerSid -ErrorAction Stop
    Require-KVWindows ($owner.ReturnValue -eq 0 -and $owner.Sid -ceq $Sid) 'PROCESS_OWNER'
}

function Get-KVUpgradeProcesses($Context) {
    $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.ExecutablePath -in @($Context.Python, $Context.BasePython) -or
        ([string]$_.CommandLine).IndexOf($Context.Launcher, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    foreach ($process in $rows) {
        $command = '\A(?i:"' + [regex]::Escape($Context.Python) + '"|' +
            [regex]::Escape($Context.Python) + ')[ \t]+-B[ \t]+-I[ \t]+(?i:"' +
            [regex]::Escape($Context.Launcher) + '"|' + [regex]::Escape($Context.Launcher) + ')[ \t]*\z'
        Require-KVWindows ($process.ExecutablePath -in @($Context.Python, $Context.BasePython) -and
            $process.CommandLine -cmatch $command) 'KV_COMMAND'
        Assert-KVUpgradeProcess $process $Context.DedicatedSid
    }
    Require-KVWindows ($rows.Count -le 2) 'KV_PROCESS_COUNT'
    return $rows
}

function Assert-KVUpgradeListenerOwner($Context) {
    $listeners = @(Get-KVUpgradeListeners | Where-Object LocalPort -eq 9444)
    Require-KVWindows ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -ceq '127.0.0.1') 'KV_LISTENER'
    $processes = @(Get-KVUpgradeProcesses $Context)
    $launcher = @($processes | Where-Object ExecutablePath -ieq $Context.Python)
    Require-KVWindows ($launcher.Count -eq 1) 'KV_PROCESS_CHAIN'
    if ($processes.Count -eq 1) {
        Require-KVWindows ($listeners[0].OwningProcess -eq $launcher[0].ProcessId) 'KV_LISTENER_OWNER'
    } else {
        $base = @($processes | Where-Object ExecutablePath -ieq $Context.BasePython)
        Require-KVWindows ($base.Count -eq 1 -and $base[0].ParentProcessId -eq $launcher[0].ProcessId -and
            $base[0].CreationDate.ToUniversalTime() -gt $launcher[0].CreationDate.ToUniversalTime() -and
            $listeners[0].OwningProcess -eq $base[0].ProcessId) 'KV_PROCESS_CHAIN'
    }
}

function Get-KVUpgradeLegacySnapshot($Context) {
    Require-KVWindows ((Get-KVUpgradeHash $Context.Caddy) -ceq $Context.V4Hashes.caddy_candidate -and
        (Get-KVUpgradeHash $Context.CaddyLauncher) -ceq $Context.V4Hashes.launcher_candidate) 'LEGACY_HASH'
    foreach ($name in @('VehiculoIoT-FastAPI', 'VehiculoIoT-Caddy')) {
        $task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
        Require-KVWindows ($task.State -eq 'Running') 'LEGACY_TASK'
        Export-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
    }
    $listeners = @(Get-KVUpgradeListeners)
    foreach ($port in @(443, 8000)) {
        $rows = @($listeners | Where-Object LocalPort -eq $port)
        $owners = @($rows | Select-Object -ExpandProperty OwningProcess -Unique)
        Require-KVWindows ($owners.Count -eq 1) 'LEGACY_LISTENER'
        if ($port -eq 8000) {
            Require-KVWindows ($rows.Count -eq 1 -and $rows[0].LocalAddress -ceq '127.0.0.1') 'LEGACY_LISTENER'
        }
        $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$owners[0]) -ErrorAction Stop
        Assert-KVUpgradeProcess $process 'S-1-5-18'
        if ($port -eq 443) {
            Require-KVWindows ($process.ExecutablePath -ieq 'C:\ProgramData\VehiculoIoT\bin\caddy.exe') 'CADDY_PROCESS'
        }
        $rows | Sort-Object LocalAddress | ForEach-Object {
            '{0}|{1}|{2}|{3}' -f $port, $_.LocalAddress, $process.ProcessId, $process.CreationDate.ToUniversalTime().Ticks
        }
    }
}

function Assert-KVUpgradeLegacy($Context) {
    $latest = @(Get-KVUpgradeLegacySnapshot $Context)
    Require-KVWindows (($latest -join [char]0) -ceq ($Context.Legacy -join [char]0)) 'LEGACY_CHANGED'
}

function Test-KVUpgradeStopped($Context) {
    if ((Get-KVUpgradeTask $Context).State -ne 'Disabled' -or
        @(Get-KVUpgradeListeners | Where-Object LocalPort -eq 9444).Count -gt 0 -or
        @(Get-KVUpgradeProcesses $Context).Count -gt 0) { return $false }
    foreach ($old in $Context.CapturedKv) {
        $lives = @(Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$old.ProcessId) -ErrorAction Stop)
        if ($lives.Count -ne 0) { return $false }
    }
    return $true
}

function Assert-KVUpgradeStopped($Context) {
    Require-KVWindows (Test-KVUpgradeStopped $Context) 'KV_STOP_NOT_VERIFIED'
}

function Stop-KVUpgradeService($Context) {
    $task = Get-KVUpgradeTask $Context
    # Disable before Stop to prevent scheduler retries between source replacements.
    if ($task.State -ne 'Disabled') {
        Disable-ScheduledTask -TaskPath '\' -TaskName $Context.TaskName -ErrorAction Stop | Out-Null
    }
    $related = @(Get-KVUpgradeProcesses $Context)
    $Context.CapturedKv = @($Context.CapturedKv) + $related
    if ($task.State -eq 'Running' -or $related.Count -gt 0) {
        Stop-ScheduledTask -TaskPath '\' -TaskName $Context.TaskName -ErrorAction Stop
    }
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-KVUpgradeStopped $Context) { return }
        Start-Sleep -Milliseconds 500
    }
    throw 'KV_STOP_NOT_VERIFIED'
}

function Invoke-KVUpgradeHttpGet($Client, [string]$Url, [int]$Status, [string]$Origin = '', [string]$Key = '',
    [string]$Contract = '', [switch]$RequireIdle) {
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, [uri]$Url)
    $response = $null
    try {
        if ($Origin) { Require-KVWindows ($request.Headers.TryAddWithoutValidation('Origin', $Origin)) 'HTTP_HEADER' }
        if ($Key) { Require-KVWindows ($request.Headers.TryAddWithoutValidation('X-API-Key', $Key)) 'HTTP_HEADER' }
        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        Require-KVWindows ([int]$response.StatusCode -eq $Status) 'HTTP_STATUS'
        if (-not $Contract) { return }
        Require-KVWindows ($response.Headers.CacheControl.NoStore -eq $true) 'HTTP_CACHE'
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        Require-KVWindows ($body.simulado -is [bool] -and $body.simulado -and $body.control_fisico -is [bool] -and
            -not $body.control_fisico -and $body.canDrive -is [bool] -and -not $body.canDrive -and
            $body.turno_activo -is [bool] -and -not $body.turno_activo -and
            $body.solicitudes -is [array]) 'HTTP_VIRTUAL'
        if ($RequireIdle) { Require-KVWindows (@($body.solicitudes).Count -eq 0) 'HTTP_QUEUE' }
        if ($Contract -ceq 'Candidate') {
            $durations = @($body.duraciones_segundos)
            Require-KVWindows ($durations.Count -eq 4 -and
                @($durations | Where-Object { $_ -isnot [int] -and $_ -isnot [long] }).Count -eq 0 -and
                ($durations -join ',') -ceq '120,300,600,1200' -and
                $body.modo_supervisado -is [bool] -and $body.modo_supervisado) 'HTTP_CAPABILITIES'
        } else {
            Require-KVWindows ($null -eq $body.PSObject.Properties['duraciones_segundos'] -and
                $null -eq $body.PSObject.Properties['modo_supervisado']) 'HTTP_ORIGINAL'
        }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose()
    }
}

function Assert-KVUpgradeHttp($Context, [ValidateSet('Original','Candidate')][string]$Version,
    [switch]$RequireIdle, [switch]$SkipAuthenticated) {
    $https = 'https://100-30-4-62.nip.io'
    $origin = 'https://yori7v7.github.io'
    $admin = '/admin/vehiculos/1/control-publico/solicitudes'
    $guest = '/publico/vehiculos/1/solicitudes/estado'
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $handler.UseCookies = $false
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(5)
    $client.MaxResponseContentBufferSize = 4194304
    $credentials = $null
    try {
        # Read-only HTTPS probes, using the same native certificate validation as V4.
        Invoke-KVUpgradeHttpGet $client ($https + '/') 200
        Invoke-KVUpgradeHttpGet $client ($https + '/openapi.json') 200
        Invoke-KVUpgradeHttpGet $client ($https + $admin) 401 $origin
        Invoke-KVUpgradeHttpGet $client ($https + $admin) 403 'https://example.invalid'
        Invoke-KVUpgradeHttpGet $client ($https + $guest) 401 $origin
        Invoke-KVUpgradeHttpGet $client ($https + $guest) 403
        Invoke-KVUpgradeHttpGet $client ('http://127.0.0.1:9444' + $guest) 403 $origin
        Invoke-KVUpgradeHttpGet $client 'http://127.0.0.1:9444/docs' 404
        if ($SkipAuthenticated) { return }
        Assert-KVUpgradeAcl $Context.Config -Reader $Context.DedicatedSid
        $credentials = Read-KVUpgradeJson $Context.Config 4096
        Require-KVWindows ($credentials.schema_version -eq 1 -and $credentials.mode -ceq 'virtual_loopback_only' -and
            $credentials.bind_host -ceq '127.0.0.1' -and $credentials.bind_port -eq 9444 -and
            $credentials.database_path -ieq $Context.Database -and
            $credentials.admin_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
            $credentials.proxy_proof -cmatch '^[A-Za-z0-9_-]{64}$' -and
            $credentials.admin_proof -cne $credentials.proxy_proof) 'KV_CONFIG'
        Invoke-KVUpgradeHttpGet $client ($https + $admin) 403 $origin 'KV_INVALID_PROOF'
        Invoke-KVUpgradeHttpGet $client ($https + $admin) 200 $origin $credentials.admin_proof $Version -RequireIdle:$RequireIdle
    } finally {
        $credentials = $null
        $client.Dispose()
        $handler.Dispose()
    }
}

function Assert-KVUpgradeRunning($Context, [ValidateSet('Original','Candidate')][string]$Version,
    [switch]$RequireIdle, [switch]$SkipAuthenticated) {
    Require-KVWindows (-not ($RequireIdle -and $SkipAuthenticated)) 'HTTP_CONTRACT'
    Assert-KVUpgradeStablePair $Context $Version
    Require-KVWindows ((Get-KVUpgradeTask $Context).State -eq 'Running') 'KV_TASK_NOT_RUNNING'
    Assert-KVUpgradeListenerOwner $Context
    Assert-KVUpgradeLegacy $Context
    Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
    Require-KVWindows ($null -eq [Net.ServicePointManager]::ServerCertificateValidationCallback) 'CUSTOM_TLS_VALIDATOR'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Assert-KVUpgradeHttp $Context $Version -RequireIdle:$RequireIdle -SkipAuthenticated:$SkipAuthenticated
    Assert-KVUpgradeListenerOwner $Context
    Assert-KVUpgradeStablePair $Context $Version
    Assert-KVUpgradeLegacy $Context
}

function Start-KVUpgradeService($Context, [ValidateSet('Original','Candidate')][string]$Version) {
    Assert-KVUpgradeStopped $Context
    Assert-KVUpgradeStablePair $Context $Version
    Assert-KVUpgradeLegacy $Context
    Enable-ScheduledTask -TaskPath '\' -TaskName $Context.TaskName -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskPath '\' -TaskName $Context.TaskName -ErrorAction Stop
    for ($i = 0; $i -lt 60; $i++) {
        if ((Get-KVUpgradeTask $Context).State -eq 'Running' -and
            @(Get-KVUpgradeListeners | Where-Object LocalPort -eq 9444).Count -gt 0) {
            Assert-KVUpgradeRunning $Context $Version
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'KV_START_NOT_VERIFIED'
}
