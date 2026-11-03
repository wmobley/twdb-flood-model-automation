# Inventories HEC-HMS projects under Root: simulation runs and shapefile references. Read-only.
param([Parameter(Mandatory)][string]$Root)
$ErrorActionPreference = 'Stop'
$projects = @()
foreach ($hms in Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.hms') {
    $dir = $hms.DirectoryName
    $runs = @()
    $runFile = Join-Path $dir ($hms.BaseName + '.run')
    if (Test-Path -LiteralPath $runFile) {
        $current = $null
        foreach ($line in Get-Content -LiteralPath $runFile) {
            if ($line -match '^Run:\s*(.+)$') { $current = $Matches[1].Trim(); $runs += [pscustomobject]@{ name = $current; basin = ''; met = ''; control = '' } }
            elseif ($current -and $line -match '^\s*Basin:\s*(.+)$') { $runs[-1].basin = $Matches[1].Trim() }
            elseif ($current -and $line -match '^\s*(Precip|Met):\s*(.+)$') { $runs[-1].met = $Matches[2].Trim() }
            elseif ($current -and $line -match '^\s*Control:\s*(.+)$') { $runs[-1].control = $Matches[1].Trim() }
        }
    }
    $shapes = @()
    foreach ($f in Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Extension -in '.basin', '.map', '.hms' }) {
        foreach ($m in Select-String -LiteralPath $f.FullName -Pattern '([^\s"=:]+\.shp)' -AllMatches) {
            foreach ($g in $m.Matches) { $shapes += [pscustomobject]@{ ref = $g.Groups[1].Value; source = $f.Name } }
        }
    }
    $projects += [pscustomobject]@{
        hms = $hms.FullName; dir = $dir; name = $hms.BaseName
        runs = @($runs); shapefiles = @($shapes)
        shpOnDisk = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Filter '*.shp' | Select-Object -ExpandProperty Name)
    }
}
ConvertTo-Json -InputObject @($projects) -Depth 8 -Compress
