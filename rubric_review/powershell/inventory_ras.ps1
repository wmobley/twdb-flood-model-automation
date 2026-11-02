# Inventories HEC-RAS projects under Root: plans, their geometry/flow dependencies, and map shapefiles. Read-only.
param([Parameter(Mandatory)][string]$Root)
$ErrorActionPreference = 'Stop'

function Get-Key([string[]]$Lines, [string]$Key) {
    $line = $Lines | Where-Object { $_ -like "$Key=*" } | Select-Object -First 1
    if ($line) { return ($line.Substring($Key.Length + 1)).Trim() }
    return ''
}

$projects = @()
foreach ($prj in Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.prj') {
    $head = Get-Content -LiteralPath $prj.FullName -TotalCount 60 -ErrorAction SilentlyContinue
    if (-not ($head | Where-Object { $_ -like 'Proj Title=*' })) { continue }   # not a RAS project (e.g. a GIS .prj)
    $dir = $prj.DirectoryName
    $base = $prj.BaseName
    $planRx = '^' + [regex]::Escape($base) + '\.p\d\d$'
    $plans = @()
    foreach ($p in Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Name -match $planRx }) {
        $lines = Get-Content -LiteralPath $p.FullName -TotalCount 60
        $geom = Get-Key $lines 'Geom File'
        $flow = Get-Key $lines 'Flow File'
        $plans += [pscustomobject]@{
            file = $p.FullName; ext = $p.Extension.TrimStart('.')
            title = Get-Key $lines 'Plan Title'; shortId = Get-Key $lines 'Short Identifier'
            geomFile = $geom; geomExists = [bool]($geom -and (Test-Path -LiteralPath (Join-Path $dir "$base.$geom")))
            flowFile = $flow; flowExists = [bool]($flow -and (Test-Path -LiteralPath (Join-Path $dir "$base.$flow")))
            flowTitle = if ($flow -and (Test-Path -LiteralPath (Join-Path $dir "$base.$flow"))) {
                Get-Key (Get-Content -LiteralPath (Join-Path $dir "$base.$flow") -TotalCount 20) 'Flow Title' } else { '' }
        }
    }
    $shapes = @()
    $rasmap = Join-Path $dir "$base.rasmap"
    if (Test-Path -LiteralPath $rasmap) {
        foreach ($m in Select-String -LiteralPath $rasmap -Pattern 'Filename="([^"]+\.shp)"' -AllMatches) {
            foreach ($g in $m.Matches) {
                $rel = $g.Groups[1].Value
                $full = [IO.Path]::GetFullPath((Join-Path $dir $rel))
                $shapes += [pscustomobject]@{ ref = $rel; exists = (Test-Path -LiteralPath $full) }
            }
        }
    }
    $projects += [pscustomobject]@{
        prj = $prj.FullName; dir = $dir; base = $base
        title = Get-Key $head 'Proj Title'; rasmapExists = (Test-Path -LiteralPath $rasmap)
        plans = @($plans); shapefiles = @($shapes)
    }
}
ConvertTo-Json -InputObject @($projects) -Depth 8 -Compress
