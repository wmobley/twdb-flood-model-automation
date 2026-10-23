# TWDB Flood Model Process Repository Scaffold

Status: Implemented

## Objective

Establish a simple GitHub repository scaffold for the TWDB Flood Model Process program. The scaffold will organize the core code pieces: model inputs, Jupyter notebooks, Deconstructed Notebooks, and a load balancer, together with a lightweight project record for plans, presentations, meetings, decisions, and deliverables.

The initial work is repository organization and project scaffolding. It does not include a working HEC-RAS/HEC-HMS runner, DYNAMO registration, TACC infrastructure provisioning, or GitHub repository creation.

## User need

**Primary user:** TWDB flood-model reviewers who need repeatable model runs and consistent geospatial/reviewer outputs. Their domain expertise is flood modeling and review; they should not need to understand worker-pool internals to use the repository's documented workflows.

**Secondary users:**

- TACC operators and technical staff who stage models, operate Windows workers, diagnose failed runs, and maintain service documentation.
- TACC developers who implement HEC-RAS/HEC-HMS execution, ETL transforms, dataset contracts, and reviewer views.
- Project managers and investigators who need traceable decisions, deliverables, testing evidence, and progress artifacts.

**Job-to-be-done:** Move from manually constrained desktop processing toward a repeatable path that stages a declared model, executes it on an approved Windows environment, captures status and outputs, converts outputs into a canonical dataset, and supports review through notebooks, maps, metrics, and reports.

**Current pain:** The contract describes more than 100 HEC-RAS and HEC-HMS models arriving for TWDB review, while desktop computing limits efficient processing. The kickoff deck also identifies risks around representative model selection, unattended authentication, long-running jobs and storage, output contracts, and worker recovery.

**Definition of success:** A new contributor can quickly find models, Jupyter notebooks, Deconstructed Notebooks, and load-balancer code; project staff can find the current plan, presentations, decisions, meetings, and deliverables; a future implementation can add one representative single-run slice without reorganizing the repository; and the repository clearly separates public code and model examples from operational credentials and potentially restricted model archives.

## Current code/system summary

The current workspace contains only `Kickoff-10-8.pptx`; it has no `.git` directory, source tree, tests, package metadata, CI configuration, or repository documentation. The deck itself is also the first project presentation artifact that should be placed into a controlled project-record location once publication status is confirmed. The deck's target operating model defines these boundaries:

1. DYNAMO platform/API and registries for the HEC-RAS application, ETL transforms, and visualization scripts.
2. A DYNAMO Model Bridge that maps deconstructed execution, ETL, and visualization pieces.
3. A Windows worker pool that pulls and stages work, maintains heartbeats and logs, and runs HEC-RAS through a versioned RasCommander plan.
4. Run files that produce HDF/geometry outputs plus logs and metrics.
5. Registered Python ETL that writes a dataset with canonical variables, geometry, and metadata.
6. TWDB/Jupyter review outputs that derive maps and metrics from the dataset.

The DSO Architecture documentation places most existing services behind Tapis OAuth2, treats CKAN as a central data hub, and separates repositories by functional cluster. It does not currently list a flood-model-process repository or a dedicated HEC-RAS/HEC-HMS cluster. This project therefore needs an explicit cluster and integration decision before external architecture documentation is updated.

## Proposed design

Use one repository with a small number of clear boundaries: models, Jupyter notebooks, Deconstructed Notebooks, load-balancer code, tests, documentation, and project records. Git history and release tags provide the technical archive; lightweight metadata provides the human-readable record of why a presentation or deliverable exists, which contract task it supports, and whether it is draft, accepted, submitted, or superseded.

```text
twdb-flood-model-automation/
├── README.md
├── LICENSE
├── CITATION.cff
├── CONTRIBUTING.md
├── SECURITY.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── models/                 # model packages used for development and testing
├── notebooks/              # Jupyter notebooks for review and analysis
├── deconstructed-notebooks/ # notebooks or fragments mapped to reusable steps
├── load_balancer/          # queueing and model-run coordination code
├── configs/                # small set of run and environment configuration files
├── tests/                  # tests for load balancer and notebook-support code
├── project/
│   ├── plan.md              # roadmap, milestones, and work breakdown
│   ├── meetings/            # agendas, notes, and action items
│   ├── decisions/           # dated decisions and approvals
│   ├── presentations/       # source decks and presentation metadata
│   ├── deliverables/        # draft and accepted outputs
│   └── archive/             # superseded project records
└── docs/
    ├── architecture.md
    ├── user-guide.md
    └── design/
```

The initial scaffold should include placeholder README files at the main boundaries, a root README that explains the target operating model and project-record conventions, package/test configuration for the load balancer, a permissive open-source license selected by the project owner, citation metadata, contribution/security guidance, an environment-variable template with no secrets, a small model README, and simple project-management templates.

