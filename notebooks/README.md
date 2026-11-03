# Jupyter notebooks

Use this directory for reviewer-facing and analysis notebooks. Notebooks should document their model inputs, expected outputs, software versions, and any manual review steps.

Keep exploratory fragments in `deconstructed-notebooks/` until their purpose and reusable boundary are clear.

## Notebooks

- `rubric-fppg-deliverables-review.ipynb` — run on a DYNAMO Windows VM (`dynamo02`–`dynamo08`) after RDP login (`MODE="winrm"` from your own machine, or `MODE="local"` on the VM), stages a model submission, applies the *C – Modeling Review* tests of the FPPG Project Deliverables Checklist (`docs/rubrics/`) to every plan/run found in the submitted models (the checklist's example model names are ignored), and writes a themed HTML report plus a checklist workbook with one block per model to `outputs/rubric-review/`. Code lives in `rubric_review/`; install with `pip install -e ".[rubric]"`. In `winrm` mode `HOSTS` can list several VMs (default `DYNAMO_HOSTS`: `dynamo.tacc.utexas.edu` plus `dynamo02`–`dynamo08`); the submission is then staged on every VM and the plans/runs are shared out so each VM takes the next untested model as soon as it is free (`rubric_review/fleet.py`). Logins are made one VM at a time, one attempt each, and stop at the first failure to avoid locking the shared account. The report names the VM that tested each model. The PowerShell compute commands (`Ras.exe -c`, HEC-HMS `-script`) have not yet been exercised against a live VM.

The project-area footprint check also needs `geopandas`, `h5py` and `matplotlib` (the `rubric-geo` extra; `conda install geopandas h5py matplotlib` is more reliable on Windows). HDF paths read for the footprint (`Geometry/2D Flow Areas/*/Perimeter`, `Cross Sections`, `River Centerlines`) follow HEC-RAS 6.x geometry files and are verified only against synthetic test files, not yet a real model.
