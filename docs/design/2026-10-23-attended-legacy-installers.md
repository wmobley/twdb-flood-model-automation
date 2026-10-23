# Attended legacy HEC installers

## Status

Implemented

## Objective

Allow explicitly requested attended legacy HEC installation.

## User need

User will attend setup dialogs and accepts trying older installers.

## Current code/system summary

Manual catalog entries download but cannot launch. Existing staged interactive adapter validates bytes and preserves conflicts.

## Proposed design

Add -AllowLegacyInstallers to entry point and orchestration. Permit manual HEC EXEs only with this opt-in, using existing protected staging and interactive launch. Keep manifest validation and pinned mismatches enforced. Report missing independent checksum and untested runtime.

## Files likely affected

scripts/windows/Install-ModelingWorkstation.ps1; tests/windows/Install-ModelingWorkstation.Tests.ps1; docs/windows-workstation-setup.md.

## API/schema changes

Optional PowerShell switch; no catalog schema change.

## Data flow

Official allowlisted download → audit → conflict check → opt-in launch → exact installed-version detection.

## Risks and tradeoffs

Legacy unsigned artifacts may lack independent authenticity proof. Attended execution accepts this uncertainty; UI presence does not prove authenticity or compatibility. Installation can fail and is not transactional.

## Alternatives considered

Keep manual-only: rejected by user request. Enable by default: rejected to preserve default behavior.

## Test plan

Pester default rejection, opt-in launch, conflict protection, Plan/DownloadOnly no launch, existing suite.

## Documentation plan

Document opt-in command and provenance/compatibility limitations.

## Rollout/rollback plan

Local source changes only. Omit switch to restore previous behavior; revert source to remove option. No actual installations or external writes.

## Open questions

None for approved scope.

## Decisions

2026-10-23: User approved trying attended legacy installers after explicit opt-in was proposed. Preserve all other execution checks.

## User feedback / decisions

“Thats ok, IF i'm minding them we can install them any way”.

Validation: 57 mocked Pester tests passed on macOS. Actual Windows legacy installation remains untested. No deviations from approved scope.

### 2026-10-23 — Assume coexistence across legacy major versions

User approved: “Lets assume the can coexist”. With legacy opt-in, allow manual
HEC packages alongside only identifiable different-major installations. Same-major
and unidentified versions stay conflicts. Record assumed coexistence in detection
messages; do not claim vendor validation. Add registry tests and update guidance.

Coexistence update validation: all 62 mocked Pester tests passed. Same-major and unknown conflicts retained. Actual Windows execution remains untested.
