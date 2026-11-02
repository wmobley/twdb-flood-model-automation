"""Apply the checklist tests to every HEC-RAS plan and HEC-HMS run found on a VM.

All VM access goes through ``call(script_name, **params) -> parsed JSON`` (``VMSession.run_script`` in
production), so the evaluation logic can be tested without a VM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .events import find_events

Call = Callable[..., Any]


@dataclass
class ReviewOptions:
    models_root: str  # Windows path of the extracted models on the VM
    run_models: bool = False  # False = inventory/dependency checks only; True = compute each plan/run
    ras_version: str = "6.6"
    hms_version: str | None = None  # None = highest installed
    project_area_shapefile: str | None = None  # file name the Grant Agreement area shapefile must have
    timeout_min: int = 60
    expected_events: list[str] = field(default_factory=list)  # Scope of Work events, e.g. ["10-yr", "25-yr"]


@dataclass
class ModelFinding:
    """Everything tested for one plan (HEC-RAS) or simulation run (HEC-HMS) found in the submission."""

    tool: str  # "ras" | "hms"
    project: str
    unit: str  # plan title / run name
    path: str
    checks: dict[str, tuple[str | None, str, str | None]]  # kind -> (status, comment, figure)
    events: dict[str, bool] = field(default_factory=dict)  # expected event -> found

    @property
    def verdict(self) -> str | None:
        statuses = {s for s, _, _ in self.checks.values()}
        return "N" if "N" in statuses else (None if None in statuses else "Y")


@dataclass
class ReviewOutcome:
    environment: dict[str, Any]
    executions: list[dict[str, Any]] = field(default_factory=list)
    inventory: dict[str, list[str]] = field(default_factory=dict)  # what the scan found: {"ras": [...], "hms": [...]}
    findings: list[ModelFinding] = field(default_factory=list)  # one per plan/run found in the submission


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def pick_install(installs: list[dict], product: str, wanted: str | None) -> dict | None:
    usable = [i for i in installs if i["product"] == product and i["exeExists"]]
    if not usable:
        return None
    if wanted:
        exact = [i for i in usable if i["version"] == wanted]
        if exact:
            return exact[0]
    return max(usable, key=lambda i: _version_key(i["version"]))


def _ras_run(call: Call, install: dict | None, project: dict, plan: dict, opts: ReviewOptions, log: list, execute: bool) -> tuple[str | None, str]:
    missing = [name for name, ok in (("geometry", plan["geomExists"]), ("flow", plan["flowExists"])) if not ok]
    if missing:
        return "N", f"Plan references missing {' and '.join(missing)} file(s) (geom={plan['geomFile'] or '-'}, flow={plan['flowFile'] or '-'})"
    deps = f"Geometry .{plan['geomFile']} and flow .{plan['flowFile']} present"
    if not execute:
        return None, f"{deps}. Plan was not executed; confirm it computes."
    if install is None:
        return None, f"{deps}. No usable HEC-RAS install found on the VM; not executed."
    result = call("run_ras_plan.ps1", timeout=(opts.timeout_min + 5) * 60,
                  Exe=install["exe"], Prj=project["prj"], Plan=plan["file"], TimeoutMin=opts.timeout_min)
    log.append({"tool": f"HEC-RAS {install['version']}", "project": project["title"], "plan": plan["title"], **result})
    stamp = f"HEC-RAS {install['version']}, {result['seconds']}s"
    if result["timedOut"]:
        return "N", f"Run exceeded {opts.timeout_min} min timeout ({stamp})"
    if result["errorLines"]:
        return "N", f"Compute messages contain errors ({stamp}): " + " | ".join(result["errorLines"][:5])
    if result["exitCode"] != 0 or not result["planHdfUpdated"]:
        return "N", f"Exit code {result['exitCode']}, results file updated={result['planHdfUpdated']} ({stamp})"
    return "Y", f"Computed with no errors in compute messages ({stamp}); {deps}"


def _hms_run(call: Call, install: dict | None, project: dict, run: dict, opts: ReviewOptions, log: list, execute: bool) -> tuple[str | None, str]:
    deps = f"Run '{run['name']}' defined (basin={run['basin'] or '-'}, met={run['met'] or '-'}, control={run['control'] or '-'})"
    if not (run["basin"] and run["control"]):
        return "N", f"{deps}; run is missing a basin or control specification"
    if not execute:
        return None, f"{deps}. Run was not executed; confirm it computes."
    if install is None:
        return None, f"{deps}. No usable HEC-HMS install found on the VM; not executed."
    result = call("run_hms_run.ps1", timeout=(opts.timeout_min + 5) * 60,
                  Cmd=install["exe"], Hms=project["hms"], RunName=run["name"], TimeoutMin=opts.timeout_min)
    log.append({"tool": f"HEC-HMS {install['version']}", "project": project["name"], "plan": run["name"], **result})
    stamp = f"HEC-HMS {install['version']}, {result['seconds']}s"
    if result["timedOut"]:
        return "N", f"Run exceeded {opts.timeout_min} min timeout ({stamp})"
    if result["errorLines"]:
        return "N", f"Compute output contains errors ({stamp}): " + " | ".join(result["errorLines"][:5])
    if result["exitCode"] != 0 or not result["freshDssFiles"]:
        return "N", f"Exit code {result['exitCode']}, fresh DSS results={result['freshDssFiles']} ({stamp})"
    return "Y", f"Computed with no errors ({stamp}); {deps}"


def _area(shapes: list[tuple[str, bool]], wanted: str | None, where: str) -> tuple[str | None, str]:
    present = [ref for ref, exists in shapes if exists]
    if wanted:
        present = [ref for ref in present if norm(ref.replace("\\", "/").rsplit("/", 1)[-1]) == norm(wanted)]
        need = f" named '{wanted}'"
    else:
        need = ""
    if present:
        return "Y", f"Shapefile{need} referenced by {where} and present: {', '.join(sorted(set(present)))}"
    listed = ", ".join(ref for ref, _ in shapes) or "none"
    return "N", f"No shapefile{need} that exists is referenced by {where} (references: {listed})"


def _events(tool: str, project: dict, unit: dict, expected: list[str]) -> tuple[str | None, str, dict[str, bool]]:
    """Y when every Scope of Work event is represented. HMS: each event needs a run; RAS: the plan's own text must name it."""
    if tool == "hms":
        found = find_events(" | ".join(r["name"] for r in project["runs"]), expected)
        where = f"runs in project ({', '.join(r['name'] for r in project['runs'])})"
    else:
        found = find_events(_ras_text(unit), expected)
        where = f"plan '{unit['title']}' / flow file .{unit['flowFile']}"
    missing = [e for e, ok in found.items() if not ok]
    if not missing:
        return "Y", f"All {len(expected)} Scope of Work events found in {where}.", found
    extra = ""
    if tool == "ras":
        elsewhere = {e for pl in project["plans"] if pl is not unit
                     for e, ok in find_events(_ras_text(pl), missing).items() if ok}
        if elsewhere:
            extra = f" Found only in other plans of this project: {', '.join(sorted(elsewhere))}."
    return "N", f"Events not found in {where}: {', '.join(missing)}.{extra}", found