Project records should use predictable names and small sidecar metadata files. The proposed convention is `YYYY-MM-DD-short-title.ext` for dated records and a `README.md` or `metadata.yaml` beside each presentation or deliverable describing title, contract task, status, owner, reviewers, source files, and supersedes/superseded-by links. Drafts remain editable in their working location; accepted or submitted artifacts are copied or tagged into the archive with their final checksum and acceptance/submission date. Large binary files may use Git LFS if the repository owner approves that dependency.

The repository should not become an uncontrolled dump of every meeting file or export. The project archive should contain authoritative project records and final deliverables, while sensitive working material, credentials, private model archives, and restricted SharePoint records remain in the approved system of record with a link and metadata pointer in the repository.

The architecture should treat the notebooks and their outputs as the initial review boundary. The load balancer should coordinate model execution and expose stable run information to notebooks. Deconstructed Notebooks should make reusable processing steps visible before they are promoted into load-balancer or other reusable code. DYNAMO registration and canonical dataset integration remain future extension points rather than separate scaffold layers.

The first implementation slice after scaffolding should be one representative model through staging, execution, status capture, output collection, one notebook-based review, and one documented project artifact, consistent with the deck's first-90-days plan. The repository should leave room for both HEC-RAS and HEC-HMS even if the first executable slice uses only one model family.

## Files likely affected

Initial scaffold files are expected under the current repository root:

- Root project metadata and governance: `README.md`, `LICENSE`, `CITATION.cff`, `CONTRIBUTING.md`, `SECURITY.md`, `pyproject.toml`, `.gitignore`, `.env.example`.
- Model examples: `models/`.
- Code pieces: `notebooks/`, `deconstructed-notebooks/`, and `load_balancer/`.
- Configuration and tests: `configs/`, `tests/`.
- Documentation: `docs/`.
- Project management and archive: `project/` with a plan, meetings, decisions, presentations, deliverables, and archive records.
- The existing kickoff deck should move under `project/presentations/` only if the project owner confirms it is appropriate to publish with the repository. The contract PDF should remain outside the public repository unless its distribution status is explicitly approved; a sanitized requirements summary and metadata pointer can live in `project/plan.md` or `docs/`.

No files in the DSO Architecture repository will be changed in this phase.

## API/schema changes

No network API or database schema is proposed for the scaffold phase.

The repository will reserve two lightweight file-based conventions for later implementation:

- A run configuration describing model family, model/software version, input locations, plan version, and output locations.
- A review-output convention describing source model, run identity, software versions, output files, and QA/QC notes.

The scaffold uses YAML for the small set of run and environment configuration files. This keeps configuration readable for operators while leaving the load-balancer implementation free to validate the structure before execution.

## Data flow

```text
Model package + run configuration
        ↓
Load balancer stages and dispatches the model run
        ↓
HEC-RAS or HEC-HMS executes under a versioned plan
        ↓
Native output files + execution information
        ↓
Deconstructed Notebook explores and documents processing steps
        ↓
Jupyter notebook reviews outputs and produces analysis artifacts
        ↓
Project deliverable or presentation is archived with metadata
```

The DYNAMO target operating model remains the architectural context for the load balancer and notebook pieces. TACC operational systems, authentication, storage, and any future CKAN/MINT/Tapis integration remain external adapters rather than being embedded into the initial scaffold.

## Risks and tradeoffs

- **Architecture coupling:** Encoding DYNAMO or MINT assumptions directly into the initial code could make the notebooks and load balancer harder to test locally. Keeping those integrations as future extension points reduces that risk but defers integration detail.
- **Windows dependency:** HEC-RAS and HEC-HMS execution requires a Windows-capable environment and licensed/approved software. Local CI should validate configuration, notebook logic, and model fixtures without requiring the proprietary executables.
- **Data exposure:** The contract assumes non-sensitive inputs, but repository publication still requires a deliberate check. Model examples and explicit ignore rules reduce accidental publication risk.
- **Notebook promotion:** Deconstructed Notebooks may contain useful logic that later belongs in the load balancer or a reusable library. The scaffold should preserve the exploratory layer without forcing premature abstraction.
- **Repository scope:** Keeping project records, models, notebooks, and load-balancer code together improves traceability for this contract but can become cluttered. The small number of top-level directories and metadata conventions are intended to keep it navigable.

## Alternatives considered

- **Separate repositories for models, notebooks, and load balancer:** Rejected for the initial contract deliverable because the contract calls for a documented GitHub repository containing the automation and extraction work, and the first slice crosses these pieces.
- **A generic DSO monorepo location:** Not selected because the current DSO Architecture repo maps independent services and tools as separate repositories; this project has a distinct flood-model execution and review lifecycle.
- **Large service-oriented package layout:** Rejected for the scaffold phase because the user identified three concrete code pieces and asked for significantly simpler organization.
- **Commit representative TWDB model archives:** Rejected until data ownership, access protocols, and public-release status are confirmed.

