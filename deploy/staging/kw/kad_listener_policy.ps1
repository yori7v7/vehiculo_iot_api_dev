# K-AD: politica PURA de listeners, sin consultar red ni modificar Windows.
# Solo se aplica al preflight previo a instalar el sidecar virtual.
# Rechaza ausencia del legacy 8000, todo bind no-loopback y cualquier 9444 activo.
function Test-KADPortPolicy {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()][object[]]$LegacyListeners = @(),
        [AllowEmptyCollection()][object[]]$SidecarListeners = @()
    )
    $loopback = @('127.0.0.1', '::1')
    $legacyPresent = @($LegacyListeners).Count -gt 0
    $legacyUnsafe = @($LegacyListeners | Where-Object {
        $_.LocalAddress -notin $loopback
    }).Count -gt 0
    $sidecarAbsent = @($SidecarListeners).Count -eq 0
    [pscustomobject]@{
        LegacyPresent      = [bool]$legacyPresent
        LegacyLoopbackOnly = [bool]($legacyPresent -and -not $legacyUnsafe)
        SidecarAbsent      = [bool]$sidecarAbsent
        IsSafe             = [bool]($legacyPresent -and -not $legacyUnsafe -and $sidecarAbsent)
    }
}