def _ras_text(plan: dict) -> str:
    return " | ".join([plan["title"], plan["shortId"], plan["flowTitle"], plan["flowText"]])


def _evidence_only_events(tool: str, unit: dict) -> tuple[str | None, str]:
    if tool == "ras":
        detail = f"flow file .{unit['flowFile']} '{unit['flowTitle']}'" if unit["flowExists"] else "flow file missing"
    else:
        detail = f"met model '{unit['met'] or '-'}', control '{unit['control'] or '-'}'"
    status = "N" if "missing" in detail else None
    return status, f"Evidence: {detail}. Reviewer must compare against the Scope of Work events (no EXPECTED_EVENTS given)."


def _evaluate(tool, call, install, project, unit, opts, geo, log, execute) -> ModelFinding:
    if tool == "ras":
        name, path = project["title"] or project["base"], unit["file"]
        runs = _ras_run(call, install, project, unit, opts, log, execute)
        shapes = [(s["ref"], s["exists"]) for s in project["shapefiles"]]
        area_status, area_comment = _area(shapes, opts.project_area_shapefile, f"{project['base']}.rasmap")
        figure = None
        if geo is not None:
            g = geo.check_ras(project, unit)
            figure = g.figure
            if g.status is None:
                area_comment += f" Footprint check unavailable: {g.comment}"
            else:
                area_status = "Y" if (area_status == "Y" and g.status == "Y") else "N"
                area_comment = f"{g.comment} Map layer: {area_comment}"
        unit_name = unit["title"]
    else:
        name, path, unit_name = project["name"], project["hms"], unit["name"]
        runs = _hms_run(call, install, project, unit, opts, log, execute)
        on_disk = set(project["shpOnDisk"])
        shapes = [(s["ref"], s["ref"].replace("\\", "/").rsplit("/", 1)[-1] in on_disk) for s in project["shapefiles"]]
        area_status, area_comment = _area(shapes, opts.project_area_shapefile, f"HMS project {project['name']}")
        figure = None
    found: dict[str, bool] = {}
    if opts.expected_events:
        ev_status, ev_comment, found = _events(tool, project, unit, opts.expected_events)
    else:
        ev_status, ev_comment = _evidence_only_events(tool, unit)
    checks = {"runs": (*runs, None), "events": (ev_status, ev_comment, None), "area": (area_status, area_comment, figure)}
    return ModelFinding(tool, name, unit_name, path, checks, found)


def run_review(call: Call, opts: ReviewOptions, geo: Any = None) -> ReviewOutcome:
    """Apply the checklist tests (runs, events, project area) to every plan/run found under ``models_root``."""
    software = call("inventory_software.ps1")
    ras_projects = call("inventory_ras.ps1", Root=opts.models_root)
    hms_projects = call("inventory_hms.ps1", Root=opts.models_root)
    installs = {"ras": pick_install(software["installs"], "HEC-RAS", opts.ras_version),
                "hms": pick_install(software["installs"], "HEC-HMS", opts.hms_version)}

    executions: list[dict] = []
    findings: list[ModelFinding] = []
    for tool, projects, units in (("hms", hms_projects, "runs"), ("ras", ras_projects, "plans")):
        for project in projects:
            for unit in project[units]:
                findings.append(_evaluate(tool, call, installs[tool], project, unit, opts, geo, executions, opts.run_models))

    environment = {
        "computer": software["computer"], "user": software["user"],
        "ras_install": installs["ras"]["version"] if installs["ras"] else None,
        "hms_install": installs["hms"]["version"] if installs["hms"] else None,
        "installs": [f"{i['product']} {i['version']}" for i in software["installs"]],
        "ras_projects_found": len(ras_projects), "hms_projects_found": len(hms_projects),
        "models_found": len(findings), "models_root": opts.models_root, "run_models": opts.run_models,
    }
    inventory = {
        "ras": sorted(f"{p['title'] or p['base']}  ({p['prj']})" for p in ras_projects),
        "hms": sorted(f"{p['name']}  ({p['hms']})" for p in hms_projects),
    }
    return ReviewOutcome(environment, executions, inventory, findings)