## Test plan

Scaffold phase checks:

- Verify the directory layout and required root metadata exist.
- Validate that the package imports and the test runner discovers tests.
- Validate example model/configuration files with a lightweight local command.
- Verify `.gitignore` excludes credentials, local environments, native model outputs, logs, and notebook checkpoints.
- Verify project-record templates cover the plan, meeting notes, decisions, presentation metadata, and deliverable metadata.
- Verify archived artifacts have a status, owner, contract-task mapping, review/acceptance field, and source/checksum field.
- Add a smoke test for the load-balancer package/configuration boundary.

Later implementation checks:

- Unit tests for load-balancer configuration, status transitions, and run coordination.
- Notebook/deconstructed-notebook checks for reproducible inputs and expected outputs.
- Integration tests with model fixtures in `models/`.
- Windows-only execution tests gated separately from cross-platform CI.
- User testing with TWDB staff and documented feedback incorporation.

## Documentation plan

The initial scaffold should document:

- The target operating model and boundaries from the kickoff deck.
- How to create a development environment and run cross-platform validation.
- How operators configure and diagnose a load-balancer run.
- How developers add a model, notebook, Deconstructed Notebook, or load-balancer capability.
- What data can and cannot be committed.
- How decisions, test evidence, and contract deliverables are tracked.
- How project records are named, reviewed, accepted, superseded, archived, and linked to contract tasks.
- Which records belong in GitHub and which remain in SharePoint, Box, or another approved system of record.

The DSO Architecture documentation should receive a separate service/repository page after the repository's cluster, integrations, startup behavior, and deployment target are confirmed. That would be an external documentation change and is out of scope for this scaffold draft.

## Rollout/rollback plan

Scaffold rollout is local and reversible: add the proposed repository files on a working branch, inspect the tree and checks, then review the diff before any remote repository creation or push. If the organization is rejected, revise the scaffold branch; do not delete unrelated user files or remove source records from their existing system of record.

Future external rollout will require explicit approval for GitHub repository creation, visibility, branch protection, secrets, DYNAMO/Tapis/CKAN/MINT configuration, or deployment changes.

## Open questions

- GitHub organization and remote publication details remain open.
- Which GitHub organization owns the repository?
- Should the initial repository be public, and should it use BSD-3-Clause or CC-BY for the code/documentation split?
- Should the DSO Architecture classify this as a new `flood-models` cluster, or place it under `cookbooks-geo`?
- Is DYNAMO/MINT integration part of the first implementation slice, or only a registry-compatible future boundary?
- Which 3–5 representative model archives and expected outputs will TWDB provide?
- What is the approved Windows worker identity/authentication and storage path?
- Are the kickoff deck and contract cleared for repository publication, or should the repo contain only sanitized summaries?
- Which system is authoritative for restricted project records such as signed contracts, invoices, private model archives, and SharePoint exports?
- Should accepted deliverables be archived in Git history/releases, Git LFS, or a linked external records system with only metadata committed here?

## Decisions

### 2026-10-08 — Scaffold around the kickoff target operating model

- **Decision:** Organize the repository around DYNAMO registries, Windows execution, versioned plans, Python ETL, canonical datasets, and TWDB review outputs.
- **Reason:** These are the explicit system boundaries shown in the kickoff architecture slide and align with the contract's execution, extraction, documentation, and user-testing deliverables.
- **Alternatives rejected:** A script-only root layout and a notebook-first layout would not preserve the execution-to-dataset flow or provide clear operational boundaries.
- **User feedback:** The user requested scaffolding and organization first and directed that the PowerPoint architecture be used with DSO Architecture context.
- **Impact on implementation:** The first code changes should create the directory and metadata scaffold only; they should not provision infrastructure or implement external integrations.

### 2026-10-08 — Keep DSO Architecture changes out of the scaffold phase

- **Decision:** Do not modify the DSO Architecture repository while establishing the local scaffold.
- **Reason:** The new repository's cluster, integrations, ports, deployment target, and authentication pattern remain open; updating architecture documentation before those choices are confirmed would create stale documentation.
- **Alternatives rejected:** Guessing a cluster or adding a provisional service page would conflict with the DSO documentation rule that current behavior and integrations must be verifiable.
- **User feedback:** No separate approval for DSO Architecture changes has been given.
- **Impact on implementation:** The scaffold may include a documentation note describing the pending architecture registration, but all DSO documentation edits remain a later approved task.

### 2026-10-08 — Treat project management and archival records as first-class repository content

