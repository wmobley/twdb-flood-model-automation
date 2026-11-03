# Starts one HEC-RAS plan or HEC-HMS run detached from this session and returns at once; poll_run.ps1 follows it.
param(
    [Parameter(Mandatory)][ValidateSet('ras', 'hms')][string]$Kind,
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Target,  # .prj (HEC-RAS) or .hms (HEC-HMS)
    [Parameter(Mandatory)][string]$Unit     # plan file (HEC-RAS) or simulation run name (HEC-HMS)
)
$ErrorActionPreference = 'Stop'
function Q([string]$s) { "'" + $s.Replace("'", "''") + "'" }
$started = (Get-Date).ToUniversalTime()
$dir = Join-Path $env:TEMP ('rubric-run-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $dir | Out-Null
$exitFile = Join-Path $dir 'exit.txt'

if ($Kind -eq 'ras') {
    $body = '$p = Start-Process -FilePath {0} -ArgumentList @(''-c'', {1}, {2}) -WindowStyle Hidden -PassThru -Wait' -f (Q $Exe), (Q ('"' + $Target + '"')), (Q ('"' + $Unit + '"'))
} else {
    $py = Join-Path $dir 'run.py'
    $out = Join-Path $dir 'out.txt'
    @(
        'from hms.model import Project'
        ('project = Project.open(r"{0}")' -f $Target)
        ('project.computeRun("{0}")' -f $Unit)
        'project.close()'
    ) | Set-Content -LiteralPath $py -Encoding ASCII
    $cmdline = '""' + $Exe + '" -script "' + $py + '" > "' + $out + '" 2>&1"'
    $body = '$p = Start-Process -FilePath cmd.exe -ArgumentList @(''/c'', {0}) -WindowStyle Hidden -PassThru -Wait' -f (Q $cmdline)
}
$wrapper = Join-Path $dir 'wrapper.ps1'
($body + "`r`n" + ('Set-Content -LiteralPath {0} -Value $p.ExitCode' -f (Q $exitFile))) | Set-Content -LiteralPath $wrapper -Encoding UTF8

# A WMI-created process lives outside the remoting session, so it keeps running between polls.
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $wrapper + '"'
    CurrentDirectory = $dir
}
if ($created.ReturnValue -ne 0) { throw "Could not start the compute process (Win32_Process.Create returned $($created.ReturnValue))" }
[pscustomobject]@{
    runDir = $dir; processId = [int]$created.ProcessId
    startedUtc = $started.ToString('o'); projectDir = (Split-Path -Parent $Target)
} | ConvertTo-Json -Compress
