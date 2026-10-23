# Architecture

The initial repository is intentionally small and follows four technical areas:

1. `models/` provides model packages for development and testing.
2. `load_balancer/` coordinates future model runs and exposes stable run information.
3. `deconstructed-notebooks/` documents individual processing steps before they become reusable code.
4. `notebooks/` turns model outputs into reviewer-facing analysis artifacts.

The kickoff target operating model places these pieces in a larger DYNAMO context: registered applications, transforms, and visualizations; a Windows execution pool; and dataset/review outputs. DYNAMO, TACC authentication, storage, and future CKAN/MINT/Tapis integrations remain future boundaries until their requirements are confirmed.
