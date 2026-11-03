# Stops a run begun by start_run.ps1, including everything it launched.
param([Parameter(Mandatory)][int]$ProcessId)
& taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
[pscustomobject]@{ stopped = -not [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) } | ConvertTo-Json -Compress
