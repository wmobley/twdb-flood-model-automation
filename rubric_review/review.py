"""Evaluate checklist groups against HEC-RAS / HEC-HMS projects found on a VM.

All VM access goes through ``call(script_name, **params) -> parsed JSON`` (``VMSession.run_script`` in
production), so the evaluation logic can be tested without a VM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .checklist import ChecklistGroup
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
class ItemResult:
    item_no: str
    row: int
    kind: str
    model: str
    run: str
    status: str | None  # "Y" | "N" | "N/A" | None (reviewer must decide)
    comment: str
    figure: str | None = None


@dataclass
class ReviewOutcome:
    results: list[ItemResult]
    environment: dict[str, Any]
    executions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # one row per model/run: {"model","run","found":{event:bool}}


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


def _find_ras(projects: list[dict], model: str, plan: str) -> tuple[dict | None, dict | None, str]:
    wanted = norm(model)
    candidates = [p for p in projects if wanted in (norm(p["title"]), norm(p["base"]))]
    if not candidates:
        found = ", ".join(sorted(p["title"] or p["base"] for p in projects)) or "none"
        return None, None, f"No HEC-RAS project titled '{model}' found under the models root; projects found: {found}"
    for project in candidates:
        for pl in project["plans"]:
            if norm(plan) in (norm(pl["title"]), norm(pl["shortId"])):
                return project, pl, ""
    known = ", ".join(sorted({pl["title"] for p in candidates for pl in p["plans"]})) or "none"
    return candidates[0], None, f"Project found ({candidates[0]['prj']}) but no plan named '{plan}'; plans: {known}"


def _find_hms(projects: list[dict], model: str, run: str) -> tuple[dict | None, dict | None, str]:
    wanted = norm(model)
    candidates = [p for p in projects if norm(p["name"]) == wanted]
    if not candidates:
        found = ", ".join(sorted(p["name"] for p in projects)) or "none"
        return None, None, f"No HEC-HMS project named '{model}' found under the models root; projects found: {found}"
    for project in candidates:
        for r in project["runs"]:
            if norm(run) == norm(r["name"]):
                return project, r, ""
    known = ", ".join(r["name"] for p in candidates for r in p["runs"]) or "none"
    return candidates[0], None, f"Project found ({candidates[0]['hms']}) but no run named '{run}'; runs: {known}"


def _ras_run(call: Call, install: dict | None, project: dict, plan: dict, opts: ReviewOptions, log: list) -> tuple[str | None, str]:
    missing = [name for name, ok in (("geometry", plan["geomExists"]), ("flow", plan["flowExists"])) if not ok]
    if missing:
        return "N", f"Plan references missing {' and '.join(missing)} file(s) (geom={plan['geomFile'] or '-'}, flow={plan['flowFile'] or '-'})"
    deps = f"Geometry .{plan['geomFile']} and flow .{plan['flowFile']} present"
    if not opts.run_models:
        return None, f"{deps}. Plan was not executed (run_models=False); confirm it computes."
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


def _hms_run(call: Call, install: dict | None, project: dict, run: dict, opts: ReviewOptions, log: list) -> tuple[str | None, str]:
    deps = f"Run '{run['name']}' defined (basin={run['basin'] or '-'}, met={run['met'] or '-'}, control={run['control'] or '-'})"
    if not (run["basin"] and run["control"]):
        return "N", f"{deps}; run is missing a basin or control specification"
    if not opts.run_models:
        return None, f"{deps}. Run was not executed (run_models=False); confirm it computes."
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


def _events(group: ChecklistGroup, project: dict, unit: dict, expected: list[str], rows: list[dict]) -> tuple[str | None, str]:
    """Y when every Scope of Work event is represented. HMS: each event needs a run; RAS: the plan's own text must name it."""
    if group.tool == "hms":
        found = find_events(" | ".join(r["name"] for r in project["runs"]), expected)
        where = f"runs in project ({', '.join(r['name'] for r in project['runs'])})"
    else:
        text = " | ".join([unit["title"], unit["shortId"], unit["flowTitle"], unit["flowText"]])
        found = find_events(text, expected)
        where = f"plan '{unit['title']}' / flow file .{unit['flowFile']}"
    if not any(r["model"] == group.model_name and r["run"] == group.run_name for r in rows):
        rows.append({"model": group.model_name, "run": group.run_name, "tool": group.tool, "found": found})
    missing = [e for e, ok in found.items() if not ok]
    if not missing:
        return "Y", f"All {len(expected)} Scope of Work events found in {where}."
    if group.tool == "ras":
        elsewhere = {e for pl in project["plans"] if pl is not unit
                     for e, ok in find_events(" | ".join([pl["title"], pl["shortId"], pl["flowTitle"], pl["flowText"]]), missing).items() if ok}
        extra = f" Found only in other plans of this project: {', '.join(sorted(elsewhere))}." if elsewhere else ""
    else:
        extra = ""
    return "N", f"Events not found in {where}: {', '.join(missing)}.{extra}"


