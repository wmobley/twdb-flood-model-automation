BeforeAll {
    . "$PSScriptRoot/../../scripts/windows/Install-ModelingWorkstation.ps1"
    $catalog = (Resolve-Path "$PSScriptRoot/../../configs/windows/modeling-workstation.json").Path
    function New-TestExecutable($Path) {
        $bytes = New-Object byte[] 2048
        $bytes[0] = 0x4d; $bytes[1] = 0x5a
        [IO.File]::WriteAllBytes($Path, $bytes)
    }
}

Describe 'Reviewed catalog and selection' {
    It 'accepts the checked-in catalog and selects each available HEC major once' {
        $m = Read-WorkstationManifest $catalog
        $selected = @(Select-WorkstationPackage $m.packages)
        @($selected | Where-Object product -EQ 'HEC-RAS').Count | Should -Be 6
        @($selected | Where-Object product -EQ 'HEC-HMS').Count | Should -Be 3
        @($selected | Group-Object product,major | Where-Object Count -GT 1).Count | Should -Be 0
    }
    It 'selects the pinned Chrome MSI from the approved host' {
        $chrome = @(Select-WorkstationPackage (Read-WorkstationManifest $catalog).packages | Where-Object product -EQ Chrome)
        $chrome.Count | Should -Be 1
        $chrome[0].installMethod | Should -Be 'msi-interactive'
        $chrome[0].requiresAdmin | Should -BeTrue
        $chrome[0].allowedHosts | Should -Contain 'dl.google.com'
        $chrome[0].integrity.sha256 | Should -Match '^[a-f0-9]{64}$'
    }
    It 'compares numeric versions and excludes newer previews' {
        $packages = @('4.9','4.14','4.99') | ForEach-Object {
            [pscustomobject]@{product='HEC-HMS';major=4;version=$_;stability=$(if ($_ -eq '4.99') {'preview'} else {'stable'})}
        }
        (Select-WorkstationPackage $packages).version | Should -Be '4.14'
    }
    It 'rejects arbitrary manifest commands' {
        $m = Get-Content $catalog -Raw | ConvertFrom-Json
        $m.packages[0] | Add-Member NoteProperty arguments 'Invoke-Expression evil'
        $path = Join-Path $TestDrive 'commands.json'
        $m | ConvertTo-Json -Depth 15 | Set-Content $path
        { Read-WorkstationManifest $path } | Should -Throw '*arguments*'
    }
    It 'rejects executable packages with no pinned checksum' {
        $m = Get-Content $catalog -Raw | ConvertFrom-Json
        $p = $m.packages | Where-Object installMethod -NE manual | Select-Object -First 1
        $p.integrity.sha256 = $null
        $path = Join-Path $TestDrive 'unpinned.json'
        $m | ConvertTo-Json -Depth 15 | Set-Content $path
        { Read-WorkstationManifest $path } | Should -Throw '*pinned*'
    }
    It 'rejects insecure and off-allowlist redirect destinations' -ForEach @(
        @{url='http://github.com/file.exe'}, @{url='https://evil.example/file.exe'},
        @{url='https://github.com:444/file.exe'}, @{url='https://user@github.com/file.exe'}
    ) {
        { Assert-AllowedUri -Uri $url -AllowedHosts @('github.com') } | Should -Throw
    }
}

Describe 'Artifact validation and cache reuse' {
    BeforeEach {
        Mock Test-WorkstationWindows { $false }
        $package = (Read-WorkstationManifest $catalog).packages[0]
        $artifact = Join-Path $TestDrive 'sample.exe'
        New-TestExecutable $artifact
    }
    It 'records a local fingerprint without claiming publisher authentication' {
        $audit = Assert-Artifact $artifact $package
        $audit.publisherChecksum | Should -Be 'unavailable-local-fingerprint-only'
        $audit.sha256 | Should -Match '^[a-f0-9]{64}$'
    }
    It 'rejects publisher checksum mismatches' {
        $package.integrity.sha256 = 'a' * 64
        { Assert-Artifact $artifact $package } | Should -Throw '*mismatch*'
    }
    It 'rejects partial files' {
        [IO.File]::WriteAllBytes($artifact, [byte[]]@(0x4d,0x5a))
        { Assert-Artifact $artifact $package } | Should -Throw '*Incomplete*'
    }
    It 'rejects HTML masquerading as an executable' {
        [IO.File]::WriteAllText($artifact, '<html>' + ('x' * 2048))
        { Assert-Artifact $artifact $package } | Should -Throw '*HTML*'
    }
    It 'rejects modified cached bytes even when no publisher hash exists' {
        $directory = Join-Path $TestDrive $package.id
        [void](New-Item -ItemType Directory $directory -Force)
        $path = Join-Path $directory $package.fileName
        New-TestExecutable $path
        @{sha256=('0' * 64);sourceUrl=$package.url} | ConvertTo-Json | Set-Content "$path.provenance.json"
        Mock Receive-OfficialArtifact { throw 'Network must not be used for cached artifacts' }
        { Get-PackageArtifact $package $TestDrive } | Should -Throw '*Cached bytes*'
        Should -Invoke Receive-OfficialArtifact -Times 0
    }
}

