# Computes one HEC-RAS plan headlessly (Ras.exe -c) and reports exit status, fresh results and error lines.
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Prj,
    [Parameter(Mandatory)][string]$Plan,
    [int]$TimeoutMin = 60
)
$ErrorActionPreference = 'Stop'
$start = Get-Date
$dir = Split-Path -Parent $Prj
$proc = Start-Process -FilePath $Exe -ArgumentList @('-c', "`"$Prj`"", "`"$Plan`"") -PassThru -WindowStyle Hidden
$timedOut = -not $proc.WaitForExit($TimeoutMin * 60000)
if ($timedOut) { Stop-Process -Id $proc.Id -Force }
$exit = if ($timedOut) { $null } else { $proc.ExitCode }

$fresh = @(Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.LastWriteTime -ge $start })
$planHdf = $fresh | Where-Object { $_.Name -like ((Split-Path -Leaf $Plan) + '.hdf') } | Select-Object -First 1
$msgFile = $fresh | Where-Object { $_.Name -match 'computeMsgs\.txt$' } | Select-Object -First 1
$errors = @()
$tail = ''
if ($msgFile) {
    $text = Get-Content -LiteralPath $msgFile.FullName -Raw -ErrorAction SilentlyContinue
    $errors = @(($text -split "`r?`n") | Where-Object { $_ -match '(?i)\b(error|errors|failed|abort\w*)\b' } | Select-Object -First 25)
    $tail = if ($text.Length -gt 1500) { $text.Substring($text.Length - 1500) } else { $text }
}
[pscustomobject]@{
    exitCode = $exit; timedOut = $timedOut
    planHdfUpdated = [bool]$planHdf; computeMsgsFile = if ($msgFile) { $msgFile.Name } else { '' }
    errorLines = $errors; messagesTail = $tail
    seconds = [int]((Get-Date) - $start).TotalSeconds
} | ConvertTo-Json -Depth 4 -Compress
