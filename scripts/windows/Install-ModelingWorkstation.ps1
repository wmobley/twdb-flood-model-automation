<#
.SYNOPSIS
Plans, downloads, or installs a reviewed Windows modeling workstation catalog.
.DESCRIPTION
Defaults to Plan. DownloadOnly never launches installers. Install requires Windows 11 x64.
Run Install first in a normal PowerShell for JustMe Miniforge, then rerun as Administrator
for QGIS and modern HEC installers. Legacy packages remain manual-required.
No execution policy, global PATH, Windows features, or existing environments are changed.
.EXAMPLE
.\Install-ModelingWorkstation.ps1 -Mode Plan
.EXAMPLE
.\Install-ModelingWorkstation.ps1 -Mode DownloadOnly -CacheDirectory C:\ModelingCache
.EXAMPLE
.\Install-ModelingWorkstation.ps1 -Mode Install -MiniforgeDirectory C:\Users\Alice\miniforge3
#>
#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Plan','DownloadOnly','Install')][string]$Mode = 'Plan',
    [ValidateSet('Miniforge','QGIS','HEC-RAS','HEC-HMS','Chrome')][string[]]$Products = @('Miniforge','QGIS','HEC-RAS','HEC-HMS','Chrome'),
    [string]$ManifestPath = (Join-Path $PSScriptRoot '../../configs/windows/modeling-workstation.json'),
    [string]$CacheDirectory = (Join-Path ([IO.Path]::GetTempPath()) 'modeling-workstation-cache'),
    [string]$ReportDirectory = (Join-Path ([IO.Path]::GetTempPath()) 'modeling-workstation-reports'),
    [string]$MiniforgeDirectory = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'miniforge3')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-WorkstationWindows { return [Environment]::OSVersion.Platform -eq 'Win32NT' }
