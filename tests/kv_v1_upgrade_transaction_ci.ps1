# Exercise the actual transaction code with files in a unique temporary folder.
# All task, network and dedicated-server checks below are fixtures.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$root = Join-Path ([IO.Path]::GetTempPath()) ('kv-v1-transaction-fixture-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
. (Join-Path $PSScriptRoot '..\scripts\kv_v1_upgrade_transaction.ps1')
$realNewFile = (Get-Command Write-KVNewFile).ScriptBlock
$script:fault = ''
$script:starts = 0
$script:kvRunning = $false
$script:stops = 0
$script:dbChecks = @()
$script:passed = 0

function Check([bool]$Passed,[string]$Label) {
    if (-not $Passed) { throw ('Fixture failed: ' + $Label) }
    $script:passed++
    Write-Host ('PASS: ' + $Label)
}
function Assert-KVUpgradePrivatePath([string]$Path,[switch]$Directory,[switch]$RequireProtected) {
    if (-not $Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $Path)) { throw 'Fixture path rejected.' }
}
function Assert-KVUpgradeCandidate($Context) {
    foreach ($source in $Context.Files) {
        if ((Get-KVFileHash (Join-Path $Context.Candidate $source.Name)) -cne $source.CandidateHash) { throw 'Candidate rejected.' }
    }
}
function Assert-KVUpgradeRunning($Context,[string]$Version,[switch]$RequireIdle) {
    if (-not $script:kvRunning) { throw 'Fixture offline.' }
    if ($RequireIdle -and $script:fault -eq 'busy') { throw 'Fixture has active turn.' }
    foreach ($entry in $Context.Files) {
        if ((Get-KVFileHash (Join-Path $Context.Live $entry.Name)) -cne $entry.($Version + 'Hash')) {
            throw 'Fixture refuses to start with incorrect or mixed content.'
        }
    }
}
function Assert-KVUpgradeStopped($Context) {
    if ($script:kvRunning) { throw 'Fixture still running.' }
}
function Stop-KVUpgradeService($Context) {
    $script:stops++
    if ($script:fault -eq 'no-stop') { throw 'Fixture process did not stop.' }
    $script:kvRunning = $false
}
function Start-KVUpgradeService($Context,[string]$Version) {
    $script:starts++
    $script:kvRunning = $true
    Assert-KVUpgradeRunning $Context $Version
    if (($Version -eq 'Candidate' -and $script:fault -eq 'start-failure') -or $script:fault -eq 'all-starts-fail') {
        throw 'Fixture unhealthy after start.'
    }
}
function Invoke-KVSQLite($Context,[string]$Action) {
    $script:dbChecks += $Action
    if ($Action -ne 'verify-migrated') { Assert-KVUpgradeStopped $Context }
    if ($Action -eq 'backup') {
        if ($script:fault -eq 'backup-failure') { throw 'Fixture SQLite backup failed.' }
        & $realNewFile (Join-Path $Context.BackupRoot 'admission.before.sqlite') ([IO.File]::ReadAllBytes($Context.Database))
    } elseif ($Action -eq 'verify-migrated' -and $script:fault -eq 'migration-failure') {
        throw 'Fixture migration not verified.'
    } elseif ($Action -eq 'verify-rollback' -and $script:fault -eq 'unsafe-rollback') {
        throw 'Fixture current DB not compatible.'
    }
}
function Write-KVNewFile([string]$Path,[byte[]]$Bytes) {
    if ($Path -like '*\kr_ticket_ledger.py.kv-v1.*' -and $script:fault -eq 'between-files') {
        $script:fault = ''
        throw 'Injected interruption before replacing module two.'
    }
    if ($Path -like '*\transaction.json.*' -and $script:fault -eq 'after-files' -and
        [Text.Encoding]::UTF8.GetString($Bytes).Contains('"CANDIDATE_PINNED"')) {
        $script:fault = ''
        throw 'Injected interruption after both replacements.'
    }
    & $realNewFile $Path $Bytes
}

function New-KVFixture([string]$Fault) {
    $script:fault = $Fault
    $script:starts = $script:stops = 0
    $script:kvRunning = $true
    $script:dbChecks = @()
    $folder = Join-Path $root ([guid]::NewGuid().ToString('N'))
    $ctx = [pscustomobject]@{
        Live=(Join-Path $folder 'live'); Candidate=(Join-Path $folder 'candidate')
        BackupRoot=(Join-Path $folder 'recovery'); Database=(Join-Path $folder 'admission.sqlite')
        Files=@()
    }
    foreach ($path in @($ctx.Live,$ctx.Candidate,$ctx.BackupRoot)) { [void][IO.Directory]::CreateDirectory($path) }
    foreach ($name in @('kv_virtual_staging.py','kr_ticket_ledger.py')) {
        $original = Join-Path $ctx.Live $name
        $candidate = Join-Path $ctx.Candidate $name
        [IO.File]::WriteAllText($original, ('old: ' + $name))
        [IO.File]::WriteAllText($candidate, ('new: ' + $name))
        $ctx.Files += [pscustomobject]@{Name=$name; OriginalHash=(Get-KVFileHash $original); CandidateHash=(Get-KVFileHash $candidate)}
    }
    [IO.File]::WriteAllText($ctx.Database, 'synthetic ledger')
    return $ctx
}
function Test-Rejected([scriptblock]$Run) {
    try { & $Run; return $false } catch { return $true }
}
function Assert-KVFixtureResult($Context,[string]$Phase,[string]$Version) {
    $state = Get-KVTransaction $Context
    if ($state.phase -cne $Phase) { throw ('Fixture unexpected phase ' + $state.phase) }
    Assert-KVTransactionPair $Context $state $Version
    Assert-KVUpgradeRunning $Context $Version
}

