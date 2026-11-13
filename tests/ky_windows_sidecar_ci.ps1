# K-Y: ensayo NATIVO Windows de arranque/parada independiente.
# No crea tareas, no usa EC2, no configura Caddy, no conecta la bateria.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$python = (Get-Command python.exe -ErrorAction Stop).Source
$private = Join-Path $env:RUNNER_TEMP ('ky-sidecar-' + [guid]::NewGuid().ToString('N'))
$sidecar = $null
$legacy = $null
$script:checks = 0

function Check([bool]$ok, [string]$name) {
    if (-not $ok) { throw ('K-Y FAIL: ' + $name) }
    $script:checks++
    Write-Output ('[K-Y] OK: ' + $name)
}
function Random-Proof {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes = New-Object byte[] 48
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes)
    }
    finally { $rng.Dispose() }
}
function Get-HttpStatus([int]$port, [string]$path, [hashtable]$headers = @{}) {
    $request = [Net.HttpWebRequest][Net.WebRequest]::Create(
        ('http://127.0.0.1:{0}{1}' -f $port, $path)
    )
    $request.Method = 'GET'
    $request.Timeout = 1500
    $request.ReadWriteTimeout = 1500
    $request.Proxy = $null
    foreach ($name in $headers.Keys) {
        if ($name -eq 'Host') { $request.Host = $headers[$name] }
        else { $request.Headers[$name] = $headers[$name] }
    }
    $response = $null
    try { $response = $request.GetResponse() }
    catch [Net.WebException] {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw }
    }
    try { return [int]$response.StatusCode }
    finally { $response.Close() }
}
function Is-Listening([int]$port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).Count -gt 0
}
try {
    New-Item -ItemType Directory -Force -Path $private | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($identity.User.Value, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique) {
        $principal = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $principal, 'FullControl', 'ContainerInherit,ObjectInherit',
            'None', 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $private -AclObject $acl
    $config = Join-Path $private 'private.json'
    $admin = Random-Proof
    $proxy = Random-Proof
    $settings = [ordered]@{
        schema_version = 1
        mode = 'virtual_ci'
        bind_host = '127.0.0.1'
        bind_port = 9444
        database_path = (Join-Path $private 'tickets.sqlite3')
        admin_proof = $admin
        proxy_proof = $proxy
    }
    $settings | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $config -Encoding UTF8
    # Validar explicitamente que el test NO funcionaria fuera del CI.
    $env:APP_ENV = 'staging'
    $env:ADMISSION_VIRTUAL_ONLY = 'enabled'
    Remove-Item Env:\KY_WINDOWS_CI_ONLY -ErrorAction SilentlyContinue
    & $python -m app.public_control.ky_windows_sidecar --config $config
    Check ($LASTEXITCODE -eq 2) 'CI-only deniega ejecucion sin bandera adicional'
    $env:KY_WINDOWS_CI_ONLY = 'isolated-sidecar'

    $invalidConfig = Join-Path $private 'invalid.json'
    $invalid = [ordered]@{}
    foreach ($name in $settings.Keys) { $invalid[$name] = $settings[$name] }
    $invalid['bind_host'] = '0.0.0.0'
    $invalid | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $invalidConfig -Encoding UTF8
    & $python -m app.public_control.ky_windows_sidecar --config $invalidConfig
    Check ($LASTEXITCODE -eq 2) 'falla cerrada ante host 0.0.0.0'
    Check (-not (Is-Listening 9444)) 'sin sidecar tras intento invalido'

    # Simular proceso CONTROL/MONITOREO legado, separado en 8000.
    $legacy = Start-Process -FilePath $python -WorkingDirectory $root -PassThru `
        -ArgumentList '-m http.server 8000 --bind 127.0.0.1' `
        -RedirectStandardOutput (Join-Path $private 'legacy.out') `
        -RedirectStandardError (Join-Path $private 'legacy.err')
    $legacyReady = $false
    for ($attempt = 0; $attempt -lt 35; $attempt++) {
        try {
            if ((Get-HttpStatus 8000 '/') -eq 200) { $legacyReady = $true; break }
        }
        catch { }
        Start-Sleep -Milliseconds 300
    }
    Check $legacyReady 'servicio legado simulado en 8000 responde'

    $sidecar = Start-Process -FilePath $python -WorkingDirectory $root -PassThru `
        -ArgumentList ('-m app.public_control.ky_windows_sidecar --config "' + $config + '"') `
        -RedirectStandardOutput (Join-Path $private 'ky.out') `
        -RedirectStandardError (Join-Path $private 'ky.err')
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if ($sidecar.HasExited) { break }
        try {
            if ((Get-HttpStatus 9444 '/') -eq 404) { $ready = $true; break }
        }
        catch { }
        Start-Sleep -Milliseconds 300
    }
    Check $ready 'sidecar real 127.0.0.1:9444 arrancado de forma independiente'
    Check ((Get-HttpStatus 9444 '/vehiculos/1/movimientos') -eq 404) 'sidecar no expone movimientos'
    Check ((Get-HttpStatus 9444 '/docs') -eq 404) 'sidecar sin Swagger'
    Check ((Get-HttpStatus 9444 '/admin/vehiculos/1/control-publico/solicitudes') -eq 403) 'cabeceras de proxy obligatorias'
    $trusted = @{
        'Host' = '100-30-4-62.nip.io'
        'Origin' = 'https://yori7v7.github.io'
        'X-Admission-Proxy-Token' = $proxy
        'X-Admission-Client-IP' = '8.8.8.8'
        'X-Admission-Scheme' = 'https'
    }
    Check ((Get-HttpStatus 9444 '/admin/vehiculos/1/control-publico/solicitudes' $trusted) -eq 401) 'admin exige su clave independiente'
    $trusted['X-API-Key'] = $admin
    Check ((Get-HttpStatus 9444 '/admin/vehiculos/1/control-publico/solicitudes' $trusted) -eq 200) 'consulta admin VIRTUAL autorizada'
    Check ((Get-HttpStatus 8000 '/') -eq 200) 'legacy no se interrumpe al arrancar sidecar'

    Stop-Process -Id $sidecar.Id -Force
    $sidecar.WaitForExit()
    Check (-not (Is-Listening 9444)) 'sidecar detenido y puerto 9444 liberado'
    Check ((Get-HttpStatus 8000 '/') -eq 200) 'legacy sigue arriba tras parar sidecar'
    Check ($legacy.HasExited -eq $false) 'PID legacy no fue detenido'
    Write-Output ('[K-Y] RESULTADO: ' + $script:checks + ' comprobaciones; 8000 preservado, 9444 reversible')
}
finally {
    if ($null -ne $sidecar) {
        try { if (-not $sidecar.HasExited) { Stop-Process -Id $sidecar.Id -Force; $sidecar.WaitForExit() } }
        catch { }
        $sidecar.Dispose()
    }
    if ($null -ne $legacy) {
        try { if (-not $legacy.HasExited) { Stop-Process -Id $legacy.Id -Force; $legacy.WaitForExit() } }
        catch { }
        $legacy.Dispose()
    }
    Remove-Item Env:\KY_WINDOWS_CI_ONLY -ErrorAction SilentlyContinue
    Remove-Item Env:\ADMISSION_VIRTUAL_ONLY -ErrorAction SilentlyContinue
    Remove-Item Env:\APP_ENV -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $private) {
        Remove-Item -LiteralPath $private -Recurse -Force
    }
}