- **Decision:** Add a `project/` area for plans, meetings, decisions, risks, status reports, presentations, deliverables, and archive metadata alongside the software tree.
- **Reason:** The user clarified that the scaffold must support project management as well as code, and the contract requires documented user testing, progress reporting, recommendations, and electronic deliverables.
- **Alternatives rejected:** Keeping project records only in personal notes or an unstructured `misc/` directory would make contract traceability and deliverable history difficult to review.
- **User feedback:** The user requested project-management organization and archiving for presentations and deliverables.
- **Impact on implementation:** The scaffold must include project-record templates, naming/status conventions, publication/access classification, and a clear boundary between repository records and restricted external records.

### 2026-10-08 — Simplify the repository around the concrete code pieces

- **Decision:** Use `models/`, `notebooks/`, `deconstructed-notebooks/`, and `load_balancer/` as the primary technical areas, with a smaller `project/` area for planning and archives.
- **Reason:** The user clarified that synthetic models can simply be models and identified Jupyter notebooks, Deconstructed Notebooks, and the load balancer as the code pieces.
- **Alternatives rejected:** A deeper service-style tree with separate orchestration, execution, ETL, dataset, registry, and worker packages would overstate the current implementation and add structure before the first working slice exists.
- **User feedback:** The user requested significantly simpler project organization and named the concrete code pieces.
- **Impact on implementation:** The next scaffold should create the simpler top-level directories and avoid placeholder subpackages that do not yet correspond to working code.

### 2026-10-08 — Use YAML for initial run configuration

- **Decision:** Use YAML for the initial load-balancer run configuration example and loader.
- **Reason:** The configuration is operator-facing and should remain readable while the execution contract is still being shaped.
- **Alternatives rejected:** JSON was not selected for the first scaffold because it is more verbose for hand-maintained run configuration; a larger schema system would add unnecessary weight at this stage.
- **User feedback:** No objection was raised to a simple configuration format; this choice resolves the draft assumption for implementation.
- **Impact on implementation:** Add a small YAML loader and focused validation test without introducing a network API or a full execution engine.

### 2026-10-08 — Keep remote GitHub and architecture writes separate

- **Decision:** Implement and validate the repository locally without creating a remote repository, pushing commits, or modifying DSO Architecture.
- **Reason:** Those actions create external state and require a separate approval step; the current request approves the local scaffold.
- **Alternatives rejected:** Publishing immediately would couple the initial scaffold to an unconfirmed GitHub organization, visibility, and architecture classification.
- **User feedback:** The user approved implementation of the scaffold; no remote destination or push approval was provided.
- **Impact on implementation:** Initialize local Git only if needed for validation, and report external publication as follow-up work.

### 2026-10-08 — Use BSD-3-Clause for the initial code scaffold

- **Decision:** Add a BSD-3-Clause license for the initial repository scaffold.
- **Reason:** The contract identifies BSD-3-Clause as an acceptable open-license option requiring citation, and the scaffold is code-oriented.
- **Alternatives rejected:** CC-BY was not selected for the initial code scaffold; a separate documentation license can be added if the project owner later needs one.
- **User feedback:** No separate license preference was provided.
- **Impact on implementation:** Added `LICENSE` and `CITATION.cff`; ownership and publication details should be confirmed before remote publication.

### 2026-10-08 — Name the repository twdb-flood-model-automation

- **Decision:** Rename the local project directory and repository/package identity to `twdb-flood-model-automation`.
- **Reason:** The name describes the automation focus while leaving room for HEC-RAS, HEC-HMS, notebooks, models, and project records.
- **Alternatives rejected:** `TWDB-Hecras` was too narrow and platform-specific; `twdb-flood-model-process` described the contract but was less specific about the repository's implementation focus.
- **User feedback:** The user selected `twdb-flood-model-automation`.
- **Impact on implementation:** Rename the local directory and update README, package metadata, and citation metadata; the contract/program name remains “TWDB Flood Model Process” in project documentation.

## Implementation result

The local scaffold now includes the simplified technical areas (`models/`, `notebooks/`, `deconstructed-notebooks/`, and `load_balancer/`), a YAML configuration loader with focused tests, project-management and archive directories, the kickoff presentation archive, root repository metadata, and GitHub Actions CI configuration.

The repository remains local-only. No remote GitHub repository, DSO Architecture update, infrastructure provisioning, external integration, or model execution was performed.

## User feedback / decisions

Pending user review. The requested direction so far is:

- Focus on scaffolding and organization first.
- Use the configuration/target operating model in `Kickoff-10-8.pptx`.
- Use the DSO Architecture repository as the architectural reference.
- Include project-management organization and an archive for presentations and deliverables.
- Keep the project structure significantly simpler, with models, Jupyter notebooks, Deconstructed Notebooks, and a load balancer as the primary code pieces.
