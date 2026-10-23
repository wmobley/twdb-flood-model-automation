# Windows modeling workstation installer

## Status

Implemented — script, reviewed catalog, tests, and setup guide created on 2026-10-22. PowerShell parsing, real-catalog Plan smoke check, and 31 mocked Pester tests passed on macOS PowerShell 7.4.6. Actual Windows installation, ACL behavior, and computation remain unvalidated.

## Objective

Create a PowerShell provisioning script for Windows 11 x64 that installs Miniforge (providing Python and Conda), QGIS long-term release, and the newest stable HEC-RAS and HEC-HMS version available from official sources in every numeric major family. Report unavailable families and compatibility limits explicitly.

## User need

- **Primary user:** The requester preparing a Windows modeling machine; operator expertise is unspecified.
- **Secondary users:** None identified.
- **Job-to-be-done:** Prepare a Windows machine with Python/Conda, QGIS LTR, and historical major families of both HEC applications.
- **Current pain:** The repository has no provisioning script; the user requested one script to install the required software. The existing workstation setup process is unspecified.
- **Definition of success:** The requested software is installed where supported; a report identifies exact versions, missing families, pending manual steps, and runtime readiness without claiming unsupported legacy applications work on Windows 11.

## Current code/system summary

README.md describes an initial repository scaffold. docs/architecture.md anticipates a Windows execution pool but contains no workstation provisioning implementation. Existing executable code is a Python YAML run configuration loader under load_balancer/, tested with pytest. configs/ holds local configuration; technical guides are in docs/ and design records in docs/design/. There is no existing scripts/ directory or PowerShell testing infrastructure. Read-only .wolf/ context agrees with this scaffold; its anatomy index predates this work. No DSO service, port, authentication, or integration changes are proposed.

## Proposed design

### Entry point and operating modes

**Proposed:** Implement a Windows PowerShell 5.1-compatible entry point at scripts/windows/Install-ModelingWorkstation.ps1. Default to a plan showing selected packages, detection results, download sources, required privilege, and manual actions. Explicit DownloadOnly downloads into a user-selected cache without executing installers; explicit Install performs validated installation actions. Reject conflicting modes and invalid paths before side effects. Non-Windows systems may inspect the manifest but cannot install software; do not execute installers on this Mac.

**Proposed:** Use current-user Miniforge without registering Python globally or modifying global PATH. Use documented installer behavior only, detect required elevation per application, and explain relaunch requirements rather than silently elevating. Do not change machine execution policy, disable signature checks, enable deprecated Windows components, or automatically reboot.

### Version catalog and selection

Use a checked-in JSON manifest under configs/windows/ with explicit source page, direct artifact URL, product, numeric version, major family, architecture, stability, retrieval/verification date, install method, detection rule, and integrity provenance. Keep numeric components as integers for comparison (for example, 4.14 exceeds 4.9); exclude previews, beta releases, and development builds. Select the highest stable version per major, not the lexicographically greatest filename. RAS 7.0.2 belongs to family 7, irrespective of marketing labels.

Official catalogs verified by the parent planning agent on 2026-10-22 list RAS 2.2, 3.1.3, 4.1, 5.0.7, 6.6, and 7.0.2; HMS 2.2.2, 3.5, and 4.14. Neither page lists a 1.x download. Report 1.x as unavailable from reviewed official sources and exclude it from required installation coverage, as accepted by the user; do not invent a URL or substitute a third-party mirror. QGIS currently labels 3.44.15 as LTR. These are dated catalog observations, not permanent latest-version guarantees.

**Proposed:** Resolve latest versions through maintainer-reviewed manifest updates, rather than brittle runtime HTML scraping. Display catalog verification date and freshness limitation prominently in every plan and document refresh steps. “Newest stable” means newest in that dated reviewed catalog. Runtime discovery may report a newer release but never authorizes execution without a reviewed manifest record and validated installation adapter. Before implementation acceptance, recheck official pages, artifact availability, architectures, installer instructions, and any redistribution restrictions; record unknowns rather than invent metadata.

