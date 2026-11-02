# Expands an uploaded model zip into a fresh scratch folder so originals stay untouched.
param(
    [Parameter(Mandatory)][string]$Zip,
    [Parameter(Mandatory)][string]$Dest
)
$ErrorActionPreference = 'Stop'
# Relative paths resolve against the user's home; absolute paths are used as given.
$zipPath = if ([IO.Path]::IsPathRooted($Zip)) { $Zip } else { Join-Path $HOME $Zip }
$destPath = if ([IO.Path]::IsPathRooted($Dest)) { $Dest } else { Join-Path $HOME $Dest }
if (Test-Path -LiteralPath $destPath) { Remove-Item -LiteralPath $destPath -Recurse -Force }
Expand-Archive -LiteralPath $zipPath -DestinationPath $destPath -Force
[pscustomobject]@{
    root = $destPath
    fileCount = (Get-ChildItem -LiteralPath $destPath -Recurse -File | Measure-Object).Count
} | ConvertTo-Json -Compress
