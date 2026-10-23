# TWDB Flood Model Automation

Repository scaffold for the TWDB Flood Model Process program.

The repository has four primary technical areas:

- `models/` contains model packages used for development and testing.
- `notebooks/` contains Jupyter notebooks for review and analysis.
- `deconstructed-notebooks/` contains processing steps that are being explored or made reusable.
- `load_balancer/` contains code that coordinates model runs.

Project records live under `project/`. The project plan, meeting records, decisions, presentations, deliverables, and archived records are kept there with lightweight metadata. Living technical guidance lives under `docs/`.

## Current status

This repository contains the initial scaffold. It does not yet provision TACC infrastructure, execute HEC-RAS or HEC-HMS, register components with DYNAMO, or publish a remote GitHub repository.

## Development setup

For Windows modeling software, see the [workstation setup guide](docs/windows-workstation-setup.md).
It covers Miniforge Python/Conda, QGIS LTR, and one stable HEC-RAS/HEC-HMS version per major family.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
pytest
```

The first executable boundary is the YAML run configuration loader:

```bash
python - <<'PY'
from load_balancer import load_run_config

config = load_run_config("configs/example-run.yaml")
print(config.name, config.model_family, config.concurrency)
PY
```

## Project records

Use `YYYY-MM-DD-short-title.ext` for dated records. Presentations and deliverables should have a nearby `metadata.yaml` or README describing the contract task, owner, status, reviewers, and source information. Do not commit credentials, private model archives, restricted SharePoint exports, or signed contract records unless their publication status is approved.

## Architecture

The target operating model is documented in [docs/architecture.md](docs/architecture.md). It follows the kickoff concept of a model run coordinated by a load balancer, explored and documented through Deconstructed Notebooks, and reviewed through Jupyter notebooks.
