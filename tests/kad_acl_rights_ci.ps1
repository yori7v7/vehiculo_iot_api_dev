# K-AF: prueba de mascara ACL de preflight Windows PowerShell 5.1.
# Ejecuta SOLO la definicion de funcion extraida por AST del codigo del PR,
# con Get-Acl simulado; no toca ACL reales ni archivos del sistema.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT') {
    throw 'K-AF ACL solo en runner de Windows GitHub Actions.'
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$source = Join-Path $root 'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $source, [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) { throw 'K-AF: preflight PowerShell invalido' }
$matches = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'HasUnsafeWrite-KAC'
}, $true))
if ($matches.Count -ne 1) { throw 'K-AF: no se encontro funcion de ACL unica' }
# Esta definicion es codigo auditable del propio repositorio, no entrada externa.
Invoke-Expression $matches[0].Extent.Text

$global:KAF_Rules = @()
$fixtureAcl = New-Object PSObject
$fixtureAcl | Add-Member -MemberType ScriptMethod -Name GetAccessRules -Value {
    param($explicit, $inherited, $targetType)
    return @($global:KAF_Rules)
}
function Get-Acl {
    param([string]$LiteralPath)
    return $fixtureAcl
}
function Mock-Rule([string]$Sid, [string]$Kind, [Security.AccessControl.FileSystemRights]$Rights) {
    return [pscustomobject]@{
        AccessControlType = $Kind
        IdentityReference = [pscustomobject]@{ Value = $Sid }
        FileSystemRights = $Rights
    }
}
$cases = @(
    @{name='Everyone delete children';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles));unsafe=$true},
    @{name='Authenticated Users delete children';rules=@((Mock-Rule 'S-1-5-11' 'Allow' [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles));unsafe=$true},
    @{name='Builtin Users delete children';rules=@((Mock-Rule 'S-1-5-32-545' 'Allow' [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles));unsafe=$true},
    @{name='Everyone write';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::Write));unsafe=$true},
    @{name='Everyone delete';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::Delete));unsafe=$true},
    @{name='Everyone change permissions';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::ChangePermissions));unsafe=$true},
    @{name='Everyone take ownership';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::TakeOwnership));unsafe=$true},
    @{name='Everyone read only';rules=@((Mock-Rule 'S-1-1-0' 'Allow' [Security.AccessControl.FileSystemRights]::ReadAndExecute));unsafe=$false},
    @{name='Denied write does not grant write';rules=@((Mock-Rule 'S-1-1-0' 'Deny' [Security.AccessControl.FileSystemRights]::Write));unsafe=$false},
    @{name='No allow rules';rules=@();unsafe=$false}
)
$pass = 0
foreach ($c in $cases) {
    $global:KAF_Rules = @($c.rules)
    $actual = HasUnsafeWrite-KAC 'fixture-ACL-in-memory'
    if ([bool]$actual -ne [bool]$c.unsafe) {
        throw ('[K-AF] ACL no coincide: ' + $c.name)
    }
    $pass++
    Write-Output ('[K-AF CI] OK: ' + $c.name)
}
Remove-Variable -Name KAF_Rules -Scope Global -ErrorAction SilentlyContinue
Write-Output ('[K-AF CI] ' + $pass + '/' + $cases.Count + ' escenarios de permisos aprobados; no se leyeron ni cambiaron ACL reales.')
exit 0