function Assert-AllowedUri {
    param([uri]$Uri, [string[]]$AllowedHosts)
    if ($Uri.Scheme -ne 'https' -or $Uri.UserInfo -or $Uri.Port -ne 443 -or $Uri.DnsSafeHost -notin $AllowedHosts) {
        throw "Unapproved download URI: $Uri"
    }
}
function ConvertTo-NormalizedVersion {
    param([string]$Version)
    $v = [version]$Version
    return New-Object version($v.Major,$v.Minor,[Math]::Max(0,$v.Build),[Math]::Max(0,$v.Revision))
}
function Read-WorkstationManifest {
    param([string]$Path)
    $m = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($m.schemaVersion -ne 1 -or !$m.catalogVerifiedOn -or !$m.packages) { throw 'Unsupported or incomplete manifest.' }
    $ids = @()
    $trusted = @('github.com','release-assets.githubusercontent.com','www.hec.usace.army.mil','download.qgis.org','dl.google.com')
    foreach ($p in $m.packages) {
        if ($p.id -notmatch '^[a-z0-9-]+$' -or $p.id -in $ids) { throw 'Invalid or duplicate package ID.' }
        $ids += $p.id
        if ($p.product -notin @('Miniforge','QGIS','HEC-RAS','HEC-HMS','Chrome') -or
            $p.version -notmatch '^\d+(\.\d+){1,3}$' -or $p.major -ne [int]($p.version.Split('.')[0]) -or
            $p.architecture -notin @('x64','x86','legacy-unknown') -or
            $p.stability -notin @('stable','preview') -or
            $p.installMethod -notin @('miniforge-silent','msi-interactive','hec-interactive','manual') -or
            $p.detectionMethod -notin @('miniforge-history','uninstall-registry') -or
            $p.fileName -notmatch '^[A-Za-z0-9_.-]+\.(exe|msi)$') { throw "Invalid package metadata: $($p.id)" }
        if (!$p.sourcePage -or ([uri]$p.sourcePage).Scheme -ne 'https' -or !$p.verifiedOn -or !$p.integrity.provenance -or !$p.notes) { throw 'Missing provenance.' }
        foreach ($hostName in $p.allowedHosts) { if ($hostName -notin $trusted) { throw 'Unreviewed artifact host.' } }
        Assert-AllowedUri -Uri $p.url -AllowedHosts $p.allowedHosts
        if ($p.integrity.sha256 -and $p.integrity.sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid SHA256.' }
        if ($p.installMethod -ne 'manual' -and (!$p.integrity.sha256 -or !$p.coexistenceEvidence)) {
            throw "Executable package lacks pinned authenticity/coexistence evidence: $($p.id)"
        }
        # Arguments are code-owned; arbitrary commands/arguments are never interpreted from the catalog.
        $adapter = @{Miniforge='miniforge-silent'; QGIS='msi-interactive'; 'HEC-RAS'='hec-interactive'; 'HEC-HMS'='hec-interactive'; Chrome='msi-interactive'}
        if ($p.installMethod -ne 'manual' -and $p.installMethod -ne $adapter[$p.product]) { throw 'Installer adapter does not match product.' }
        if ($p.requiresAdmin -ne ($p.product -ne 'Miniforge')) { throw 'Unexpected privilege metadata.' }
        if ($p.PSObject.Properties.Name -contains 'arguments') { throw 'Manifest arguments are forbidden.' }
        if ($p.registryName -notmatch '^[A-Za-z0-9 ._-]+$') { throw 'Invalid detection name.' }
    }
    return $m
}
function Select-WorkstationPackage {
    param([object[]]$Packages)
    $Packages | Where-Object { $_.stability -eq 'stable' } |
        Group-Object { "$($_.product):$($_.major)" } | ForEach-Object {
            $_.Group | Sort-Object @{Expression={[version]$_.version};Descending=$true} | Select-Object -First 1
        }
}
function Assert-Artifact {
    param([string]$Path, $Package)
    $f = Get-Item -LiteralPath $Path
    if ($f.Length -lt 1024) { throw 'Incomplete artifact (less than 1 KiB).' }
    $stream = [IO.File]::OpenRead($f.FullName)
    try { $head = New-Object byte[] 8; [void]$stream.Read($head,0,8) } finally { $stream.Dispose() }
    if ($Package.fileName.EndsWith('.exe')) {
        if ($head[0] -ne 0x4d -or $head[1] -ne 0x5a) { throw 'Artifact is not a Windows executable; HTML/error response rejected.' }
    } elseif ([BitConverter]::ToString($head) -ne 'D0-CF-11-E0-A1-B1-1A-E1') { throw 'Artifact is not an MSI compound document.' }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Package.integrity.sha256 -and $hash -ne $Package.integrity.sha256.ToLowerInvariant()) {
        throw 'Pinned SHA256 mismatch. Do not approve changed bytes by updating a local cache hash.'
    }
    $sig = 'not-checked-non-windows'
    if (Test-WorkstationWindows) { $sig = [string](Get-AuthenticodeSignature -LiteralPath $Path).Status }
    return [pscustomobject]@{path=$f.FullName;size=$f.Length;sha256=$hash;publisherChecksum=($(if ($Package.integrity.sha256) {'matched'} else {'unavailable-local-fingerprint-only'}));signature=$sig}
}
function Receive-OfficialArtifact {
    param([uri]$Uri,[string[]]$AllowedHosts,[string]$Destination)
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(45)
    try {
        for ($hop=0; $hop -lt 8; $hop++) {
            Assert-AllowedUri $Uri $AllowedHosts
            $response = $client.GetAsync($Uri,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            try {
                $code = [int]$response.StatusCode
                if ($code -in @(301,302,303,307,308)) {
                    if (!$response.Headers.Location) { throw 'Redirect has no destination.' }
                    $Uri = New-Object uri($Uri,$response.Headers.Location)
                    continue
                }
                [void]$response.EnsureSuccessStatusCode()
                if ([string]$response.Content.Headers.ContentType -match '(text/|html|json)') { throw 'Server returned text instead of an installer.' }
                $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                $outputStream = [IO.File]::Open($Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose(); $inputStream.Dispose() }
                if ($response.Content.Headers.ContentLength -and (Get-Item -LiteralPath $Destination).Length -ne $response.Content.Headers.ContentLength) { throw 'Truncated download.' }
                return $Uri.AbsoluteUri
            } finally { $response.Dispose() }
        }
        throw 'Too many redirects.'
    } finally { $client.Dispose(); $handler.Dispose() }
}
function Get-PackageArtifact {
    param($Package,[string]$CacheDirectory)
    $directory = Join-Path $CacheDirectory $Package.id
    [void](New-Item -ItemType Directory -Path $directory -Force)
    $path = Join-Path $directory $Package.fileName
    $auditPath = "$path.provenance.json"
    if (Test-Path -LiteralPath $path) {
        $audit = Assert-Artifact $path $Package
        if (!(Test-Path -LiteralPath $auditPath)) { throw 'Cache provenance missing; review cached artifact before reuse.' }
        $old = Get-Content -LiteralPath $auditPath -Raw | ConvertFrom-Json
        if ($old.sha256 -ne $audit.sha256 -or $old.sourceUrl -ne $Package.url) { throw 'Cached bytes or source differ from recorded provenance.' }
        return $audit
    }
    $partial = "$path.$([guid]::NewGuid().ToString('N')).partial"
    $finalUrl = Receive-OfficialArtifact $Package.url $Package.allowedHosts $partial
    $audit = Assert-Artifact $partial $Package
    Move-Item -LiteralPath $partial -Destination $path
    $audit.path = $path
    $record = [ordered]@{sourceUrl=$Package.url;finalUrl=$finalUrl;retrievedAt=[DateTime]::UtcNow.ToString('o');size=$audit.size;sha256=$audit.sha256;publisherChecksum=$audit.publisherChecksum;signature=$audit.signature}
    $record | ConvertTo-Json | Set-Content -LiteralPath $auditPath -Encoding UTF8
    return $audit
}
function Get-InstalledPackage {
    param($Package,[string]$MiniforgeDirectory)
    if (!(Test-WorkstationWindows)) { return [pscustomobject]@{state='absent';message='Detection unavailable on this platform.'} }
    if ($Package.product -eq 'Miniforge') {
        if (!(Test-Path -LiteralPath $MiniforgeDirectory)) { return [pscustomobject]@{state='absent';message='Target directory absent.'} }
        $stamp = Join-Path $MiniforgeDirectory '.modeling-workstation-install.json'
        if (Test-Path -LiteralPath $stamp) {
            $s = Get-Content -LiteralPath $stamp -Raw | ConvertFrom-Json
            if ($s.version -eq $Package.version -and $s.sha256 -eq $Package.integrity.sha256 -and
                (Test-Path -LiteralPath (Join-Path $MiniforgeDirectory 'python.exe')) -and
                (Test-Path -LiteralPath (Join-Path $MiniforgeDirectory 'Scripts/conda.exe')) -and
                $s.pythonHash -eq (Get-FileHash -LiteralPath (Join-Path $MiniforgeDirectory 'python.exe') -Algorithm SHA256).Hash -and
                $s.condaHash -eq (Get-FileHash -LiteralPath (Join-Path $MiniforgeDirectory 'Scripts/conda.exe') -Algorithm SHA256).Hash) {
                return [pscustomobject]@{state='exact';message='Provisioning receipt and Python/Conda files detected; environments preserved.'}
            }
        }
        return [pscustomobject]@{state='conflict';message='Existing Miniforge directory preserved; no upgrade or overwrite.'}
    }
    $keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
    $entries = @($keys | ForEach-Object { Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue } |
        Where-Object { $_.PSObject.Properties.Name -contains 'DisplayName' -and $_.DisplayName -like "$($Package.registryName)*" })
    foreach ($entry in $entries) {
        if ($entry.PSObject.Properties.Name -contains 'DisplayVersion') {
            $v = [regex]::Match([string]$entry.DisplayVersion,'\d+(?:\.\d+){1,3}').Value
            if ($v -and (ConvertTo-NormalizedVersion $v) -eq (ConvertTo-NormalizedVersion $Package.version)) { return [pscustomobject]@{state='exact';message="Exact uninstall registration: $($entry.DisplayName) $v"} }
        }
    }
    # Any existing version is preserved. Even vendor side-by-side support cannot establish local customization safety.
    if ($entries.Count -and $Package.product -in @('HEC-RAS','HEC-HMS') -and $Package.coexistenceEvidence) {
        $sameMajorOrUnknown = @($entries | Where-Object {
            if ($_.PSObject.Properties.Name -notcontains 'DisplayVersion') { return $true }
            $installed = [regex]::Match([string]$_.DisplayVersion,'\d+(?:\.\d+){1,3}').Value
            return (!$installed -or [int]$installed.Split('.')[0] -eq $Package.major)
        })
        if (!$sameMajorOrUnknown.Count) { return [pscustomobject]@{state='absent';message='Only other major families detected; vendor documents independent version directories.'} }
    }
    if ($entries.Count) { return [pscustomobject]@{state='conflict';message='Other or unidentifiable product installation detected; preserve it and review side-by-side installation manually.'} }
    return [pscustomobject]@{state='absent';message='No matching uninstall registration.'}
}
function Test-WorkstationAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function New-ProtectedInstallerStage {
    # Elevated process creates a new directory with a protected ACL before copying any cache bytes.
    $base = Join-Path $env:ProgramData 'ModelingWorkstation'
    if (Test-Path -LiteralPath $base) {
        $acl = Get-Acl -LiteralPath $base
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18','S-1-5-32-544') -or !$acl.AreAccessRulesProtected -or (Get-Item -LiteralPath $base).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unsafe staging root; administrator must review/remove it manually.' }
        foreach ($rule in $acl.Access) {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($rule.AccessControlType -eq 'Allow' -and $sid -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Staging root grants access to unapproved principal.' }
        }
    } else {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true,$false)
        $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
        foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier($sid)),'FullControl','ContainerInherit,ObjectInherit','None','Allow')
            $acl.AddAccessRule($rule)
        }
        if ($PSVersionTable.PSEdition -eq 'Core') {
            [IO.FileSystemAclExtensions]::Create((New-Object IO.DirectoryInfo($base)),$acl)
        } else { [void][IO.Directory]::CreateDirectory($base,$acl) }
    }
    $stage = Join-Path $base ([guid]::NewGuid().ToString('N'))
    [void](New-Item -ItemType Directory -Path $stage)
    return $stage
}
function Install-WorkstationPackage {
    param($Package,$Artifact,[string]$MiniforgeDirectory)
    if ($Package.installMethod -eq 'manual') { throw 'Manual package cannot be launched.' }
    [void](Assert-Artifact $Artifact.path $Package)
    $path = $Artifact.path
    if ($Package.requiresAdmin) {
        if (!(Test-WorkstationAdministrator)) { throw 'Rerun PowerShell as Administrator for this installer; no automatic elevation is performed.' }
        $stage = New-ProtectedInstallerStage
        $path = Join-Path $stage $Package.fileName
        Copy-Item -LiteralPath $Artifact.path -Destination $path
    }
    # Hold a no-write/no-delete handle across hash validation and launch to close the cache replacement race.
    $lock = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        [void](Assert-Artifact $path $Package)
        switch ($Package.installMethod) {
            'miniforge-silent' {
                if ($MiniforgeDirectory -notmatch '^[A-Za-z]:\\[A-Za-z0-9_\\.-]+$' -or (Test-Path -LiteralPath $MiniforgeDirectory)) { throw 'Miniforge needs a new absolute path without spaces/special characters; existing directories are preserved.' }
                if (Test-WorkstationAdministrator) { throw 'Install JustMe Miniforge from a non-elevated PowerShell, then rerun elevated for other packages.' }
                $process = Start-Process -FilePath $path -ArgumentList "/InstallationType=JustMe /AddToPath=0 /RegisterPython=0 /S /D=$MiniforgeDirectory" -Wait -PassThru
                if ($process.ExitCode -eq 0 -and (Test-Path -LiteralPath (Join-Path $MiniforgeDirectory 'python.exe')) -and (Test-Path -LiteralPath (Join-Path $MiniforgeDirectory 'Scripts/conda.exe'))) {
                    @{version=$Package.version;sha256=$Package.integrity.sha256;pythonHash=(Get-FileHash -LiteralPath (Join-Path $MiniforgeDirectory 'python.exe') -Algorithm SHA256).Hash;condaHash=(Get-FileHash -LiteralPath (Join-Path $MiniforgeDirectory 'Scripts/conda.exe') -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $MiniforgeDirectory '.modeling-workstation-install.json') -Encoding UTF8
                }
            }
            'msi-interactive' {
                Write-Host "$($Package.product) installer requires interaction. Preserve any existing software; do not choose removal/upgrade."
                $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/msiexec.exe') -ArgumentList "/i `"$path`" /norestart" -Wait -PassThru
            }
            'hec-interactive' {
                Write-Host 'HEC installer requires interaction. Keep its version-specific default installation directory.'
                $process = Start-Process -FilePath $path -Wait -PassThru
            }
        }
        return [int]$process.ExitCode
    } finally { $lock.Dispose() }
}
function Get-WorkstationExitCode {
    param([string]$Mode,[object[]]$Results)
    if ($Mode -eq 'Plan') { return 0 }
    if (@($Results | Where-Object { $_.status -eq 'failed' }).Count) { return 1 }
    if ($Mode -eq 'Install' -and @($Results | Where-Object { $_.status -notin @('installed-detected','installed-verified','unavailable') }).Count) { return 1 }
    return 0
}
function Assert-WorkstationInstallPlatform {
    if (!(Test-WorkstationWindows) -or ![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or [Environment]::OSVersion.Version.Build -lt 22000) {
        throw 'Installation requires Windows 11 x64 and a 64-bit PowerShell process.'
    }
}
function Invoke-Workstation {
    param([string]$Mode,[string]$ManifestPath,[string]$CacheDirectory,[string]$ReportDirectory,[string]$MiniforgeDirectory,
        [ValidateSet('Miniforge','QGIS','HEC-RAS','HEC-HMS','Chrome')][string[]]$Products = @('Miniforge','QGIS','HEC-RAS','HEC-HMS','Chrome'))
    $manifest = Read-WorkstationManifest $ManifestPath
    if (!$Products -or !$Products.Count) { throw 'Select at least one product.' }
    foreach ($product in $Products) {
        if (!@($manifest.packages | Where-Object { $_.product -eq $product -and $_.stability -eq 'stable' }).Count) { throw "Requested product absent from reviewed catalog: $product" }
    }
    foreach ($directory in @($CacheDirectory,$ReportDirectory,$MiniforgeDirectory)) {
        if ([string]::IsNullOrWhiteSpace($directory) -or $directory -match '[\r\n"]' -or ![IO.Path]::IsPathRooted($directory)) { throw 'Use nonempty absolute paths without quotes or newlines.' }
    }
    if ($Mode -eq 'Install') {
        Assert-WorkstationInstallPlatform
    }
    Write-Host "Reviewed catalog: $($manifest.catalogVerifiedOn). Newest means newest in this dated catalog; review vendor pages for updates."
    $results = @()
    foreach ($p in @(Select-WorkstationPackage $manifest.packages | Where-Object { $_.product -in $Products })) {
        $r = [pscustomobject]@{id=$p.id;product=$p.product;version=$p.version;major=$p.major;status='planned';runtimeReadiness='untested';message=$p.notes;sourceUrl=$p.url;requiresAdmin=$p.requiresAdmin;installMethod=$p.installMethod;artifact=$null;exitCode=$null;rebootRequired=$false}
        if ($p.product -eq 'HEC-RAS' -and $p.major -eq 6 -and (Test-WorkstationWindows) -and !(Get-Command wmic.exe -ErrorAction SilentlyContinue)) {
            $r.runtimeReadiness='blocked'; $r.message += ' WMIC missing: https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/wmic-window-11-os-issue'
        }
        try {
            $detected = Get-InstalledPackage $p $MiniforgeDirectory
            $r.message += " $($detected.message)"
            if ($detected.state -eq 'exact') { $r.status='installed-detected' }
            elseif ($Mode -eq 'Plan') { if ($p.installMethod -eq 'manual' -or $detected.state -eq 'conflict') { $r.status='manual-required' } }
            else {
                $r.artifact = Get-PackageArtifact $p $CacheDirectory
                $r.status='downloaded'
                if ($Mode -eq 'Install') {
                    if ($p.installMethod -eq 'manual' -or $detected.state -eq 'conflict') { $r.status='manual-required' }
                    else {
                        $r.exitCode = Install-WorkstationPackage $p $r.artifact $MiniforgeDirectory
                        $r.rebootRequired = $r.exitCode -in @(3010,1641)
                        if ($r.exitCode -notin @(0,3010,1641)) { throw "Installer returned $($r.exitCode)." }
                        if ((Get-InstalledPackage $p $MiniforgeDirectory).state -ne 'exact') { throw 'Installer ended but exact installed version could not be verified. Inspect installation manually.' }
                        $r.status='installed-verified'
                    }
                }
            }
        } catch { $r.status='failed'; $r.message += " $($_.Exception.Message)" }
        $results += $r
        Write-Host "$($r.product) $($r.version): $($r.status) - $($r.message)"
        if ($Mode -eq 'Plan') { Write-Host "  Source: $($r.sourceUrl); method: $($r.installMethod); administrator: $($r.requiresAdmin)" }
    }
    foreach ($missing in @($manifest.unavailableFamilies | Where-Object { $_.product -in $Products })) {
        Write-Host "$($missing.product) $($missing.major).x: unavailable (informational) - $($missing.reason)"
        $results += [pscustomobject]@{id="$($missing.product)-$($missing.major)-unavailable";product=$missing.product;version=$null;major=$missing.major;status='unavailable';runtimeReadiness='untested';message=$missing.reason}
    }
    $report = [pscustomobject]@{schemaVersion=1;generatedAt=[DateTime]::UtcNow.ToString('o');mode=$Mode;requestedProducts=$Products;catalogVerifiedOn=$manifest.catalogVerifiedOn;packages=$results;exitCode=(Get-WorkstationExitCode $Mode $results)}
    [void](New-Item -ItemType Directory -Path $ReportDirectory -Force)
    $reportPath = Join-Path $ReportDirectory ("workstation-{0}-{1}-{2}.json" -f $Mode,[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'),[guid]::NewGuid().ToString('N'))
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Report: $reportPath"
    return $report
}
if ($MyInvocation.InvocationName -ne '.') {
    try { $report = Invoke-Workstation -Mode $Mode -ManifestPath $ManifestPath -CacheDirectory $CacheDirectory -ReportDirectory $ReportDirectory -MiniforgeDirectory $MiniforgeDirectory -Products $Products; exit $report.exitCode }
    catch { Write-Error $_ -ErrorAction Continue; exit 2 }
}
