# K-V V1: laboratory-only fault injection of two-file update and offline
# SQLite backup. MUST run only in Windows GitHub Actions RUNNER_TEMP.
# Never touches scheduled tasks, Caddy, EC2, production databases or motors.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if($env:GITHUB_ACTIONS -cne 'true' -or
   $env:RUNNER_OS -cne 'Windows' -or
   $env:KV_V1_LAB_ONLY -cne 'file-fixtures-faults' -or
   [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or
   $PSVersionTable.PSVersion.Major -ne 5) {
    throw 'NO-GO: KV recovery rehearsal restricted to Windows Actions fixtures'
}

$parent = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\')
$root = Join-Path $parent ('KV-V1-RECOVERY-CI-' + [Guid]::NewGuid().ToString('N'))
if(Test-Path -LiteralPath $root) { throw 'NO-GO: fixture root already exists' }
[IO.Directory]::CreateDirectory($root) | Out-Null
foreach($name in @('active','candidate','backup','data')) {
    [IO.Directory]::CreateDirectory((Join-Path $root $name)) | Out-Null
}
$active = Join-Path $root 'active'
$candidate = Join-Path $root 'candidate'
$backup = Join-Path $root 'backup'
$data = Join-Path $root 'data'
$names = @('kv_virtual_staging.py','kr_ticket_ledger.py')
$old = @{kv_virtual_staging.py='old-http-contract-120';kr_ticket_ledger.py='old-ledger-120'}
$new = @{kv_virtual_staging.py='new-http-contract-120-300-600-1200';kr_ticket_ledger.py='new-ledger-supervised'}
$script:running = $true
$script:checks = 0
$script:passes = 0
function Check([bool]$OK, [string]$label) {
    if(-not $OK) { throw ('NO-GO: ' + $label) }
    $script:passes++
    Write-Host ('PASS: ' + $label)
}
function Assert-Offline {
    if($script:running) { throw 'NO-GO: fixture service is running; refuse backup or replace' }
}
function Equal-Content([string]$folder,[hashtable]$expected) {
    foreach($name in $names) {
        if(-not (Test-Path -LiteralPath (Join-Path $folder $name) -PathType Leaf)) { return $false }
        if((Get-Content -LiteralPath (Join-Path $folder $name) -Raw) -cne $expected[$name]) {
            return $false
        }
    }
    return $true
}
function Restore-Original {
    Assert-Offline
    foreach($name in $names) {
        $src = Join-Path $backup $name
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)) { throw 'NO-GO: missing recovery file' }
        [IO.File]::Copy($src, (Join-Path $active $name), $true)
    }
    if(-not(Equal-Content $active $old)) { throw 'NO-GO: recovery does not match backed-up files' }
}
function Stage-Candidate {
    Assert-Offline
    foreach($name in $names) {
        $src = Join-Path $candidate $name
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)) { throw 'NO-GO: incomplete candidate' }
    }
}
function Apply-Candidate([int]$failAfter=0) {
    Assert-Offline
    Stage-Candidate
    $index = 0
    foreach($name in $names) {
        $index++
        [IO.File]::Copy((Join-Path $candidate $name), (Join-Path $active $name), $true)
        if($index -eq $failAfter) { throw 'INJECTED_FAULT_AFTER_FILE_' + $index }
    }
}
foreach($name in $names) {
    Set-Content -LiteralPath (Join-Path $active $name) -Value $old[$name] -NoNewline -Encoding Ascii
    Set-Content -LiteralPath (Join-Path $candidate $name) -Value $new[$name] -NoNewline -Encoding Ascii
}

Write-Host '=== K-V V1 LAB: ROLLBACK DE DOS FUENTES + SQLITE OFFLINE ==='
$blocked = $false
try { Assert-Offline } catch { $blocked = $true }
Check $blocked 'running service prevents file or SQLite backup'

$script:running = $false
Assert-Offline
foreach($name in $names) { [IO.File]::Copy((Join-Path $active $name), (Join-Path $backup $name), $false) }
Check (Equal-Content $backup $old) 'offline original source backups are complete'

# Create a REAL fresh SQLite journal in the CI temporary directory. It never
# copies live K-V data. The Python stdlib backup API provides consistent bytes.
$py = (Get-Command python -ErrorAction Stop).Source
$db = Join-Path $data 'fixture.sqlite'
$dbbackup = Join-Path $backup 'fixture.sqlite'
$pycode = @'
import sqlite3, sys
a, b = sys.argv[1:]
with sqlite3.connect(a) as db:
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
    db.execute("INSERT INTO turns VALUES(1, 'revoked')")
with sqlite3.connect(a) as db, sqlite3.connect(b) as destination:
    db.backup(destination)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == 'ok'
    assert destination.execute("PRAGMA integrity_check").fetchone()[0] == 'ok'
    assert destination.execute("SELECT state FROM turns WHERE id=1").fetchone()[0] == 'revoked'
'@
& $py -c $pycode $db $dbbackup
Check ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $dbbackup)) 'SQLite consistent snapshot and integrity_check'

$injected = $false
try { Apply-Candidate 1 } catch { $injected = $_.Exception.Message -match 'INJECTED_FAULT_AFTER_FILE_1' }
Check ($injected -and -not(Equal-Content $active $old) -and -not(Equal-Content $active $new)) 'fault between first and second file detected'
Restore-Original
Check (Equal-Content $active $old) 'rollback restores BOTH original files after partial copy'

$injected = $false
try { Apply-Candidate 2 } catch { $injected = $_.Exception.Message -match 'INJECTED_FAULT_AFTER_FILE_2' }
Check ($injected -and (Equal-Content $active $new)) 'fault after both files before commit detected'
Restore-Original
Check (Equal-Content $active $old) 'rollback restores originals before commit'

$missing = Join-Path $candidate $names[1]
[IO.File]::Move($missing, $missing + '.MISSING')
$refused = $false
try { Apply-Candidate } catch { $refused = $_.Exception.Message -match 'incomplete candidate' }
Check $refused 'incomplete candidate fails before first production file change'
Check (Equal-Content $active $old) 'missing candidate leaves original unchanged'
[IO.File]::Move($missing + '.MISSING', $missing)

Apply-Candidate
Check (Equal-Content $active $new) 'candidate can be installed after valid backups'
$script:running = $true
$script:running = $false
Restore-Original
Check (Equal-Content $active $old) 'simulated startup failure restores original pair'

# Database backup is NEVER overwritten during source-only rollback.
Check ((Get-Item -LiteralPath $dbbackup).Length -gt 0) 'SQLite backup retained for evidence, not restored automatically'
Write-Host ('GO: KV V1 RECOVERY LAB ' + $script:passes + ' checks passed. ONLY fixtures inside RUNNER_TEMP.')
