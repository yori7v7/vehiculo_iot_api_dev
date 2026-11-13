# K-AD: verificacion PURA de propiedad de listeners para Windows PowerShell 5.1.
# No lee el host, no consulta procesos y no realiza operaciones de escritura.
# Compara (PID, inicio, ejecutable) del registro protegido con el proceso vivo
# y exige que TODOS los listeners observados pertenezcan al PID registrado.
function Test-KADProcessOwnership {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()][object[]]$Listeners = @(),
        [AllowNull()][object]$Record,
        [AllowNull()][object]$Process,
        [AllowNull()][string]$ExpectedImagePath
    )
    $result = [ordered]@{
        HasListeners       = $false
        IdentityMatches    = $false
        AllListenersOwned  = $false
        IsSafe             = $false
    }
    try {
        $result.HasListeners = (@($Listeners).Count -gt 0)
        if ($null -eq $Record -or $null -eq $Process -or
            [string]::IsNullOrWhiteSpace($ExpectedImagePath)) {
            return [pscustomobject]$result
        }
        $recordPid = 0
        $actualPid = 0
        if (-not [int]::TryParse([string]$Record.process_id, [ref]$recordPid) -or
            -not [int]::TryParse([string]$Process.ProcessId, [ref]$actualPid) -or
            $recordPid -le 0 -or $recordPid -ne $actualPid) {
            return [pscustomobject]$result
        }
        $recordImage = [string]$Record.executable_path
        $actualImage = [string]$Process.ExecutablePath
        $imageOk = [string]::Equals($recordImage, $ExpectedImagePath,
            [StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals($actualImage, $ExpectedImagePath,
                [StringComparison]::OrdinalIgnoreCase)
        $created = [string]$Process.CreationDate.ToUniversalTime().Ticks
        $timeOk = ($created -eq [string]$Record.creation_ticks)
        $result.IdentityMatches = [bool]($imageOk -and $timeOk)
        $ownersOk = $result.HasListeners
        foreach ($listener in @($Listeners)) {
            $ownerPid = 0
            if (-not [int]::TryParse([string]$listener.OwningProcess, [ref]$ownerPid) -or
                $ownerPid -ne $recordPid) {
                $ownersOk = $false
            }
        }
        $result.AllListenersOwned = [bool]$ownersOk
        $result.IsSafe = [bool]($result.HasListeners -and
            $result.IdentityMatches -and $result.AllListenersOwned)
    }
    catch {
        # Falta de propiedades, fechas malformadas u otra incertidumbre: NO-GO.
        return [pscustomobject]([ordered]@{
            HasListeners = $false
            IdentityMatches = $false
            AllListenersOwned = $false
            IsSafe = $false
        })
    }
    return [pscustomobject]$result
}
