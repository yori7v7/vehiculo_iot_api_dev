param([string]$BaseUrl = 'http://127.0.0.1:8043')
$ErrorActionPreference = 'Stop'
$uri = [uri]$BaseUrl
if (!($uri.Scheme -eq 'https' -or ($uri.Scheme -eq 'http' -and $uri.IsLoopback))) {
    throw 'Usa HTTPS o el servidor de loopback.'
}
$base = $BaseUrl.TrimEnd('/')
$health = Invoke-RestMethod -Uri "$base/" -TimeoutSec 12 -MaximumRedirection 0
$db = Invoke-RestMethod -Uri "$base/health/database" -TimeoutSec 12 -MaximumRedirection 0
$spec = Invoke-RestMethod -Uri "$base/openapi.json" -TimeoutSec 12 -MaximumRedirection 0
$catalog = Invoke-RestMethod -Uri "$base/plataforma/catalogo" -TimeoutSec 12 -MaximumRedirection 0
if ($health.status -ne 'ok' -or $db.database -ne 'available' -or $spec.info.version -ne '4.3.0') {
    throw 'La API, el diagnóstico MySQL o la versión publicada no pasó la comprobación.'
}
$paths = $spec.paths.PSObject.Properties.Name
if (($paths -contains '/vehiculos') -or ($paths -notcontains '/plataforma/sesion') -or
    ($catalog.PSObject.Properties.Name -notcontains 'modelos') -or
    ($catalog.PSObject.Properties.Name -notcontains 'unidades')) {
    throw 'Las rutas 4.3 y la retirada del contrato legado no coinciden.'
}
Write-Output 'API 4.3, MySQL y OpenAPI verificados por lectura.'

function Require-HttpCode([string]$Path, [int]$Expected, [hashtable]$Headers = @{}) {
    $status = 0
    try {
        $result = Invoke-WebRequest -UseBasicParsing -Uri "$base$Path" -Method Get -Headers $Headers -TimeoutSec 12 -MaximumRedirection 0
        $status = [int]$result.StatusCode
    } catch {
        if (-not $_.Exception.Response) { throw }
        $status = [int]$_.Exception.Response.StatusCode
    }
    if ($status -ne $Expected) { throw ('Respuesta {0} inesperada en {1}.' -f $status,$Path) }
}

Require-HttpCode '/vehiculos' 404
Require-HttpCode '/plataforma/perfil' 401 @{ 'X-API-Key'='retired-fixture-not-a-credential' }
$origin = 'https://yori7v7.github.io'
$preflight = Invoke-WebRequest -UseBasicParsing -Uri "$base/plataforma/sesion" -Method Options -TimeoutSec 12 -MaximumRedirection 0 -Headers @{
    'Origin'=$origin
    'Access-Control-Request-Method'='POST'
    'Access-Control-Request-Headers'='authorization, content-type'
}
if ($preflight.StatusCode -ne 200 -or ($preflight.Headers['Access-Control-Allow-Origin'] -join '') -ne $origin) {
    throw 'CORS de Pages no paso el preflight.'
}
Write-Output 'Contrato legado retirado, clave antigua sin acceso a 4.3 y origen Pages admitido.'
