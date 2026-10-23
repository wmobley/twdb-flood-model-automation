# Windows modeling workstation setup

Use `scripts/windows/Install-ModelingWorkstation.ps1` with its accompanying
`configs/windows/modeling-workstation.json` catalog. Copy the repository to the
Windows machine; the script is not a standalone file without its catalog.

The script accepts Windows 11 or Windows Server 2022 with Desktop Experience
on an Intel/AMD 64-bit machine, using a 64-bit PowerShell process. The catalog selects one
stable version per HEC major family, Miniforge (which includes Python and Conda),
and QGIS long-term release. It excludes previews and beta releases. “Latest” means
the latest in the dated, reviewed catalog, not a live release lookup.

## Windows Server 2022

Server 2022 is recognized by Windows kernel version 10.0, build 20348,
server/domain-controller product type, and Desktop Experience installation type.
Server Core and other Windows Server releases are rejected. OS identity comes from
`Win32_OperatingSystem` through CIM rather than the PowerShell host's reported OS
version. Detection failures stop installation before downloads or installer launches.

Accepting the OS does not certify the applications. Install mode emits a server
warning and includes untested compatibility in each package report message.
Legacy packages require explicit attended opt-in to launch. Verify application startup and representative
model computations on a disposable Server 2022 VM before using it for modeling.
[Google's Chrome requirements](https://support.google.com/chrome/a/answer/7100626?hl=en)
include Windows Server 2016 and later. The reviewed
[QGIS installation guide](https://www.qgis.org/resources/installation-guide/) and
[HEC-RAS downloads](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
do not establish Server 2022 compatibility for every cataloged package; those
application/runtime checks remain unverified. Miniforge still requires a normal,
non-administrator shell, while Chrome, QGIS and HEC require Administrator PowerShell.
WinGet is not required.

## Run the script

Open PowerShell in the repository root and preview first:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1
```

Download the selected installers without launching them:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1 -Mode DownloadOnly
```

Install Miniforge from a **normal, non-administrator** PowerShell window:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1 -Mode Install -Products Miniforge
```

Then open PowerShell **as Administrator**, return to the repository root, and run:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1 -Mode Install -Products QGIS,HEC-RAS,HEC-HMS,Chrome
```

Miniforge installs for the current user, without global Python registration or
PATH changes. Its default directory is `$HOME\miniforge3`; if your Windows user
path contains spaces or special characters, supply a new, writable absolute path
without spaces, for example `-MiniforgeDirectory C:\Modeling\miniforge3`.
Use the **Miniforge Prompt** from the Start menu to run `python` and `conda` after
installation. An existing target directory is preserved rather than upgraded.

Use the same Windows account that will use Miniforge. QGIS and HEC setup dialogs require
your interaction, including acceptance of the vendor terms. Keep each HEC
version in its own installation directory. Do not select an existing version's
directory. Installation can take time and requires internet access and free disk
space for downloads and installed applications.

Follow your organization's PowerShell execution policy if it blocks the script.
The installer does not change that policy, automatically reboot, or enable WMIC.

Use `-Products` to limit any mode to a product subset. Override output locations
with `-CacheDirectory` and `-ReportDirectory`; both require absolute paths. Defaults
are `modeling-workstation-cache` and `modeling-workstation-reports` beneath the
current process's temporary directory (`[IO.Path]::GetTempPath()`). Use the same
explicit cache path between passes if elevation changes your temporary directory.
The default catalog path is relative to the script; `-ManifestPath` overrides it.

## Google Chrome

Chrome is included by default and uses Google's official 64-bit enterprise MSI;
WinGet is not required. To install only Chrome, run in Administrator PowerShell:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1 -Mode Install -Products Chrome
```

The MSI opens an interactive setup. Existing Chrome versions, including per-user
uninstall registrations, are preserved; different or unknown versions require manual
review. Chrome automatic updates remain enabled. An update during installation
can cause exact-version verification to report incomplete installation.

The catalog pins SHA256 from a specific Microsoft WinGet manifest commit, an
independent published checksum rather than a Google-published checksum. Google's
stable MSI URL changes over time: changed bytes fail validation until the catalog
is reviewed and updated. Never replace the pin using only a local download hash.
The report's `publisherChecksum` field means the configured checksum matched;
consult catalog `integrity.provenance` for its source, which for Chrome is Microsoft.

## Historical HEC coverage

The reviewed catalog covers HEC-RAS 2.2, 3.1.3, 4.1, 5.0.7, 6.6, and 7.0.2, and
HEC-HMS 2.2.2, 3.5, and 4.14. Neither reviewed official catalog lists 1.x; its
absence is informational and does not itself cause installation failure.

Historical downloads may lack publisher checksums, supported installer behavior,
or Windows 11 compatibility evidence. By default, such entries remain manual-required rather
than being silently omitted or reported as installed. Review their report messages
and vendor instructions. An isolated older Windows VM may be necessary; this
script does not create one.

In this catalog, automatic script launch is enabled for Miniforge, QGIS, Chrome, RAS 7.0.2,
and HMS 4.14. The remaining HEC versions are downloaded for manual review and
installation unless `-AllowLegacyInstallers` explicitly enables attended setup. The script records their locally calculated hashes but does not
treat them as publisher-verified. Install mode therefore returns an incomplete
result until those historical versions are installed and detected on a rerun.

HEC-RAS 6.6 computation depends on WMIC. If it is absent, installation may succeed
while computation remains blocked. Follow the [official HEC guidance](https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/wmic-window-11-os-issue)
for the manual mitigation. A successful installation or version detection does
not establish that a model can compute. Validate representative models separately.

## Catalog maintenance and recovery

The JSON report records per-package installation status, installer exit codes,
reboot requests, artifact provenance, and runtime readiness. Exit code `0` means
the requested mode completed, `1` means a failed download or incomplete installation,
and `2` means a fatal validation error. A valid preview can succeed while showing
manual work. Download-only success means artifacts were obtained, not installed.
Installation readiness and computation readiness are separate; runtime readiness
remains untested until tested outside this script.

Maintain the JSON catalog alongside the script. Check the official product page,
select the newest stable release per numeric major family, and record the exact
artifact URL and publisher checksum source. Verify installer instructions,
architecture, detection rules, and coexistence behavior before allowing script
execution. A checksum calculated after downloading an artifact is a local audit
fingerprint, not independent proof of publisher authenticity.

- [HEC-RAS downloads](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
- [HEC-HMS downloads](https://www.hec.usace.army.mil/software/hec-hms/downloads.aspx)
- [QGIS downloads](https://qgis.org/download/)
- [Miniforge installation instructions](https://github.com/conda-forge/miniforge)

Preserve the installation report when troubleshooting. Fix the reported cause and
rerun detection; do not remove existing software to force a match. Installation
is not transactional. If rollback is necessary, use the vendor's supported
uninstaller for the newly installed package or restore a pre-install VM snapshot.
Do not commit downloaded installers or machine-specific reports.

## Validation limits

PowerShell parsing and mocked tests can run on macOS, but they do not validate
Windows installer execution. Before workstation deployment, test on a disposable
Windows 11 and Server 2022 Desktop Experience VMs: verify exact installed versions, side-by-side behavior, reruns,
Python and Conda commands, QGIS startup, and representative HEC computations.


Run focused tests with Pester 5 (install Pester according to your organization's
policy if it is not available):

```powershell
Invoke-Pester -Path .\tests\windows\Install-ModelingWorkstation.Tests.ps1
```

Current verification: all 57 mocked Pester tests passed on macOS, including Chrome
and Server 2022 platform cases. Windows PowerShell 5.1 compatibility is targeted but has not been
executed on Windows. No actual application installations were tested in this session.

## Attended legacy HEC setup

To try older HEC installers, run as Administrator and attend each setup dialog:

```powershell
.\scripts\windows\Install-ModelingWorkstation.ps1 -Mode Install -Products HEC-RAS,HEC-HMS -AllowLegacyInstallers
```

This explicitly opts into launching catalog entries marked manual. Without the
switch they remain download/manual-review only. Plan and DownloadOnly never
launch installers, including with the switch. Existing detected conflicts remain
manual-required. Preserve each version's installation directory in setup dialogs.

Some legacy packages lack an independently published checksum or valid signature.
Attending setup does not establish authenticity or Server compatibility. The report
records opt-in, original method, artifact hash/signature and installation outcome.
A successful exit must still pass version detection; model computation stays untested.
