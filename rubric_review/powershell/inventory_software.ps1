# Lists installed HEC-RAS / HEC-HMS versions. Read-only.
$ErrorActionPreference = 'SilentlyContinue'
$found = @()
foreach ($product in 'HEC-RAS', 'HEC-HMS') {
    foreach ($base in 'C:\Program Files (x86)\HEC', 'C:\Program Files\HEC') {
        $dir = Join-Path $base $product
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        foreach ($v in Get-ChildItem -LiteralPath $dir -Directory) {
            $exe = if ($product -eq 'HEC-RAS') { Join-Path $v.FullName 'Ras.exe' } else { Join-Path $v.FullName 'hec-hms.cmd' }
            $found += [pscustomobject]@{
                product = $product; version = $v.Name; path = $v.FullName
                exe = $exe; exeExists = (Test-Path -LiteralPath $exe)
            }
        }
    }
}
[pscustomobject]@{ computer = $env:COMPUTERNAME; user = $env:USERNAME; installs = @($found) } |
    ConvertTo-Json -Depth 5 -Compress
