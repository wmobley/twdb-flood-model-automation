# Reports progress of a run begun by start_run.ps1; once it has ended, also reports the outcome and clears its scratch folder.
param(
    [Parameter(Mandatory)][ValidateSet('ras', 'hms')][string]$Kind,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$ProjectDir,
    [Parameter(Mandatory)][string]$StartedUtc,
    [Parameter(Mandatory)][int]$ProcessId,
    [string]$Plan = '',
    [int]$Probe = 0  # 1 = also list changed files and the tail of any text/log files, to learn what the tool writes while it runs
)
$ErrorActionPreference = 'Stop'
$started = [datetime]::Parse($StartedUtc, [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
$exitFile = Join-Path $RunDir 'exit.txt'
$finished = Test-Path -LiteralPath $exitFile
$alive = [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
$running = (-not $finished) -and $alive
$exitCode = $null
if ($finished) { $exitCode = [int]((Get-Content -LiteralPath $exitFile -Raw).Trim()) }

$recurse = $Kind -eq 'hms'
$files = @(Get-ChildItem -LiteralPath $ProjectDir -File -Recurse:$recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -ge $started })
$latest = $files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1

$children = @()
if ($running) {
    $all = @(Get-CimInstance Win32_Process)
    $ids = New-Object 'System.Collections.Generic.HashSet[int]'
    [void]$ids.Add($ProcessId)
    do {
        $before = $ids.Count
        foreach ($p in $all) { if ($ids.Contains([int]$p.ParentProcessId)) { [void]$ids.Add([int]$p.ProcessId) } }
    } while ($ids.Count -gt $before)
    $children = @($all | Where-Object { $ids.Contains([int]$_.ProcessId) -and [int]$_.ProcessId -ne $ProcessId } | ForEach-Object {
        $cpu = (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue).CPU
        '{0} (cpu {1}s)' -f $_.Name, [int]$cpu
    })
}

$msgFile = if ($Kind -eq 'ras') { $files | Where-Object { $_.Name -match 'computeMsgs\.txt$' } | Select-Object -First 1 }
           else { Get-Item -LiteralPath (Join-Path $RunDir 'out.txt') -ErrorAction SilentlyContinue }
$text = if ($msgFile) { Get-Content -LiteralPath $msgFile.FullName -Raw -ErrorAction SilentlyContinue } else { '' }
if (-not $text) { $text = '' }
$lines = @(($text -split "`r?`n") | Where-Object { $_.Trim() })

$errors = @()
$planHdf = $false
$dss = 0
if (-not $running) {
    $errors = @($lines | Where-Object { $_ -match '(?i)\b(error|errors|exception|failed|traceback|abort\w*)\b' } | Select-Object -First 25)
    if ($Plan) { $planHdf = [bool]($files | Where-Object { $_.Name -eq ((Split-Path -Leaf $Plan) + '.hdf') }) }
    $dss = @($files | Where-Object { $_.Extension -eq '.dss' }).Count
    Remove-Item -LiteralPath $RunDir -Recurse -Force -ErrorAction SilentlyContinue
}
$probeFiles = @()
$probeText = @()
if ($Probe) {
    $watch = @($files)
    $watch += @(Get-ChildItem -LiteralPath $env:TEMP -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTimeUtc -ge $started })
    $watch += @(Get-ChildItem -LiteralPath $RunDir -File -ErrorAction SilentlyContinue)
    $watch = @($watch | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 40)
    $now = (Get-Date).ToUniversalTime()
    $probeFiles = @($watch | ForEach-Object {
        [pscustomobject]@{ path = $_.FullName; bytes = $_.Length; agoSeconds = [int]($now - $_.LastWriteTimeUtc).TotalSeconds }
    })
    $probeText = @($watch | Where-Object { $_.Extension -in '.txt', '.log', '.out', '.msg' -or $_.Name -match 'Msgs' } | Select-Object -First 6 | ForEach-Object {
        try {
            $fs = [IO.File]::Open($_.FullName, 'Open', 'Read', 'ReadWrite')
            $reader = New-Object IO.StreamReader($fs)
            $all = $reader.ReadToEnd(); $reader.Close()
            [pscustomobject]@{ path = $_.FullName; tail = if ($all.Length -gt 600) { $all.Substring($all.Length - 600) } else { $all } }
        } catch { [pscustomobject]@{ path = $_.FullName; tail = "(unreadable: $($_.Exception.Message))" } }
    })
}
[pscustomobject]@{
    running = $running; exitCode = $exitCode
    seconds = [int]((Get-Date).ToUniversalTime() - $started).TotalSeconds
    lastFile = if ($latest) { $latest.Name } else { '' }
    lastFileAgo = if ($latest) { [int]((Get-Date).ToUniversalTime() - $latest.LastWriteTimeUtc).TotalSeconds } else { $null }
    processes = $children; progressTail = @($lines | Select-Object -Last 3)
    errorLines = $errors; planHdfUpdated = $planHdf; freshDssFiles = $dss
    probeFiles = $probeFiles; probeText = $probeText
    messagesTail = if ($text.Length -gt 1500) { $text.Substring($text.Length - 1500) } else { $text }
} | ConvertTo-Json -Depth 4 -Compress
