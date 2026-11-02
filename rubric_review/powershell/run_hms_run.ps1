# Computes one HEC-HMS simulation run through the HMS Jython scripting interface.
param(
    [Parameter(Mandatory)][string]$Cmd,
    [Parameter(Mandatory)][string]$Hms,
    [Parameter(Mandatory)][string]$RunName,
    [int]$TimeoutMin = 60
)
$ErrorActionPreference = 'Stop'
$start = Get-Date
$py = Join-Path $env:TEMP ('hms-run-' + [guid]::NewGuid().ToString('N') + '.py')
$out = Join-Path $env:TEMP ('hms-out-' + [guid]::NewGuid().ToString('N') + '.txt')
@(
    'from hms.model import Project'
    ('project = Project.open(r"{0}")' -f $Hms)
    ('project.computeRun("{0}")' -f $RunName)
    'project.close()'
) | Set-Content -LiteralPath $py -Encoding ASCII
$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', "`"$Cmd`" -script `"$py`" > `"$out`" 2>&1") -PassThru -WindowStyle Hidden
$timedOut = -not $proc.WaitForExit($TimeoutMin * 60000)
if ($timedOut) { Stop-Process -Id $proc.Id -Force }
$text = if (Test-Path -LiteralPath $out) { Get-Content -LiteralPath $out -Raw } else { '' }
$errors = @(($text -split "`r?`n") | Where-Object { $_ -match '(?i)\b(error|exception|failed|traceback)\b' } | Select-Object -First 25)
$dir = Split-Path -Parent $Hms
$freshDss = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Filter '*.dss' | Where-Object { $_.LastWriteTime -ge $start }).Count
Remove-Item -LiteralPath $py, $out -ErrorAction SilentlyContinue
[pscustomobject]@{
    exitCode = if ($timedOut) { $null } else { $proc.ExitCode }; timedOut = $timedOut
    freshDssFiles = $freshDss; errorLines = $errors
    outputTail = if ($text.Length -gt 1500) { $text.Substring($text.Length - 1500) } else { $text }
    seconds = [int]((Get-Date) - $start).TotalSeconds
} | ConvertTo-Json -Depth 4 -Compress
