"""Apply the checklist tests to every HEC-RAS plan and HEC-HMS run found on a VM.

All VM access goes through ``call(script_name, **params) -> parsed JSON`` (``VMSession.run_script`` in
production), so the evaluation logic can be tested without a VM.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from .events import find_events

Call = Callable[..., Any]


def _silent(_message: str) -> None:
    pass


@dataclass
class RunStatus:
    """One snapshot of a compute, sent to ``ReviewOptions.status`` at every poll (and once when it ends)."""

    label: str  # "HEC-RAS 6.6 · Project / Plan"
    tool: str  # "ras" | "hms"
    project: str
    unit: str
    seconds: int
    state: str  # "running" | "finished" | "stopped"
    stage: str  # what the tool is doing, e.g. "preprocessing geometry", "unsteady flow", "writing results"
    detail: str = ""  # last file written, etc.
    exit_code: int | None = None
    host: str | None = None  # set by the fleet runner
    done: int | None = None  # models finished so far in this review (set by the runner)
    total: int | None = None  # models to test in this review (set by the runner)


@dataclass
class ReviewOptions:
    models_root: str  # Windows path of the extracted models on the VM
    run_models: bool = False  # False = inventory/dependency checks only; True = compute each plan/run
    ras_version: str = "6.6"
    hms_version: str | None = None  # None = highest installed
    project_area_shapefile: str | None = None  # file name the Grant Agreement area shapefile must have
    poll_seconds: float = 15.0  # how often to check on a running compute; there is no time limit
    progress: Callable[[str], None] = _silent  # receives a human-readable status line at each step
    log_dir: Path | None = None  # when set, every poll of a compute (files changed, log tails) is appended to a .jsonl here
    expected_events: list[str] = field(default_factory=list)  # Scope of Work events, e.g. ["10-yr", "25-yr"]
    stopped: Callable[[], bool] = lambda: False  # polled between checks; True makes a running compute stop (used by the fleet runner)
    status: Callable[[RunStatus], None] | None = None  # when set, per-poll snapshots go here instead of text lines to ``progress``


class ReviewStopped(Exception):
    """Raised inside a compute poll loop when ``ReviewOptions.stopped`` turns True; the VM process has been stopped."""


@dataclass
class ModelFinding:
    """Everything tested for one plan (HEC-RAS) or simulation run (HEC-HMS) found in the submission."""

    tool: str  # "ras" | "hms"
    project: str
    unit: str  # plan title / run name
    path: str
    checks: dict[str, tuple[str | None, str, str | None]]  # kind -> (status, comment, figure)
    events: dict[str, bool] = field(default_factory=dict)  # expected event -> found
    host: str | None = None  # VM that tested this model (set by the fleet runner)

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


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


_STAGES = (  # child process name -> what HEC-RAS / HEC-HMS is doing
    ("RasProcess", "preprocessing geometry"), ("RasUnsteady", "unsteady flow"), ("RasSteady", "steady flow"),
    ("RasMapper", "mapping results"), ("java", "computing"),
)


def _stage(state: dict) -> str:
    if state.get("stage"):
        return state["stage"]
    names = " ".join(state.get("processes") or [])
    for needle, stage in _STAGES:
        if needle.lower() in names.lower():
            return stage
    if state.get("lastFile"):
        return "writing results"
    return "starting"


def _snapshot(state: dict, label: str, kind: str, project: str, unit: str) -> RunStatus:
    bits = []
    if state.get("lastFile"):
        bits.append(f"last file {state['lastFile']} ({state['lastFileAgo']}s ago)")
    if state.get("progressTail"):
        bits.append(state["progressTail"][-1].strip()[:100])
    return RunStatus(label, kind, project, unit, int(state["seconds"]), "running" if state["running"] else "finished",
                     _stage(state) if state["running"] else "finished", " · ".join(bits), state.get("exitCode"))


def _execute(call: Call, kind: str, exe: str, target: str, unit: str, plan_file: str, label: str, opts: ReviewOptions,
             project: str = "", unit_name: str = "") -> dict:
    """Start a compute on the VM and poll until it ends, reporting progress. Ctrl-C / interrupt stops the VM process.

    Progress goes to ``opts.status`` as ``RunStatus`` snapshots when that is set (for an in-place display), otherwise as
    one text line per poll to ``opts.progress``.
    """
    started = call("start_run.ps1", Kind=kind, Exe=exe, Target=target, Unit=unit)
    log_file = None
    if opts.log_dir is not None:
        Path(opts.log_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(opts.log_dir) / (re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_")[:90] + ".jsonl")
    poll = {"Kind": kind, "RunDir": started["runDir"], "ProjectDir": started["projectDir"],
            "StartedUtc": started["startedUtc"], "ProcessId": started["processId"], "Plan": plan_file,
            "Probe": int(log_file is not None)}
    opts.progress(f"{label}: started (process {started['processId']}), checking every {opts.poll_seconds:g}s")
    try:
        while True:
            state = call("poll_run.ps1", **poll)
            if log_file is not None:
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"logged": time.strftime("%H:%M:%S"), **state}) + "\n")
            if not state["running"]:
                if opts.status is not None:
                    opts.status(_snapshot(state, label, kind, project, unit_name))
                opts.progress(f"{label}: finished after {_clock(state['seconds'])} (exit code {state['exitCode']})")
                return state
            if opts.status is not None:
                opts.status(_snapshot(state, label, kind, project, unit_name))
                _wait(opts)
                continue
            bits = [f"{label}: running {_clock(state['seconds'])}"]
            bits.append(f"last file written {state['lastFileAgo']}s ago ({state['lastFile']})" if state["lastFile"]
                        else "no files written yet")
            if state["processes"]:
                bits.append(", ".join(state["processes"]))
            if state["progressTail"]:
                bits.append("» " + state["progressTail"][-1].strip()[:100])
            opts.progress(" | ".join(bits))
            _wait(opts)
    except BaseException:
        call("stop_run.ps1", ProcessId=started["processId"])
        if opts.status is not None:
            opts.status(RunStatus(label, kind, project, unit_name, 0, "stopped", "stopped"))
        opts.progress(f"{label}: stopped")
        raise


def _wait(opts: ReviewOptions) -> None:
    """Sleep ``poll_seconds`` in one-second steps so a stop request is noticed quickly."""
    deadline = time.monotonic() + opts.poll_seconds
    while True:
        if opts.stopped():
            raise ReviewStopped()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def _verdict(result: dict, stamp: str, ok_detail: str, error_kind: str = "messages") -> tuple[str | None, str]:
    if result["exitCode"] is None:
        return None, f"The compute process ended without an exit code ({stamp}); it may have been stopped. Re-run to confirm."
    if result["errorLines"]:
        return "N", f"Compute {error_kind} contain errors ({stamp}): " + " | ".join(result["errorLines"][:5])
    return "Y", ok_detail


def _ras_run(call: Call, install: dict | None, project: dict, plan: dict, opts: ReviewOptions, log: list, execute: bool) -> tuple[str | None, str]:
    missing = [name for name, ok in (("geometry", plan["geomExists"]), ("flow", plan["flowExists"])) if not ok]
    if missing:
        return "N", f"Plan references missing {' and '.join(missing)} file(s) (geom={plan['geomFile'] or '-'}, flow={plan['flowFile'] or '-'})"
    deps = f"Geometry .{plan['geomFile']} and flow .{plan['flowFile']} present"
    if not execute:
        return None, f"{deps}. Plan was not executed; confirm it computes."
    if install is None:
        return None, f"{deps}. No usable HEC-RAS install found on the VM; not executed."
    result = _execute(call, "ras", install["exe"], project["prj"], plan["file"], plan["file"],
                      f"HEC-RAS {install['version']} · {project['title']} / {plan['title']}", opts,
                      project["title"], plan["title"])
    log.append({"tool": f"HEC-RAS {install['version']}", "project": project["title"], "plan": plan["title"], **result})
    stamp = f"HEC-RAS {install['version']}, {_clock(result['seconds'])}"
    status, comment = _verdict(result, stamp, f"Computed with no errors in compute messages ({stamp}); {deps}")
    if status == "Y" and (result["exitCode"] != 0 or not result["planHdfUpdated"]):
        return "N", f"Exit code {result['exitCode']}, results file updated={result['planHdfUpdated']} ({stamp})"
    return status, comment


def _hms_run(call: Call, install: dict | None, project: dict, run: dict, opts: ReviewOptions, log: list, execute: bool) -> tuple[str | None, str]:
    deps = f"Run '{run['name']}' defined (basin={run['basin'] or '-'}, met={run['met'] or '-'}, control={run['control'] or '-'})"
    if not (run["basin"] and run["control"]):
        return "N", f"{deps}; run is missing a basin or control specification"
    if not execute:
        return None, f"{deps}. Run was not executed; confirm it computes."
    if install is None:
        return None, f"{deps}. No usable HEC-HMS install found on the VM; not executed."
    result = _execute(call, "hms", install["exe"], project["hms"], run["name"], "",
                      f"HEC-HMS {install['version']} · {project['name']} / {run['name']}", opts,
                      project["name"], run["name"])
    log.append({"tool": f"HEC-HMS {install['version']}", "project": project["name"], "plan": run["name"], **result})
    stamp = f"HEC-HMS {install['version']}, {_clock(result['seconds'])}"
    status, comment = _verdict(result, stamp, f"Computed with no errors ({stamp}); {deps}", "output")
    if status == "Y" and (result["exitCode"] != 0 or not result["freshDssFiles"]):
        return "N", f"Exit code {result['exitCode']}, fresh DSS results={result['freshDssFiles']} ({stamp})"
    return status, comment


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


@dataclass
class WorkUnit:
    """One plan (HEC-RAS) or simulation run (HEC-HMS) to test; the unit of work handed to a VM."""

    tool: str  # "ras" | "hms"
    project: dict
    unit: dict

    @property
    def label(self) -> str:
        return (f"{self.tool.upper()} {self.project.get('title') or self.project.get('name')} / "
                f"{self.unit.get('title') or self.unit.get('name')}")


@dataclass
class Discovery:
    """What ``inventory_*.ps1`` found under ``models_root``: projects, and the plans/runs to test in order."""

    ras_projects: list[dict]
    hms_projects: list[dict]
    units: list[WorkUnit]

    @property
    def inventory(self) -> dict[str, list[str]]:
        return {
            "ras": sorted(f"{p['title'] or p['base']}  ({p['prj']})" for p in self.ras_projects),
            "hms": sorted(f"{p['name']}  ({p['hms']})" for p in self.hms_projects),
        }


def pick_installs(software: dict, opts: ReviewOptions) -> dict[str, dict | None]:
    return {"ras": pick_install(software["installs"], "HEC-RAS", opts.ras_version),
            "hms": pick_install(software["installs"], "HEC-HMS", opts.hms_version)}


def discover(call: Call, opts: ReviewOptions) -> Discovery:
    """Scan ``models_root`` on one VM for HEC-RAS plans and HEC-HMS runs (HMS first, then RAS; read-only)."""
    say = opts.progress
    say(f"Scanning {opts.models_root} for HEC-RAS and HEC-HMS projects")
    ras_projects = call("inventory_ras.ps1", Root=opts.models_root)
    hms_projects = call("inventory_hms.ps1", Root=opts.models_root)
    units = [WorkUnit("hms", p, r) for p in hms_projects for r in p["runs"]]
    units += [WorkUnit("ras", p, pl) for p in ras_projects for pl in p["plans"]]
    say(f"Found {len(ras_projects)} HEC-RAS and {len(hms_projects)} HEC-HMS projects with {len(units)} plans/runs to test"
        + ("" if opts.run_models else " (not computing them: RUN_MODELS is off)"))
    return Discovery(ras_projects, hms_projects, units)


def evaluate_unit(call: Call, installs: dict[str, dict | None], work: WorkUnit, opts: ReviewOptions, geo: Any,
                  executions: list[dict]) -> ModelFinding:
    """Apply the three checklist tests to one plan/run on the VM behind ``call``."""
    return _evaluate(work.tool, call, installs[work.tool], work.project, work.unit, opts, geo, executions, opts.run_models)


def environment_summary(software: dict, installs: dict[str, dict | None], found: Discovery, opts: ReviewOptions,
                        findings: list[ModelFinding]) -> dict[str, Any]:
    return {
        "computer": software["computer"], "user": software["user"],
        "ras_install": installs["ras"]["version"] if installs["ras"] else None,
        "hms_install": installs["hms"]["version"] if installs["hms"] else None,
        "installs": [f"{i['product']} {i['version']}" for i in software["installs"]],
        "ras_projects_found": len(found.ras_projects), "hms_projects_found": len(found.hms_projects),
        "models_found": len(findings), "models_root": opts.models_root, "run_models": opts.run_models,
    }


def run_review(call: Call, opts: ReviewOptions, geo: Any = None) -> ReviewOutcome:
    """Apply the checklist tests (runs, events, project area) to every plan/run found under ``models_root``.

    Single-VM path: everything runs one after another through ``call``. ``rubric_review.fleet`` spreads the
    same work units across several VMs.
    """
    say = opts.progress
    say("Checking which HEC software is installed on the VM")
    software = call("inventory_software.ps1")
    found = discover(call, opts)
    installs = pick_installs(software, opts)

    executions: list[dict] = []
    findings: list[ModelFinding] = []
    if opts.status is not None:
        user_status = opts.status

        def counted(snapshot: RunStatus) -> None:
            snapshot.done, snapshot.total = len(findings), len(found.units)
            user_status(snapshot)
        opts = replace(opts, status=counted)
    for work in found.units:
        say(f"[{len(findings) + 1}/{len(found.units)}] Testing {work.label}")
        findings.append(evaluate_unit(call, installs, work, opts, geo, executions))
        say("    → " + "  ".join(f"{k}={s or 'REVIEW'}" for k, (s, _c, _f) in findings[-1].checks.items()))
    say("Review finished")
    return ReviewOutcome(environment_summary(software, installs, found, opts, findings), executions, found.inventory, findings)