def run_review(call: Call, groups: list[ChecklistGroup], opts: ReviewOptions, geo: Any = None) -> ReviewOutcome:
    software = call("inventory_software.ps1")
    ras_projects = call("inventory_ras.ps1", Root=opts.models_root)
    hms_projects = call("inventory_hms.ps1", Root=opts.models_root)
    ras_install = pick_install(software["installs"], "HEC-RAS", opts.ras_version)
    hms_install = pick_install(software["installs"], "HEC-HMS", opts.hms_version)

    results: list[ItemResult] = []
    executions: list[dict] = []
    event_rows: list[dict] = []
    for group in groups:
        if group.tool == "ras":
            project, unit, problem = _find_ras(ras_projects, group.model_name, group.run_name)
        else:
            project, unit, problem = _find_hms(hms_projects, group.model_name, group.run_name)

        computed: tuple[str | None, str] | None = None  # compute once per group
        for item in group.items:
            figure = None
            if unit is None:
                status, comment = "N", problem
            elif item.kind == "runs":
                if computed is None:
                    if group.tool == "ras":
                        computed = _ras_run(call, ras_install, project, unit, opts, executions)
                    else:
                        computed = _hms_run(call, hms_install, project, unit, opts, executions)
                status, comment = computed
            elif item.kind == "events" and opts.expected_events:
                status, comment = _events(group, project, unit, opts.expected_events, event_rows)
            elif item.kind == "events":
                if group.tool == "ras":
                    detail = f"flow file .{unit['flowFile']} '{unit['flowTitle']}'" if unit["flowExists"] else "flow file missing"
                else:
                    detail = f"met model '{unit['met'] or '-'}', control '{unit['control'] or '-'}'"
                status = "N" if "missing" in detail else None
                comment = f"Evidence: {detail}. Reviewer must compare against the Scope of Work events."
            elif item.kind == "area":
                if group.tool == "ras":
                    shapes = [(s["ref"], s["exists"]) for s in project["shapefiles"]]
                    status, comment = _area(shapes, opts.project_area_shapefile, f"{project['base']}.rasmap")
                    if geo is not None:
                        geo_result = geo.check_ras(project, unit)
                        figure = geo_result.figure
                        if geo_result.status is None:
                            comment += f" Footprint check unavailable: {geo_result.comment}"
                        else:
                            status = "Y" if (status == "Y" and geo_result.status == "Y") else "N"
                            comment = f"{geo_result.comment} Map layer: {comment}"
                else:
                    on_disk = set(project["shpOnDisk"])
                    shapes = [(s["ref"], s["ref"].replace("\\", "/").rsplit("/", 1)[-1] in on_disk) for s in project["shapefiles"]]
                    status, comment = _area(shapes, opts.project_area_shapefile, f"HMS project {project['name']}")
            else:
                status, comment = None, "No automated check for this item."
            results.append(ItemResult(item.item_no, item.row, item.kind, group.model_name, group.run_name, status, comment, figure))

    environment = {
        "computer": software["computer"], "user": software["user"],
        "ras_install": ras_install["version"] if ras_install else None,
        "hms_install": hms_install["version"] if hms_install else None,
        "installs": [f"{i['product']} {i['version']}" for i in software["installs"]],
        "ras_projects_found": len(ras_projects), "hms_projects_found": len(hms_projects),
        "models_root": opts.models_root, "run_models": opts.run_models,
    }
    return ReviewOutcome(results, environment, executions, event_rows)
