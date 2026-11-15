# K-X: isolated, dual-file rollback fault injection. PowerShell 5.1.
# READS originals in EC2CopyLab; WRITES ONLY NEW MIRROR PATHS.
# No public service, task, network, credential, or physical control modifications.
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('FixtureCI','EC2CopyLab')]
    [string]$Mode
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$passed = $false
$created = $false
$work = $null
$cases = @('FAIL_AFTER_FIRST','FAIL_AFTER_SECOND','PLANNED_ROLLBACK')
$results = New-Object 'System.Collections.Generic.List[object]'
$liveCaddy = 'C:\ProgramData\VehiculoIoT\Caddyfile'
$liveLauncher = 'C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1'
$launcherOriginalHash = '873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1'
function Check([bool]$ok,[string]$label) {
    if (-not $ok) { throw ('NO-GO: ' + $label) }
    Write-Host ('OK: ' + $label) -ForegroundColor Green
}
function Hash([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash }
function Normal([string]$path) {
    Check (Test-Path -LiteralPath $path -PathType Leaf) 'Archivo necesario existe'
    Check (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Archivo sin enlace'
}
function Same([string]$path,[string]$hash,[string]$label) { Check ((Hash $path) -ceq $hash) ('SHA256 ' + $label) }
function SwapMirror([string]$source,[string]$target,[string]$backup,[string]$expected,[string]$dir) {
    $prefix = [IO.Path]::GetFullPath($dir).TrimEnd('\') + '\'
    Check ([IO.Path]::GetFullPath($target).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) 'Destino exclusivo del espejo'
    Check ([IO.Path]::GetFullPath($backup).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) 'Backup exclusivo del espejo'
    Normal $source
    Normal $target
    Check (-not (Test-Path -LiteralPath $backup)) 'Respaldo temporal libre'
    $temp = Join-Path $dir ([IO.Path]::GetFileName($target) + '.incoming')
    Check (-not (Test-Path -LiteralPath $temp)) 'Temporal libre'
    [IO.File]::Copy($source,$temp,$false)
    Same $temp $expected 'archivo entrante'
    [IO.File]::Replace($temp,$target,$backup)
    Same $target $expected 'archivo reemplazado'
}
function RestoreMirror([string]$dir,[string]$oldC,[string]$oldL,[string]$hashC,[string]$hashL) {
    # Fail closed before changing either file if an original backup is invalid.
    Same $oldC $hashC 'respaldo original Caddy'
    Same $oldL $hashL 'respaldo original launcher'
    $tC = Join-Path $dir 'Caddyfile.MIRROR'
    $tL = Join-Path $dir 'run_caddy.MIRROR.ps1'
    Normal $tC
    Normal $tL
    if ((Hash $tC) -cne $hashC) {
        SwapMirror $oldC $tC (Join-Path $dir 'retired_caddy.bak') $hashC $dir
    }
    if ((Hash $tL) -cne $hashL) {
        SwapMirror $oldL $tL (Join-Path $dir 'retired_launcher.bak') $hashL $dir
    }
    Same $tC $hashC 'Caddy restaurado'
    Same $tL $hashL 'launcher restaurado'
}
function Exercise([string]$name,[string]$oldC,[string]$oldL,[string]$newC,[string]$newL,
                  [string]$hashC,[string]$hashL,[string]$hashNC,[string]$hashNL) {
    $dir = Join-Path $work $name
    Check (-not (Test-Path -LiteralPath $dir)) 'Caso nuevo sin sobrescritura'
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $tC = Join-Path $dir 'Caddyfile.MIRROR'
    $tL = Join-Path $dir 'run_caddy.MIRROR.ps1'
    [IO.File]::Copy($oldC,$tC,$false)
    [IO.File]::Copy($oldL,$tL,$false)
    Same $tC $hashC 'Caddy inicial'
    Same $tL $hashL 'launcher inicial'
    $injected = $false
    try {
        SwapMirror $newC $tC (Join-Path $dir 'patched_caddy.bak') $hashNC $dir
        if ($name -ceq 'FAIL_AFTER_FIRST') { throw 'KX_INJECTED_FIRST' }
        SwapMirror $newL $tL (Join-Path $dir 'patched_launcher.bak') $hashNL $dir
        if ($name -ceq 'FAIL_AFTER_SECOND') { throw 'KX_INJECTED_SECOND' }
        Same $tC $hashNC 'Caddy candidato'
        Same $tL $hashNL 'launcher candidato'
        RestoreMirror $dir $oldC $oldL $hashC $hashL
    }
    catch {
        $reason = $_.Exception.Message
        try { RestoreMirror $dir $oldC $oldL $hashC $hashL }
        catch { throw ('NO-GO: recuperacion fallida en ' + $name) }
        if ($name -ceq 'FAIL_AFTER_FIRST') { Check ($reason -ceq 'KX_INJECTED_FIRST') 'Fallo intencional tras primer archivo' }
        elseif ($name -ceq 'FAIL_AFTER_SECOND') { Check ($reason -ceq 'KX_INJECTED_SECOND') 'Fallo intencional tras segundo archivo' }
        else { throw 'NO-GO: excepcion no esperada' }
        $injected = $true
    }
    Same $tC $hashC ('original Caddy ' + $name)
    Same $tL $hashL ('original launcher ' + $name)
    $results.Add([ordered]@{case=$name; fault_injected=$injected; originals_restored=$true})
}
Write-Host ('=== K-X: ROLLBACK DOBLE SOLO EN ESPEJO / ' + $Mode + ' ===') -ForegroundColor Cyan
try {
    if ($Mode -ceq 'FixtureCI') {
        Check ($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_OS -ceq 'Windows') 'Fixture exclusivo de GitHub Actions Windows'
        $work = Join-Path $env:TEMP ('KX-DualRollback-CI-' + [Guid]::NewGuid().ToString('N'))
        Check (-not (Test-Path -LiteralPath $work)) 'Directorio CI nuevo'
        [IO.Directory]::CreateDirectory($work) | Out-Null
        $created = $true
        $source = Join-Path $work 'fixtures'
        [IO.Directory]::CreateDirectory($source) | Out-Null
        $oldC = Join-Path $source 'original_caddy.txt'
        $oldL = Join-Path $source 'original_launcher.txt'
        $newC = Join-Path $source 'candidate_caddy.txt'
        $newL = Join-Path $source 'candidate_launcher.txt'
        [IO.File]::WriteAllText($oldC,'ORIGINAL CADDY 127.0.0.1:8000',[Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText($oldL,'ORIGINAL LAUNCHER',[Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText($newC,'VIRTUAL CADDY 127.0.0.1:9444',[Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText($newL,'VIRTUAL LAUNCHER',[Text.UTF8Encoding]::new($false))
    }
    else {
        $admin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        Check ($admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Consola elevada'
        $root = 'C:\ProgramData\VehiculoIoT-KX-Installer'
        $manifestPath = 'C:\ProgramData\VehiculoIoT-KX-State\service\install.json'
        $release = Join-Path $root 'kx_https_public_release_v1_offline'
        $stage = Join-Path $release 'launcher_staging_v1'
        $oldC = Join-Path $root 'kx_caddy_release_preflight\Caddyfile.original.copy'
        $oldL = Join-Path $stage 'run_caddy.original.backup.ps1'
        $newC = Join-Path $release 'Caddyfile.kx.ready.NOT_ACTIVE'
        $newL = Join-Path $stage 'run_caddy.kx.pending.ps1'
        $releasePath = Join-Path $release 'preparation.json'
        $stagePath = Join-Path $stage 'launcher_stage_report.json'
        $work = Join-Path $root 'kx_dual_rollback_fault_lab_v1'
        foreach ($p in @($root,$manifestPath,$oldC,$oldL,$newC,$newL,$releasePath,$stagePath,$liveCaddy,$liveLauncher)) {
            Check (Test-Path -LiteralPath $p) 'Material K-X original presente'
            Check (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Material sin enlace'
        }
        Check ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) 'Instalador privado'
        Check (-not (Test-Path -LiteralPath $work)) 'Espejo no existente'
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $prep = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
        $staging = Get-Content -LiteralPath $stagePath -Raw | ConvertFrom-Json
        Check ($manifest.mode -ceq 'loopback_only_not_public' -and $manifest.caddy_changed -eq $false -and $manifest.physical_control_enabled -eq $false) 'K-V virtual, control OFF'
        Check ($prep.mode -ceq 'offline_public_https_candidate_never_activated' -and $prep.production_caddy_changed -eq $false) 'Candidato inactivo'
        Check ($staging.mode -ceq 'launcher_candidate_staged_offline_not_installed' -and $staging.launcher_active_file_modified -eq $false) 'Lanzador inactivo'
        Same $oldC ([string]$manifest.original_caddy_sha256) 'backup original Caddy'
        Same $oldL $launcherOriginalHash 'backup original launcher'
        Same $newC ([string]$prep.candidate_sha256) 'Caddyfile candidato'
        Same $newL ([string]$staging.launcher_candidate_sha256) 'launcher candidato'
        Same $liveCaddy ([string]$manifest.original_caddy_sha256) 'Caddy productivo intacto'
        Same $liveLauncher $launcherOriginalHash 'launcher productivo intacto'
        Check (([IO.File]::ReadAllText($newC)).Contains('{env.KX_STAGING_PROXY_PROOF}')) 'Marcador runtime sin token literal'
        [IO.Directory]::CreateDirectory($work) | Out-Null
        $created = $true
        & icacls.exe $work /inheritance:r | Out-Null
        Check ($LASTEXITCODE -eq 0) 'Herencia NTFS retirada'
        & icacls.exe $work /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        Check ($LASTEXITCODE -eq 0) 'Solo SYSTEM y Administradores'
        Check ((Get-Acl -LiteralPath $work).AreAccessRulesProtected) 'Espejo privado'
    }
    foreach ($p in @($oldC,$oldL,$newC,$newL)) { Normal $p }
    $hashC = Hash $oldC
    $hashL = Hash $oldL
    $hashNC = Hash $newC
    $hashNL = Hash $newL
    Check ($hashC -cne $hashNC -and $hashL -cne $hashNL) 'Candidatos distintos'
    foreach ($name in $cases) {
        Write-Host ('--- ' + $name + ' ---') -ForegroundColor Cyan
        Exercise $name $oldC $oldL $newC $newL $hashC $hashL $hashNC $hashNL
    }
    if ($Mode -ceq 'EC2CopyLab') {
        Same $liveCaddy $hashC 'Caddy publico intacto al terminar'
        Same $liveLauncher $hashL 'launcher publico intacto al terminar'
        $report = [ordered]@{
            mode='dual_file_rollback_mirror_only'
            timestamp_utc=[DateTime]::UtcNow.ToString('o')
            scenarios=@($results.ToArray())
            actual_service_rollback_tested=$false
            independent_watchdog_armed=$false
            production_files_modified=$false
            public_https_interrupted=$false
            kv_public_enabled=$false
            physical_control_enabled=$false
        }
        $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $work 'dual_rollback_report.json') -Encoding UTF8
    }
    $passed = $true
    Write-Host '=== RESULTADO: ROLLBACK DOBLE EN COPIA APROBADO ===' -ForegroundColor Green
    Write-Host 'Tres casos; ambos hashes restaurados; sin tocar produccion.'
    Write-Host 'IMPORTANTE: aun NO se ha ensayado el rollback del servicio real.'
}
catch {
    Write-Host '=== RESULTADO: NO-GO ROLLBACK DOBLE ===' -ForegroundColor Red
    Write-Host ('TIPO: ' + $_.Exception.GetType().Name) -ForegroundColor Yellow
    Write-Host 'Detalle privado omitido; no intentar publicacion.'
}
finally {
    if ($Mode -ceq 'FixtureCI' -and $created -and (Test-Path -LiteralPath $work)) {
        try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop }
        catch { $passed = $false; Write-Host 'NO-GO: fixture CI no retirado.' -ForegroundColor Red }
    }
    Write-Host 'SIN CAMBIOS A TAREAS, CADDY, AWS, RDS, ESP NI MOTORES'
}
if (-not $passed) { exit 1 }