Describe 'Mode boundaries and completion' {
    BeforeEach {
        Mock Test-WorkstationWindows { $false }
        Mock Get-InstalledPackage { [pscustomobject]@{state='absent';message='test'} }
        Mock Get-PackageArtifact { [pscustomobject]@{path='mock.exe';sha256=('a' * 64)} }
        Mock Install-WorkstationPackage { throw 'No installer should launch' }
        $invoke = @{ManifestPath=$catalog;CacheDirectory=(Join-Path $TestDrive 'cache');ReportDirectory=(Join-Path $TestDrive 'reports');MiniforgeDirectory=(Join-Path $TestDrive 'conda')}
    }
    It 'plans without downloading or launching and reports missing 1.x informationally' {
        $report = Invoke-Workstation -Mode Plan @invoke
        $report.exitCode | Should -Be 0
        @($report.packages | Where-Object status -EQ unavailable).Count | Should -Be 2
        Should -Invoke Get-PackageArtifact -Times 0
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'downloads without launching' {
        $report = Invoke-Workstation -Mode DownloadOnly @invoke
        $report.exitCode | Should -Be 0
        Should -Invoke Get-PackageArtifact -Times 12
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'limits actions to explicitly selected products' {
        $report = Invoke-Workstation -Mode DownloadOnly -Products Miniforge @invoke
        @($report.packages | Where-Object product -NE Miniforge).Count | Should -Be 0
        Should -Invoke Get-PackageArtifact -Times 1
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'limits Chrome downloads to its MSI without launching' {
        $report = Invoke-Workstation -Mode DownloadOnly -Products Chrome @invoke
        $report.packages.Count | Should -Be 1
        $report.packages[0].product | Should -Be 'Chrome'
        Should -Invoke Get-PackageArtifact -Times 1
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'preserves conflicting Chrome installations without launching' {
        Mock Assert-WorkstationInstallPlatform {}
        Mock Get-InstalledPackage { [pscustomobject]@{state='conflict';message='Existing Chrome preserved'} }
        $report = Invoke-Workstation -Mode Install -Products Chrome @invoke
        $report.packages[0].status | Should -Be 'manual-required'
        $report.exitCode | Should -Be 1
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'preserves exact installations without downloading' {
        Mock Get-InstalledPackage { [pscustomobject]@{state='exact';message='already installed'} }
        $report = Invoke-Workstation -Mode DownloadOnly @invoke
        @($report.packages | Where-Object status -EQ installed-detected).Count | Should -Be 12
        Should -Invoke Get-PackageArtifact -Times 0
    }
    It 'rejects installation on a non-Windows host before package actions' {
        { Invoke-Workstation -Mode Install @invoke } | Should -Throw '*Windows 11*'
        Should -Invoke Get-PackageArtifact -Times 0
        Should -Invoke Install-WorkstationPackage -Times 0
    }
    It 'rejects relative paths before downloads' {
        $invoke.CacheDirectory = 'relative-cache'
        { Invoke-Workstation -Mode DownloadOnly @invoke } | Should -Throw '*absolute paths*'
        Should -Invoke Get-PackageArtifact -Times 0
    }
    It 'reports a download failure and continues other packages' {
        Mock Get-PackageArtifact { throw 'simulated network failure' }
        $report = Invoke-Workstation -Mode DownloadOnly @invoke
        $report.exitCode | Should -Be 1
        @($report.packages | Where-Object status -EQ failed).Count | Should -Be 12
    }
    It 'fails incomplete installation but accepts unavailable 1.x' {
        Get-WorkstationExitCode Install @([pscustomobject]@{status='manual-required'}) | Should -Be 1
        Get-WorkstationExitCode Install @([pscustomobject]@{status='installed-verified'},[pscustomobject]@{status='unavailable'}) | Should -Be 0
    }
    It 'verifies successful installs and records pending reboot separately' {
        Mock Assert-WorkstationInstallPlatform {}
        Mock Get-InstalledPackage {
            if ($script:launched) { [pscustomobject]@{state='exact';message='verified'} }
            else { [pscustomobject]@{state='absent';message='absent'} }
        }
        $script:launched = $false
        Mock Install-WorkstationPackage { $script:launched = $true; return 3010 }
        $report = Invoke-Workstation -Mode Install -Products QGIS @invoke
        $report.exitCode | Should -Be 0
        $report.packages[0].status | Should -Be installed-verified
        $report.packages[0].rebootRequired | Should -BeTrue
        $report.packages[0].runtimeReadiness | Should -Be untested
    }
    It 'fails if an installer succeeds without exact-version verification' {
        Mock Assert-WorkstationInstallPlatform {}
        Mock Install-WorkstationPackage { return 0 }
        $report = Invoke-Workstation -Mode Install -Products QGIS @invoke
        $report.exitCode | Should -Be 1
        $report.packages[0].status | Should -Be failed
    }
    It 'never launches for detected conflicts in Install mode' {
        Mock Assert-WorkstationInstallPlatform {}
        Mock Get-InstalledPackage { [pscustomobject]@{state='conflict';message='preserve existing'} }
        $report = Invoke-Workstation -Mode Install -Products QGIS @invoke
        $report.exitCode | Should -Be 1
        $report.packages[0].status | Should -Be manual-required
        Should -Invoke Install-WorkstationPackage -Times 0
    }
}

Describe 'Registry exact-version detection' {
    It 'detects exact Chrome and checks current-user registrations' {
        Mock Test-WorkstationWindows { $true }
        $package = (Read-WorkstationManifest $catalog).packages | Where-Object product -EQ Chrome
        Mock Get-ItemProperty { [pscustomobject]@{DisplayName='Google Chrome';DisplayVersion='156.0.8078.48'} }
        (Get-InstalledPackage $package 'C:\miniforge3').state | Should -Be exact
        Should -Invoke Get-ItemProperty -ParameterFilter { $Path -like 'HKCU:*' }
    }
    It 'preserves other or unidentified Chrome versions' -ForEach @(
        @{version='155.0.8000.1'}, @{version='157.0.8100.1'}, @{version='unknown'}
    ) {
        Mock Test-WorkstationWindows { $true }
        Mock Get-ItemProperty { [pscustomobject]@{DisplayName='Google Chrome';DisplayVersion=$version} }
        $package = (Read-WorkstationManifest $catalog).packages | Where-Object product -EQ Chrome
        (Get-InstalledPackage $package 'C:\miniforge3').state | Should -Be conflict
    }

    It 'accepts Windows trailing-zero version padding and inspects x86 registrations' {
        Mock Test-WorkstationWindows { $true }
        Mock Get-ItemProperty { [pscustomobject]@{DisplayName='HEC-RAS 7.0';DisplayVersion='7.0.2.0'} }
        $package = (Read-WorkstationManifest $catalog).packages | Where-Object { $_.product -eq 'HEC-RAS' -and $_.major -eq 7 }
        (Get-InstalledPackage $package 'C:\miniforge3').state | Should -Be exact
        Should -Invoke Get-ItemProperty -ParameterFilter { $Path -like '*WOW6432Node*' }
    }
    It 'preserves other installed versions as conflicts' {
        Mock Test-WorkstationWindows { $true }
        Mock Get-ItemProperty { [pscustomobject]@{DisplayName='HEC-RAS 7.0';DisplayVersion='7.0.1'} }
        $package = (Read-WorkstationManifest $catalog).packages | Where-Object { $_.product -eq 'HEC-RAS' -and $_.major -eq 7 }
        (Get-InstalledPackage $package 'C:\miniforge3').state | Should -Be conflict
    }
}

Describe 'Installer launch boundary' {
    BeforeEach {
        $package = (Read-WorkstationManifest $catalog).packages | Where-Object installMethod -EQ hec-interactive | Select-Object -First 1
        $artifactPath = Join-Path $TestDrive 'installer with spaces.exe'
        New-TestExecutable $artifactPath
        $artifact = [pscustomobject]@{path=$artifactPath}
        Mock Assert-Artifact { [pscustomobject]@{sha256=('a' * 64)} }
        Mock Test-WorkstationAdministrator { $true }
        Mock New-ProtectedInstallerStage { $TestDrive }
        Mock Start-Process { [pscustomobject]@{ExitCode=3010} }
    }
    It 'stages admin installers and revalidates staged bytes before launch' {
        Install-WorkstationPackage $package $artifact 'C:\miniforge3' | Should -Be 3010
        Should -Invoke New-ProtectedInstallerStage -Times 1
        Should -Invoke Assert-Artifact -Times 2
        Should -Invoke Start-Process -Times 1 -ParameterFilter {
            $FilePath -eq (Join-Path $TestDrive $package.fileName) -and $Wait -and $PassThru
        }
    }
    It 'returns failed installer codes for orchestration to report' {
        Mock Start-Process { [pscustomobject]@{ExitCode=1603} }
        Install-WorkstationPackage $package $artifact 'C:\miniforge3' | Should -Be 1603
    }
    It 'never automatically elevates' {
        Mock Test-WorkstationAdministrator { $false }
        { Install-WorkstationPackage $package $artifact 'C:\miniforge3' } | Should -Throw '*Administrator*'
        Should -Invoke Start-Process -Times 0
    }
    It 'refuses manual legacy installer execution' {
        $package.installMethod = 'manual'
        { Install-WorkstationPackage $package $artifact 'C:\miniforge3' } | Should -Throw '*Manual*'
        Should -Invoke Start-Process -Times 0
    }
    It 'does not launch when staged verification fails' {
        Mock Assert-Artifact { if ($Path -ne $artifactPath) { throw 'staged bytes changed' } }
        { Install-WorkstationPackage $package $artifact 'C:\miniforge3' } | Should -Throw '*staged bytes*'
        Should -Invoke Start-Process -Times 0
    }
}
