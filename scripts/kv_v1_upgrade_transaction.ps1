# Shared only by the K-V upgrade and independent recovery entry points.
Set-StrictMode -Version Latest

function Assert-KVTransaction([bool]$Condition, [string]$Reason) {
    if (-not $Condition) { throw ('KV_TRANSACTION: ' + $Reason) }
}

function Format-KVFailure($Record) {
    $message = $Record.Exception.Message
    if ($message -cmatch '\AKV_[A-Z_]{1,32}\z' -or
        $message -cmatch '\AKV_TRANSACTION: [A-Za-z .-]{1,120}\z') { return $message }
    return 'KV_EVIDENCE_UNVERIFIED'
}

function Write-KVNewFile([string]$Path, [byte[]]$Bytes) {
    $file = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $file.Write($Bytes,0,$Bytes.Length)
        $file.Flush($true)
    }
    finally { $file.Dispose() }
}

function Move-KVVerifiedFile([string]$Source, [string]$Destination, [switch]$Replace) {
    $parent = [IO.Path]::GetDirectoryName($Source)
    Assert-KVTransaction ($parent -ieq [IO.Path]::GetDirectoryName($Destination) -and
        ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($Source))).DriveFormat -ceq 'NTFS') 'La publicacion requiere el mismo directorio NTFS.'
    if (-not ('KVUpgradeNativeRename' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class KVUpgradeNativeRename
{
    [DllImport("kernel32.dll", EntryPoint = "MoveFileExW", ExactSpelling = true,
        CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool Move(string source, string destination, uint flags);
}
'@ -ErrorAction Stop
    }
    # Same-directory rename carries the prepared security descriptor without
    # the ACL merge performed by File.Replace. No copy or deferred rename.
    $flags = if ($Replace) { 0x09 } else { 0x08 }
    Assert-KVTransaction ([KVUpgradeNativeRename]::Move($Source,$Destination,$flags)) 'Windows rechazo la publicacion del archivo preparado.'
}

function Enter-KVTransaction($Context, [switch]$Create) {
    if ($Create -and -not (Test-Path -LiteralPath $Context.BackupRoot)) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $administrators = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
        $acl.SetOwner($administrators)
        foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
            $identity = [Security.Principal.SecurityIdentifier]::new($sid)
            $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
                $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
        }
        [void][IO.Directory]::CreateDirectory($Context.BackupRoot, $acl)
    }
    Assert-KVUpgradePrivatePath $Context.BackupRoot -Directory -RequireProtected
    $path = Join-Path $Context.BackupRoot 'transaction.lock'
    if (Test-Path -LiteralPath $path) { Assert-KVUpgradePrivatePath $path }
    return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}

function Get-KVTransaction($Context) {
    $path = Join-Path $Context.BackupRoot 'transaction.json'
    Assert-KVUpgradePrivatePath $path
    $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-KVTransaction ($state.schema_version -eq 1 -and $state.release -ceq 'kv-v1' -and
        $state.phase -cin @('PREPARED','OFFLINE_BACKED_UP','CANDIDATE_PINNED','START_AUTHORIZED',
            'COMMITTED_VERIFIED','ROLLBACK_PINNED','ROLLED_BACK_VERIFIED') -and
        @($state.original_acl.PSObject.Properties).Count -eq $Context.Files.Count) 'Estado de recuperacion invalido.'
    return $state
}

function Set-KVTransactionPhase($Context, $State, [string]$Phase) {
    $path = Join-Path $Context.BackupRoot 'transaction.json'
    $next = $path + '.' + [guid]::NewGuid().ToString('N')
    $copy = [ordered]@{schema_version=1; release='kv-v1'; phase=$Phase; original_acl=$State.original_acl}
    Write-KVNewFile $next ([Text.Encoding]::UTF8.GetBytes(($copy | ConvertTo-Json -Depth 4 -Compress)))
    try {
        Assert-KVUpgradePrivatePath $next
        if (Test-Path -LiteralPath $path) {
            Assert-KVUpgradePrivatePath $path
            Move-KVVerifiedFile $next $path -Replace
        } else {
            Move-KVVerifiedFile $next $path
        }
        $State.phase = $Phase
        Write-Host ('K-V V1: ' + $Phase)
    }
    finally { if ([IO.File]::Exists($next)) { [IO.File]::Delete($next) } }
}