Sources:

- [HEC-RAS official current and previous downloads](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
- [HEC-HMS official downloads](https://www.hec.usace.army.mil/software/hec-hms/downloads.aspx)
- [QGIS official downloads and LTR selection](https://qgis.org/download/)
- [Miniforge official installation instructions](https://github.com/conda-forge/miniforge)

### Download and integrity boundary

Fetch only listed official HTTPS artifacts; validate each redirect hop against the reviewed allowlist before following it. Never execute server-returned commands. Download to a temporary filename, validate expected artifact characteristics, then move into a version-specific cache. Preserve source URL, final URL, timestamp, size, SHA-256, publisher checksum status, and signature result where applicable. A locally calculated checksum is an audit fingerprint, not proof of publisher authenticity. Compare publisher checksums when provided; fail on mismatch. Publisher authenticity policy must be established for each artifact before marking it eligible for any script-launched execution, including interactive installers. Changed bytes at the same URL invalidate the expected artifact approval; record the discrepancy and require renewed review rather than merely updating the local audit hash. Revalidate the expected hash before every cache reuse and every launch. For elevated execution, stage verified bytes in an appropriately protected location, prevent unprivileged modification, and verify the staged artifact immediately before launch; never elevate execution directly from a shared writable cache. Reject partial files and unexpected HTML/error responses.

### Install and detection boundary

Miniforge documents silent JustMe installation with /RegisterPython=0, /S, and /D; verify exact argument ordering and supported path constraints against the selected release. Do not reuse these flags for HEC or QGIS. Silent install switches for those products remain unvalidated. Implementation includes researching and validating supported installation methods for QGIS and each selected RAS/HMS artifact, using documented unattended switches where supported or explicit interactive installer execution where needed. The deliverable must install supported applications rather than primarily downloading them. **Proposed:** Install mode may launch validated interactive installers, identify user interaction before starting, wait for completion, and verify the installed version. Only unverified or incompatible legacy installers remain manual-required, with the verified artifact and official instructions retained. Do not treat unknown silent flags as grounds to omit investigation of an interactive installation path.

Detect exact installed versions using reliable registry/file metadata and product-specific checks, including 32-bit legacy installations on x64 Windows. Preserve existing versions and user environments; do not uninstall, overwrite, or downgrade to satisfy selection. A matching installation is skipped. Unknown detection or same-product conflicts require manual review. Do not assume different major families can coexist: validate installation directories and upgrade/overwrite behavior before enabling any script-launched action, including interactive installers. Unknown overwrite or coexistence behavior remains manual-required. Bundled HEC runtimes are product dependencies, not replacements for the user's Miniforge Python.

HEC documents a [Windows 11 WMIC computation issue](https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/wmic-window-11-os-issue) affecting RAS 6.0–6.6. Report the missing dependency and link the official manual mitigation; do not automatically install WMIC or enable optional/deprecated OS features. GUI installation alone does not prove the compute engine works. Older RAS/HMS families may need manual installation or an older isolated Windows environment; never claim Windows 11 support merely because the installer launches.

### Results and completion

**Proposed:** Emit a readable summary plus JSON report in a user-selected output directory. Record each requested family as installed-detected, installed-verified, downloaded, manual-required, unavailable, incompatible, or failed; track runtime readiness separately as verified, blocked, or untested. Record exit codes/reboot requirements and preserve successful prior steps when one package fails. Absent 1.x is a distinct unavailable-family coverage result based on reviewed sources, not a permanent claim that it can never be obtained. Unavailable 1.x alone does not cause a failure exit code. Install mode returns nonzero for incomplete required installation; download mode reports missing families distinctly; plan mode succeeds if planning is valid even when gaps are disclosed. Finalize exact exit-code mapping during implementation without conflating partial completion with success.

## Files likely affected

- scripts/windows/Install-ModelingWorkstation.ps1 — new entry point and installer orchestration.
- configs/windows/modeling-workstation.json — reviewed release and installer metadata.
- tests/windows/Install-ModelingWorkstation.Tests.ps1 — focused PowerShell tests.
- docs/windows-workstation-setup.md — operation, catalog maintenance, manual legacy steps, limitations.
- README.md — setup-guide link; configs/README.md — manifest purpose.
- .gitignore — local downloaded installers, logs, and reports only if defaults create repository-local output.
- This spec — approval and implementation decisions. No .wolf/ edits.

## API/schema changes

No existing service API or run-configuration schema changes. The new local JSON manifest needs a schemaVersion and validation for supported products, version components, official HTTPS URLs, installation/detection methods, and integrity metadata. Installation methods are enumerated adapters with validated arguments treated as data. Manifest fields cannot contain arbitrary PowerShell expressions or shell commands; never use Invoke-Expression. Installation eligibility must not default to true when fields are absent. Reports include a schema version for later tooling; no credentials are required or recorded.

## Data flow

Validated arguments → validated manifest → numeric major selection → installed-version and platform inspection → plan → optional official downloads and integrity checks → explicitly requested eligible installs → exact-version detection → separate runtime-readiness assessment → console and JSON reports. Manual-required and unavailable entries remain visible throughout.

## Risks and tradeoffs

- Official catalogs omit 1.x; the user accepts its absence, so it is informational rather than a completion blocker.
- Legacy installers, architectures, co-installation behavior, and unattended switches are unverified; manual fallback is required until evidence supports automation.
- RAS 6.6 can be installed yet unable to compute on Windows 11 without WMIC. Report installation and computation separately.
- A reviewed catalog is reproducible but becomes stale. Its verification date and refresh procedure must be visible.
- Publisher checksums/signatures may be unavailable for historical downloads. Local hashing preserves provenance but does not resolve authenticity; unvalidated artifacts must remain manual-required.
- Installation is not transactional. Preserve installed software and document package-by-package recovery rather than promising automatic rollback.

## Alternatives considered

- A separate python.org installation: user chose Miniforge to supply both Python and Conda, avoiding another interpreter installation.
- Every minor release: user chose one newest stable version per numeric major.
- QGIS latest feature release: user chose LTR.
- **Proposed:** Runtime scraping or a package-manager-only solution is deferred because historical family coverage and installer behavior still require official-source validation; a reviewed manifest makes those limits inspectable.
- **Proposed:** An older Windows VM remains a documented manual option for incompatible historical applications; VM provisioning is outside this script.

## Test plan

Run PowerShell parsing and focused Pester tests with downloads, registry inspection, and process launching mocked. Cover numeric ordering, preview exclusion, one selection per major, missing 1.x without failure, manifest validation, platform rejection, existing-version preservation, path quoting, integrity mismatch, partial downloads, HTML responses, process failure, reboot-required results, manual fallback, incomplete-install exit behavior, cache tampering, disallowed redirects, malicious manifest arguments, and protected elevated staging. Verify plan mode launches no installers and DownloadOnly never executes artifacts.

On a disposable Windows 11 x64 VM, validate actual approved artifacts and documented switches one package at a time; confirm installed versions, coexistence, no unexpected PATH/registration changes, and rerun behavior. Test Miniforge Python/Conda and QGIS launch/version checks. Use HEC launch/version checks and representative compute smoke tests before reporting runtime-ready; missing models or legacy Windows incompatibility must remain explicitly untested/blocked. Availability of a Windows 11 VM is currently unknown. If none is available, perform mocked/source validation only and explicitly report provisioning as not fully validated; do not imply Windows installation or compatibility testing passed. Unit tests on macOS cannot establish Windows installer compatibility. Existing pytest tests remain unchanged unless shared project behavior changes.

## Documentation plan

Explain requirements, privilege, modes, examples, manifest verification date/refresh, cache integrity distinctions, report statuses, manual installation, WMIC guidance, coexistence limitations, and recovery. Clearly identify unsupported or untested families and that no models, Conda analysis environments, TACC services, or HEC compute automation are provisioned.

## Rollout/rollback plan

**Proposed:** Review the spec, approve implementation, test plan/download paths, then validate install mode on a disposable Windows VM before use on a workstation. Take a VM snapshot before installer validation. Keep local artifacts/reports for diagnosis. If a package fails, stop its dependent actions and report remediation; uninstall only the newly installed product through its supported vendor procedure when explicitly requested. No automatic removal of preexisting software or workstation-wide rollback.

## Open questions

1. Operational choices approved together on 2026-10-22; artifact-specific validation remains required.
2. Which historical installers provide trustworthy checksums/signatures, reliable detection, supported unattended flags, and safe side-by-side behavior? These are implementation validation gates, not settled facts.
3. Can all listed legacy versions install and compute on Windows 11? Until tested, they remain manual-required or runtime-untested.

## Decisions

### 2026-10-22 — Confirmed target and version scope

- **Decision:** Windows 11 x64; Miniforge supplies Python/Conda; QGIS LTR; one newest stable release per numeric major family for RAS and HMS.
- **Reason:** User explicitly selected these defaults and family granularity.
- **Alternatives rejected:** Every minor family, separate Python installation, and QGIS feature-release default.
- **User feedback:** “One per major family (1.x, 2.x, etc.)” and “Yes, use those defaults.”
- **Impact on implementation:** Manifest selection is by major; no separate Python installer.

### 2026-10-22 — Review boundary

- **Decision:** This document remains In Review; no installer source or external installation has been performed.
- **Reason:** Repository requires approved design before major provisioning implementation.
- **Alternatives rejected:** Immediate unreviewed implementation.
- **User feedback:** Requirements confirmed; implementation approval not yet supplied.
- **Impact on implementation:** Review and approve the proposed choices before source edits.

### 2026-10-22 — Missing 1.x accepted

- **Decision:** An unavailable official 1.x installer is acceptable for either HEC product.
- **Reason:** User explicitly accepted its absence.
- **Alternatives rejected:** Requiring 1.x coverage or failing installation solely because it is unavailable.
- **User feedback:** “IF there isn't a 1.x thats fine”.
- **Impact on implementation:** Report unavailable 1.x informationally; exclude it from required coverage and failure exit codes. Other installation failures remain failures. This scope clarification does not record approval of the entire design.

### 2026-10-22 — Implementation approved

- **Decision:** Implement the reviewed plan.
- **Reason:** User explicitly authorized proceeding.
- **Alternatives rejected:** Further design-only work.
- **User feedback:** “ok, do it”.
- **Impact on implementation:** Source, tests, and documentation edits may proceed; no installation or remote writes in this session.

### 2026-10-22 — Implementation and validation results

- **Decision:** Implemented Plan/DownloadOnly/Install, product filtering, JSON provenance reports, pinned executable integrity checks, and protected administrative staging.
- **Reason:** Separate current-user Miniforge installation from administrative application setup while preserving existing software.
- **Alternatives rejected:** Automatic elevation and unverified historical installer execution.
- **User feedback:** Implementation authorized by “ok, do it”.
- **Impact on implementation:** Use a non-elevated Miniforge pass and an elevated QGIS/HEC pass. Script launch is enabled for Miniforge, QGIS, RAS 7.0.2, and HMS 4.14. Other historical HEC releases remain manual-required because publisher integrity or installation evidence is incomplete. This is the approved fallback, not a claim that all historical releases install automatically.
- **Validation:** 31 Pester tests passed; script parsing and real-catalog Plan passed. QA reviewed ownership checks, version normalization, two-pass documentation, and mocked installation behavior. Windows installer/ACL/registry integration, redirect-chain integration, Miniforge receipt runtime, application startup, and HEC compute smoke tests still require Windows validation. No remote write or actual application installation performed.

## User feedback / decisions

Requirements and proposed operational choices approved on 2026-10-22 (“ok, do it”). Installer behavior and compatibility claims require validation.
