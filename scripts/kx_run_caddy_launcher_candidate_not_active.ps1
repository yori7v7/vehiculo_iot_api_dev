# K-X CADDY LAUNCHER CANDIDATE - NOT INSTALLED. Windows PowerShell 5.1.
# Exact replacement candidate for deploy/windows/run_caddy.ps1 only AFTER approved release.
# The legacy Caddy listener can still start when K-V proof is unavailable.
param([string]$StateDirectory)
. (Join-Path $PSScriptRoot 'common.ps1')

function Get-KXValidatedVirtualProxyProof {
    # This path is an existing local service secret store, NOT a public config.
    $store = 'C:\ProgramData\VehiculoIoT-KX-State\service'
    $configFile = Join-Path $store 'config.json'
    $manifestFile = Join-Path $store 'install.json'

    foreach ($path in @($store, $configFile, $manifestFile)) {
        if (-not (Test-Path -LiteralPath $path)) { throw 'K-V proof unavailable' }
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'K-V proof unavailable'
        }
    }

    $storeAcl = Get-Acl -LiteralPath $store -ErrorAction Stop
    if (-not $storeAcl.AreAccessRulesProtected) { throw 'K-V proof unavailable' }

    $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    if ($manifest.mode -cne 'loopback_only_not_public' -or
        $manifest.physical_control_enabled -ne $false -or
        $manifest.dedicated_user -cne 'VehIoT_KXSvc' -or
        $manifest.dedicated_sid -notmatch '^S-1-5-21-[0-9-]+$') {
        throw 'K-V proof unavailable'
    }

    $acl = Get-Acl -LiteralPath $configFile -ErrorAction Stop
    $accepted = @('S-1-5-18', 'S-1-5-32-544', [string]$manifest.dedicated_sid)
    foreach ($rule in $acl.GetAccessRules(
        $true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq
            [Security.AccessControl.AccessControlType]::Allow -and
            $rule.IdentityReference.Value -notin $accepted) {
            throw 'K-V proof unavailable'
        }
    }

    $configItem = Get-Item -LiteralPath $configFile -Force -ErrorAction Stop
    if ($configItem.Length -gt 4096 -or $configItem.Length -lt 128) {
        throw 'K-V proof unavailable'
    }
    $data = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    $keys = @($data.PSObject.Properties.Name | Sort-Object)
    $expected = @(@('schema_version','mode','bind_host','bind_port',
        'database_path','admin_proof','proxy_proof') | Sort-Object)
    if (($keys -join ',') -cne ($expected -join ',') -or
        $data.schema_version -ne 1 -or
        $data.mode -cne 'virtual_loopback_only' -or
        $data.bind_host -cne '127.0.0.1' -or
        $data.bind_port -ne 9444 -or
        $data.database_path -cne (Join-Path $store 'data\admission.sqlite') -or
        $data.admin_proof -cnotmatch '^[A-Za-z0-9_-]{64}$' -or
        $data.proxy_proof -cnotmatch '^[A-Za-z0-9_-]{64}$' -or
        $data.admin_proof -ceq $data.proxy_proof) {
        throw 'K-V proof unavailable'
    }
    return [string]$data.proxy_proof
}

try {
    $StateDirectory = Get-VehicleStateDirectory $StateDirectory
    $configuration = Get-VehicleConfiguration $StateDirectory
    Set-VehicleCaddyEnvironment $StateDirectory

    # Set invalid value FIRST. Any failed credential validation must deny K-V,
    # while the legacy 8000 reverse proxy can continue running.
    $env:KX_STAGING_PROXY_PROOF = 'KX_INVALID_PROOF_SERVICE_UNAVAILABLE_DO_NOT_USE'
    try {
        $env:KX_STAGING_PROXY_PROOF = Get-KXValidatedVirtualProxyProof
    }
    catch {
        # Safe: no raw exception string, credential, path or JSON in logs.
        Write-Warning '[K-X] Virtual authentication unavailable; Caddy remains legacy-compatible.'
    }

    $arguments = @('run', '--config', $configuration.caddyfile_path,
        '--adapter', 'caddyfile')
    exit (Invoke-VehicleProcess $StateDirectory 'caddy' $configuration.caddy_path $arguments)
}
catch {
    Write-VehicleFailureLog $StateDirectory 'caddy'
    Write-Error 'La tarea Caddy no pudo continuar. Revisa requisitos, rutas y logs protegidos.' -ErrorAction Continue
    exit 1
}
finally {
    # Clear only in the supervisor after its child exits.
    Remove-Item Env:KX_STAGING_PROXY_PROOF -ErrorAction SilentlyContinue
}