function Get-KVFileHash([string]$Path) {
    $file = Get-Item -LiteralPath $Path -Force
    Assert-KVTransaction (-not $file.PSIsContainer -and ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -and
        $file.Length -gt 0 -and $file.Length -lt 100000) 'Fuente ausente, redirigida o de tamano inesperado.'
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-KVCodeAclSections {
    return [Security.AccessControl.AccessControlSections]::Owner -bor
        [Security.AccessControl.AccessControlSections]::Group -bor
        [Security.AccessControl.AccessControlSections]::Access
}

function Get-KVCodeAcl([string]$Path) {
    return (Get-Acl -LiteralPath $Path).GetSecurityDescriptorSddlForm((Get-KVCodeAclSections))
}

function Assert-KVOriginalCopies($Context, $State) {
    foreach ($file in $Context.Files) {
        $copy = Join-Path $Context.BackupRoot $file.Name
        Assert-KVUpgradePrivatePath $copy
        Assert-KVTransaction ((Get-KVFileHash $copy) -ceq $file.OriginalHash -and
            -not [string]::IsNullOrWhiteSpace($State.original_acl.($file.Name))) 'Respaldo original sin integridad.'
    }
}

function Assert-KVTransactionPair($Context, $State, [ValidateSet('Original','Candidate')][string]$Version) {
    foreach ($file in $Context.Files) {
        $target = Join-Path $Context.Live $file.Name
        $expectedHash = if ($Version -eq 'Original') { $file.OriginalHash } else { $file.CandidateHash }
        Assert-KVTransaction ((Get-KVFileHash $target) -ceq $expectedHash -and
            (Get-KVCodeAcl $target) -ceq $State.original_acl.($file.Name)) 'La pareja activa o su ACL difiere de la verificada.'
    }
}

function Set-KVTransactionPair($Context, $State, [ValidateSet('Original','Candidate')][string]$Version) {
    $sourceDirectory = if ($Version -eq 'Original') { $Context.BackupRoot } else { $Context.Candidate }
    # Validate the entire pair before the first change, including rollback sources.
    foreach ($file in $Context.Files) {
        $target = Join-Path $Context.Live $file.Name
        $source = Join-Path $sourceDirectory $file.Name
        Assert-KVUpgradePrivatePath $source
        $sourceHash = if ($Version -eq 'Original') { $file.OriginalHash } else { $file.CandidateHash }
        Assert-KVTransaction ((Get-KVFileHash $source) -ceq $sourceHash) 'Fuente sin evidencia verificable.'
        if (Test-Path -LiteralPath $target) {
            Assert-KVTransaction ((Get-KVFileHash $target) -cin @($file.OriginalHash,$file.CandidateHash) -and
                (Get-KVCodeAcl $target) -ceq $State.original_acl.($file.Name)) 'Instalacion o ACL sin evidencia verificable.'
        } else {
            Assert-KVTransaction ($Version -eq 'Original') 'Falta una fuente original antes de instalar.'
        }
    }
    foreach ($file in $Context.Files) {
        Assert-KVUpgradeStopped $Context
        $target = Join-Path $Context.Live $file.Name
        $hash = if ($Version -eq 'Original') { $file.OriginalHash } else { $file.CandidateHash }
        $targetExists = Test-Path -LiteralPath $target
        $before = if ($targetExists) { Get-KVFileHash $target } else { $null }
        if ($before -ceq $hash) { continue }
        $next = $target + '.kv-v1.' + [guid]::NewGuid().ToString('N')
        Write-KVNewFile $next ([IO.File]::ReadAllBytes((Join-Path $sourceDirectory $file.Name)))
        try {
            Assert-KVTransaction ((Get-KVFileHash $next) -ceq $hash) 'Contenido temporal no verificado.'
            $expectedAcl = $State.original_acl.($file.Name)
            if ((Get-KVCodeAcl $next) -cne $expectedAcl) {
                # Prepare the temporary file with the existing owner/group/DACL.
                # Refuse to replace the live source if that cannot be proven.
                $acl = [Security.AccessControl.FileSecurity]::new()
                $acl.SetSecurityDescriptorSddlForm($expectedAcl, (Get-KVCodeAclSections))
                [IO.FileInfo]::new($next).SetAccessControl($acl)
                Assert-KVTransaction ((Get-KVCodeAcl $next) -ceq $expectedAcl) 'ACL temporal incompatible.'
            }
            Assert-KVUpgradeStopped $Context
            if ($targetExists) {
                Assert-KVTransaction ($before -cin @($file.OriginalHash,$file.CandidateHash) -and
                    (Get-KVFileHash $target) -ceq $before -and (Get-KVCodeAcl $target) -ceq $expectedAcl) 'El destino cambio durante la preparacion.'
                Move-KVVerifiedFile $next $target -Replace
            } else {
                Assert-KVTransaction ($Version -eq 'Original') 'No se recrea un destino ausente al instalar.'
                Move-KVVerifiedFile $next $target
            }
            Assert-KVTransaction ((Get-KVCodeAcl $target) -ceq $expectedAcl) 'La ACL original cambio.'
        }
        finally { if ([IO.File]::Exists($next)) { [IO.File]::Delete($next) } }
    }
    Assert-KVTransactionPair $Context $State $Version
}

function Invoke-KVSQLite($Context, [string]$Action) {
    $dbBackup = Join-Path $Context.BackupRoot 'admission.before.sqlite'
    $arguments = @($Action,$Context.Database)
    if ($Action -in @('backup','verify-migrated')) { $arguments += $dbBackup }
    if ($Action -eq 'verify-migrated') { Assert-KVUpgradePrivatePath $dbBackup }
    if ($Action -ne 'verify-migrated') {
        Assert-KVUpgradeStopped $Context
        $probe = [IO.File]::Open($Context.Database, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        $probe.Dispose()
    }
    & $Context.Python -B -I -S (Join-Path $PSScriptRoot 'kv_v1_upgrade_sqlite.py') @arguments 2>&1 | Out-Null
    Assert-KVTransaction ($LASTEXITCODE -eq 0) ('SQLite no verificable en ' + $Action + '.')
    if ($Action -eq 'backup') { Assert-KVUpgradePrivatePath $dbBackup }
}

function Invoke-KVRecovery($Context) {
    $state = Get-KVTransaction $Context
    Assert-KVOriginalCopies $Context $state
    if ($state.phase -ceq 'ROLLED_BACK_VERIFIED') {
        Assert-KVTransactionPair $Context $state 'Original'
        Assert-KVUpgradeRunning $Context 'Original'
        return
    }
    if ($state.phase -ceq 'PREPARED') {
        # No deterministic write to the live pair is permitted in PREPARED.
        Assert-KVTransactionPair $Context $state 'Original'
        $originalHealthy = $false
        try {
            Assert-KVUpgradeRunning $Context 'Original'
            $originalHealthy = $true
        }
        catch { }
        if ($originalHealthy) {
            Set-KVTransactionPhase $Context $state 'ROLLED_BACK_VERIFIED'
            return
        }
    }
    Stop-KVUpgradeService $Context
    Assert-KVUpgradeStopped $Context
    Invoke-KVSQLite $Context 'verify-rollback'
    Set-KVTransactionPair $Context $state 'Original'
    Set-KVTransactionPhase $Context $state 'ROLLBACK_PINNED'
    try {
        Start-KVUpgradeService $Context 'Original'
        Assert-KVTransactionPair $Context $state 'Original'
        Set-KVTransactionPhase $Context $state 'ROLLED_BACK_VERIFIED'
    }
    catch {
        Stop-KVUpgradeService $Context
        throw
    }
}

function Invoke-KVUpgrade($Context) {
    Assert-KVUpgradeCandidate $Context
    Assert-KVUpgradeRunning $Context 'Original' -RequireIdle
    Assert-KVTransaction (-not (Test-Path -LiteralPath (Join-Path $Context.BackupRoot 'transaction.json'))) 'Ya existe una transaccion. Conserva su evidencia.'
    $acl = [ordered]@{}
    foreach ($file in $Context.Files) {
        $source = Join-Path $Context.Live $file.Name
        Assert-KVTransaction ((Get-KVFileHash $source) -ceq $file.OriginalHash) 'El contenido original cambio.'
        $acl[$file.Name] = Get-KVCodeAcl $source
        Write-KVNewFile (Join-Path $Context.BackupRoot $file.Name) ([IO.File]::ReadAllBytes($source))
    }
    $state = [pscustomobject]@{phase=''; original_acl=[pscustomobject]$acl}
    Assert-KVOriginalCopies $Context $state
    Set-KVTransactionPhase $Context $state 'PREPARED'
    $startAttempted = $false
    try {
        Stop-KVUpgradeService $Context
        Assert-KVUpgradeStopped $Context
        Invoke-KVSQLite $Context 'backup'
        Set-KVTransactionPhase $Context $state 'OFFLINE_BACKED_UP'
        Assert-KVUpgradeCandidate $Context
        Set-KVTransactionPair $Context $state 'Candidate'
        Set-KVTransactionPhase $Context $state 'CANDIDATE_PINNED'
        Set-KVTransactionPhase $Context $state 'START_AUTHORIZED'
        $startAttempted = $true
        Start-KVUpgradeService $Context 'Candidate'
        Invoke-KVSQLite $Context 'verify-migrated'
        Assert-KVTransactionPair $Context $state 'Candidate'
        Assert-KVUpgradeRunning $Context 'Candidate'
        Set-KVTransactionPhase $Context $state 'COMMITTED_VERIFIED'
        return 0
    }
    catch {
        Write-Host ('NO-GO: actualizacion interrumpida en ' + $state.phase + '. ' + (Format-KVFailure $_))
        try {
            if ($startAttempted) { Stop-KVUpgradeService $Context }
            Invoke-KVRecovery $Context
            Write-Host 'NO-GO: version anterior verificada tras recuperacion; SQLite conservada.'
        }
        catch {
            Write-Host ('NO-GO: recuperacion no verificada. ' + (Format-KVFailure $_))
            Write-Host 'Ejecuta el recuperador antes de cualquier arranque manual.'
        }
        return 2
    }
}
