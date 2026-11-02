# Jupyter notebooks

Use this directory for reviewer-facing and analysis notebooks. Notebooks should document their model inputs, expected outputs, software versions, and any manual review steps.

Keep exploratory fragments in `deconstructed-notebooks/` until their purpose and reusable boundary are clear.

## Notebooks

- `rubric-fppg-deliverables-review.ipynb` — run on a DYNAMO Windows VM (`dynamo02`–`dynamo08`) after RDP login (`MODE="local"`; SSH mode is optional and blocked from laptops so far), stages a model submission, runs the *C – Modeling Review* items of the FPPG Project Deliverables Checklist (`docs/rubrics/`), and writes a filled-in workbook plus HTML report to `outputs/rubric-review/`. Code lives in `rubric_review/`; install with `pip install -e ".[rubric]"`. Requires the VM to run the Windows OpenSSH server. The PowerShell compute commands (`Ras.exe -c`, HEC-HMS `-script`) have not yet been exercised against a live VM.

The project-area footprint check also needs `geopandas`, `h5py` and `matplotlib` (the `rubric-geo` extra; `conda install geopandas h5py matplotlib` is more reliable on Windows). HDF paths read for the footprint (`Geometry/2D Flow Areas/*/Perimeter`, `Cross Sections`, `River Centerlines`) follow HEC-RAS 6.x geometry files and are verified only against synthetic test files, not yet a real model.