try {
    $ctx = New-KVFixture ''
    $lock = Enter-KVTransaction $ctx
    try {
        Check (Test-Rejected { $duplicate = Enter-KVTransaction $ctx; $duplicate.Dispose() }) 'exclusive lock rejects a concurrent operator'
        Check ((Invoke-KVUpgrade $ctx) -eq 0) 'valid pair reaches verified commit'
        Assert-KVFixtureResult $ctx 'COMMITTED_VERIFIED' 'Candidate'
        Check (($script:dbChecks -join ',') -ceq 'backup,verify-migrated') 'backup precedes candidate DB verification'
        [IO.File]::AppendAllText($ctx.Database, ' | post-upgrade activity')
        Invoke-KVRecovery $ctx
        Assert-KVFixtureResult $ctx 'ROLLED_BACK_VERIFIED' 'Original'
        Check ([IO.File]::ReadAllText($ctx.Database).EndsWith('post-upgrade activity')) 'independent rollback preserves newer SQLite data'
        $stops = $script:stops
        Invoke-KVRecovery $ctx
        Check ($script:stops -eq $stops) 'verified recovery is idempotent'
    }
    finally { $lock.Dispose() }

    foreach ($testFault in @('between-files','after-files','start-failure','migration-failure','backup-failure')) {
        $ctx = New-KVFixture $testFault
        Check ((Invoke-KVUpgrade $ctx) -eq 2) ('fault returns NO-GO: ' + $testFault)
        Assert-KVFixtureResult $ctx 'ROLLED_BACK_VERIFIED' 'Original'
        Check ([IO.File]::ReadAllText($ctx.Database) -ceq 'synthetic ledger') ('fault leaves DB intact: ' + $testFault)
    }
    $ctx = New-KVFixture 'all-starts-fail'
    Check ((Invoke-KVUpgrade $ctx) -eq 2 -and -not $script:kvRunning -and
        (Get-KVTransaction $ctx).phase -ceq 'ROLLBACK_PINNED') 'failed rollback startup leaves sidecar stopped'
    $ctx = New-KVFixture 'no-stop'
    Check ((Invoke-KVUpgrade $ctx) -eq 2 -and $script:dbChecks.Count -eq 0 -and $script:starts -eq 0) 'stop uncertainty blocks backups and replacement'
    $ctx = New-KVFixture 'busy'
    Check ((Test-Rejected { Invoke-KVUpgrade $ctx }) -and $script:stops -eq 0) 'active turn blocks cutover'
    $ctx = New-KVFixture ''
    [IO.File]::Delete((Join-Path $ctx.Candidate $ctx.Files[1].Name))
    Check ((Test-Rejected { Invoke-KVUpgrade $ctx }) -and $script:stops -eq 0) 'missing candidate cannot stop service'
    $ctx = New-KVFixture ''
    Check ((Invoke-KVUpgrade $ctx) -eq 0) 'independent recovery test has committed candidate'
    $script:fault = 'unsafe-rollback'
    Check ((Test-Rejected { Invoke-KVRecovery $ctx }) -and -not $script:kvRunning) 'incompatible current DB keeps recovery stopped'
    $ctx = New-KVFixture ''
    [void](Invoke-KVUpgrade $ctx)
    Stop-KVUpgradeService $ctx
    [IO.File]::Delete((Join-Path $ctx.Live $ctx.Files[0].Name))
    Invoke-KVRecovery $ctx
    Assert-KVFixtureResult $ctx 'ROLLED_BACK_VERIFIED' 'Original'
    Check $script:kvRunning 'independent recovery restores a missing module with its original ACL'
    $ctx = New-KVFixture ''
    [void](Invoke-KVUpgrade $ctx)
    [IO.File]::WriteAllText((Join-Path $ctx.BackupRoot $ctx.Files[0].Name), 'invalid backup')
    Check (Test-Rejected { Invoke-KVRecovery $ctx }) 'tampered original copy cannot be restored'
    Write-Host ('GO: K-V V1 transaction {0}/{0} checks passed in isolated PowerShell 5.1 fixture.' -f $script:passed)
}
finally {
    $resolved = [IO.Path]::GetFullPath($root)
    $expected = Join-Path ([IO.Path]::GetTempPath()) 'kv-v1-transaction-fixture-'
    if ($resolved.StartsWith($expected, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
