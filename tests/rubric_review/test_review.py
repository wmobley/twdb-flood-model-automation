from pathlib import Path

import openpyxl
import pytest

from rubric_review import ReviewOptions, build_review_workbook, run_review, write_html_report

WORKBOOK = Path(__file__).parents[2] / "docs/rubrics/FPPG_Project_Deliverables Checklist_FINAL.xlsx"


def _plan(title, geom=True, flow=True, flow_text=""):
    return {"file": rf"C:\m\{title}.p01", "ext": "p01", "title": title, "shortId": "", "geomFile": "g01", "geomExists": geom,
            "flowFile": "f01", "flowExists": flow, "flowTitle": "Flow 1", "flowText": flow_text}


def _ras_project(title, plan, shapes=None):
    return {"prj": rf"C:\m\{title}.prj", "dir": r"C:\m", "base": title, "title": title, "rasmapExists": True,
            "plans": [plan], "shapefiles": shapes if shapes is not None else [{"ref": r".\Features\Area.shp", "exists": True}]}


def _hms_project(name, run_names):
    runs = [{"name": n, "basin": "b", "met": "m", "control": "c"} for n in run_names]
    return {"hms": rf"C:\m\{name}.hms", "dir": r"C:\m", "name": name, "runs": runs,
            "shapefiles": [{"ref": "a.shp", "source": "x"}], "shpOnDisk": ["a.shp"]}


def _fake_call(ras_projects, hms_projects, run_result=None, polls=None):
    """``polls`` = states returned by successive poll_run.ps1 calls; the last is the finished ``run_result``."""
    ran = []
    pending = list(polls or [])

    def call(script, timeout=None, **params):
        if script == "inventory_software.ps1":
            return {"computer": "DYNAMO02", "user": "dynamo", "installs": [
                {"product": "HEC-RAS", "version": "6.6", "path": "x", "exe": r"C:\ras\Ras.exe", "exeExists": True},
                {"product": "HEC-RAS", "version": "7.0.2", "path": "x", "exe": r"C:\ras7\Ras.exe", "exeExists": True},
                {"product": "HEC-HMS", "version": "4.12", "path": "x", "exe": r"C:\hms\hec-hms.cmd", "exeExists": True}]}
        if script == "inventory_ras.ps1":
            return ras_projects
        if script == "inventory_hms.ps1":
            return hms_projects
        ran.append((script, params))
        if script == "start_run.ps1":
            return {"runDir": r"C:\tmp\run", "processId": 4242, "startedUtc": "2026-11-03T00:00:00.0000000Z", "projectDir": r"C:\m"}
        if script == "poll_run.ps1":
            return pending.pop(0) if pending else run_result
        return {"stopped": True}
    call.ran = ran
    return call


OK = {"running": False, "exitCode": 0, "planHdfUpdated": True, "errorLines": [], "seconds": 5, "lastFile": "", "lastFileAgo": None,
      "processes": [], "progressTail": [], "messagesTail": "done", "freshDssFiles": 2}
BUSY = {**OK, "running": True, "exitCode": None, "seconds": 20, "lastFile": "a.hdf", "lastFileAgo": 3,
        "processes": ["Ras.exe (cpu 7s)"], "progressTail": ["Step 12 of 40"]}


def test_every_model_found_is_tested_whatever_it_is_called():
    ras = [_ras_project("Totally Different Name", _plan("Scenario X")), _ras_project("Another", _plan("P2"))]
    hms = [_hms_project("Some_Other_Watershed", ["a", "b"])]
    out = run_review(_fake_call(ras, hms), ReviewOptions(models_root=r"C:\m"))
    assert [(f.tool, f.project, f.unit) for f in out.findings] == [
        ("hms", "Some_Other_Watershed", "a"), ("hms", "Some_Other_Watershed", "b"),
        ("ras", "Totally Different Name", "Scenario X"), ("ras", "Another", "P2")]
    assert all(set(f.checks) == {"runs", "events", "area"} for f in out.findings)


def test_nothing_found_gives_empty_findings():
    out = run_review(_fake_call([], []), ReviewOptions(models_root=r"C:\m"))
    assert out.findings == [] and out.environment["models_found"] == 0


def test_ras_run_pass_and_fail_paths():
    project = _ras_project("M", _plan("Plan"))
    call = _fake_call([project], [], OK)
    out = run_review(call, ReviewOptions(models_root="x", run_models=True))
    assert out.findings[0].checks["runs"][0] == "Y"
    assert [name for name, _ in call.ran] == ["start_run.ps1", "poll_run.ps1"] and call.ran[0][0] == "start_run.ps1" and call.ran[0][1]["Exe"] == r"C:\ras\Ras.exe"  # preferred 6.6

    bad = {**OK, "errorLines": ["ERROR: negative depth"]}
    out = run_review(_fake_call([project], [], bad), ReviewOptions(models_root="x", run_models=True))
    status, comment, _ = out.findings[0].checks["runs"]
    assert status == "N" and "negative depth" in comment


def test_compute_is_polled_without_a_time_limit_and_reports_progress():
    messages = []
    call = _fake_call([_ras_project("M", _plan("Plan"))], [], OK, polls=[BUSY, BUSY, BUSY])
    out = run_review(call, ReviewOptions(models_root="x", run_models=True, poll_seconds=0, progress=messages.append))
    assert out.findings[0].checks["runs"][0] == "Y"
    assert [name for name, _ in call.ran].count("poll_run.ps1") == 4  # three busy, one finished
    assert any("running 0:20" in m and "Ras.exe (cpu 7s)" in m and "Step 12 of 40" in m for m in messages)
    assert any("[1/1] Testing RAS" in m for m in messages) and any("finished after 0:05" in m for m in messages)


def test_poll_log_is_written_when_a_log_dir_is_given(tmp_path):
    call = _fake_call([_ras_project("M", _plan("Plan"))], [], OK, polls=[BUSY])
    run_review(call, ReviewOptions(models_root="x", run_models=True, poll_seconds=0, log_dir=tmp_path / "logs"))
    (log,) = (tmp_path / "logs").glob("*.jsonl")
    rows = [__import__("json").loads(line) for line in log.read_text().splitlines()]
    assert [r["running"] for r in rows] == [True, False] and rows[0]["lastFile"] == "a.hdf"
    assert all(params["Probe"] == 1 for name, params in call.ran if name == "poll_run.ps1")


def test_interrupting_a_compute_stops_the_vm_process():
    call = _fake_call([_ras_project("M", _plan("Plan"))], [], OK, polls=[BUSY])
    original = call

    def interrupting(script, timeout=None, **params):
        if script == "poll_run.ps1" and len([r for r in original.ran if r[0] == "poll_run.ps1"]) == 1:
            raise KeyboardInterrupt
        return original(script, timeout, **params)

    interrupting.ran = original.ran
    with pytest.raises(KeyboardInterrupt):
        run_review(interrupting, ReviewOptions(models_root="x", run_models=True, poll_seconds=0))
    assert ("stop_run.ps1", {"ProcessId": 4242}) in original.ran


def test_process_ending_without_exit_code_is_left_to_the_reviewer():
    gone = {**OK, "exitCode": None}
    out = run_review(_fake_call([_ras_project("M", _plan("Plan"))], [], gone), ReviewOptions(models_root="x", run_models=True, poll_seconds=0))
    assert out.findings[0].checks["runs"][0] is None


def test_dependency_check_without_running():
    good = _ras_project("M", _plan("Plan"))
    broken = _ras_project("M", _plan("Plan", flow=False), shapes=[])
    assert run_review(_fake_call([good], []), ReviewOptions(models_root="x")).findings[0].checks["runs"][0] is None
    f = run_review(_fake_call([broken], []), ReviewOptions(models_root="x")).findings[0]
    assert (f.checks["runs"][0], f.checks["events"][0], f.checks["area"][0]) == ("N", "N", "N")


def test_hms_run_executes_with_hms_install():
    call = _fake_call([], [_hms_project("W", ["10-yr"])], OK)
    out = run_review(call, ReviewOptions(models_root="x", run_models=True))
    assert out.findings[0].checks["runs"][0] == "Y" and call.ran[0][1]["Exe"] == r"C:\hms\hec-hms.cmd"


def test_event_matching_handles_return_periods_and_annual_chance():
    from rubric_review.events import find_events

    text = "Ray 10-yr | Q25yr | 50 year storm | 1% AEP | 2%"
    assert find_events(text, ["10-yr", "25-yr", "50-yr", "100-yr"]) == {"10-yr": True, "25-yr": True, "50-yr": True, "100-yr": True}
    assert find_events("100yr only", ["10-yr", "100-yr"]) == {"10-yr": False, "100-yr": True}  # 100yr is not 10yr


def test_event_matching_reads_zero_padded_annual_chance_profiles():
    from rubric_review.events import find_events

    names = "50%_ACE,10%_ACE,04%_ACE,02%_ACE,01%_ACE,0.02%_ACE"
    found = find_events(names, ["10-yr", "25-yr", "50-yr", "100-yr", "500-yr"])
    assert found == {"10-yr": True, "25-yr": True, "50-yr": True, "100-yr": True, "500-yr": False}  # 0.02% is 5000-yr


def test_hms_events_need_a_run_for_every_expected_event():
    hms = [_hms_project("W", ["10-yr", "25yr", "100yr"])]
    opts = ReviewOptions(models_root="x", expected_events=["10-yr", "25-yr", "50-yr", "100-yr"])
    f = run_review(_fake_call([], hms), opts).findings[0]
    assert f.checks["events"][0] == "N" and "50-yr" in f.checks["events"][1]
    assert f.events == {"10-yr": True, "25-yr": True, "50-yr": False, "100-yr": True}


def test_ras_events_read_plan_and_flow_text():
    project = _ras_project("M", _plan("Plan", flow_text="Profile Names=10-yr,25-yr,100-yr"))
    f = run_review(_fake_call([project], []), ReviewOptions(models_root="x", expected_events=["10-yr", "25-yr", "100-yr"])).findings[0]
    assert f.checks["events"][0] == "Y"
    f = run_review(_fake_call([project], []), ReviewOptions(models_root="x", expected_events=["10-yr", "50-yr"])).findings[0]
    assert f.checks["events"][0] == "N" and "50-yr" in f.checks["events"][1]


def test_project_area_shapefile_name_is_enforced():
    project = _ras_project("M", _plan("Plan"))
    run = lambda name: run_review(_fake_call([project], []), ReviewOptions(models_root="x", project_area_shapefile=name)).findings[0].checks["area"][0]
    assert run("GrantArea.shp") == "N" and run("area.shp") == "Y"


class FakeGeo:
    def __init__(self, status):
        self.status = status

    def check_ras(self, project, plan):
        from rubric_review.geo import GeoResult
        return GeoResult(self.status, "geo comment", "fig.png")


def test_area_requires_both_footprint_and_rasmap_layer():
    layer = _ras_project("M", _plan("Plan"))
    nolayer = _ras_project("M", _plan("Plan"), shapes=[])
    area = lambda proj, geo: run_review(_fake_call([proj], []), ReviewOptions(models_root="x"), geo=geo).findings[0].checks["area"]
    assert area(layer, FakeGeo("Y"))[0] == "Y" and area(layer, FakeGeo("Y"))[2] == "fig.png"
    assert area(layer, FakeGeo("N"))[0] == "N"
    assert area(nolayer, FakeGeo("Y"))[0] == "N"
    assert area(layer, FakeGeo(None))[0] == "Y"  # footprint unavailable: falls back to the map-layer check


def test_workbook_gets_one_block_per_model_and_keeps_template_wording(tmp_path):
    ras = [_ras_project(f"Model {i}", _plan("Plan")) for i in range(1, 5)]  # 4 + 1 hms = 5 blocks (template example has 10)
    out = run_review(_fake_call(ras, [_hms_project("W", ["10-yr"])]), ReviewOptions(models_root="x"))
    path = build_review_workbook(WORKBOOK, tmp_path / "filled.xlsx", out.findings)
    ws = openpyxl.load_workbook(path)["C - Modeling Review"]
    assert [ws.cell(r, 1).value for r in range(4, 19)] == [f"C{i}" for i in range(1, 16)]
    assert ws["B4"].value == "Hydrologic Model" and "Simulation Run Name: 10-yr" in ws["C4"].value
    assert ws["B7"].value == "Hydraulic Model" and "Project Name: Model 1" in ws["C7"].value
    assert ws["D4"].value == "Model runs with no errors" and ws["E4"].value is None  # not executed -> reviewer decides
    assert ws["D6"].value.startswith("Project Area")
    assert ws["A19"].value is None and "guideline" in str(ws["B20"].value).lower()  # tail kept, example blocks gone
    assert all("Example" not in str(c.value) and "Ray Watershed" not in str(c.value) for row in ws.iter_rows() for c in row)


def test_report_is_themed_and_handles_empty_and_populated(tmp_path):
    empty = write_html_report(run_review(_fake_call([], []), ReviewOptions(models_root="C:/x")), tmp_path / "e.html", "Test <report>", "h").read_text()
    assert "Test &lt;report&gt;" in empty and "No HEC-RAS plans or HEC-HMS runs were found" in empty

    project = _ras_project("M", _plan("Plan", flow_text="Profile Names=10-yr"))
    out = run_review(_fake_call([project], [_hms_project("W", ["10-yr"])]), ReviewOptions(models_root="C:/m", expected_events=["10-yr", "100-yr"]))
    html = write_html_report(out, tmp_path / "r.html", "T", "h").read_text()
    for needle in ("Hydrologic models (HEC-HMS)", "Hydraulic models (HEC-RAS)", "Model-by-model findings",
                   "Runs without errors", "Scope of Work events", "Items for the reviewer", "✘"):
        assert needle in html


# ---- Project-area footprint -----------------------------------------------------------------------------------

def _make_geometry(tmp_path, perimeter):
    import h5py
    import numpy as np

    hdf = tmp_path / "M.g01.hdf"
    with h5py.File(hdf, "w") as f:
        f.create_group("Geometry/2D Flow Areas/Area1").create_dataset("Perimeter", data=np.array(perimeter, float))
    return hdf


def _area_shapefile(tmp_path, box):
    import geopandas as gpd
    from shapely.geometry import box as shp_box

    path = tmp_path / "GrantArea.shp"
    gpd.GeoDataFrame({"id": [1]}, geometry=[shp_box(*box)]).to_file(path)
    return path


def test_footprint_coverage_pass_fail_and_figure(tmp_path):
    pytest.importorskip("geopandas")
    pytest.importorskip("h5py")
    from rubric_review.geo import LocalGeo

    _make_geometry(tmp_path, [(0, 0), (100, 0), (100, 100), (0, 100)])
    project = {"dir": str(tmp_path), "base": "M"}
    plan = {"geomFile": "g01", "title": "Plan 1"}

    inside = LocalGeo(_area_shapefile(tmp_path, (10, 10, 90, 90)), tmp_path / "fig").check_ras(project, plan)
    assert inside.status == "Y" and "100%" in inside.comment and Path(inside.figure).exists()

    partial = LocalGeo(_area_shapefile(tmp_path, (50, 50, 150, 150)), tmp_path / "fig").check_ras(project, plan)
    assert partial.status == "N" and "25%" in partial.comment

    missing = LocalGeo(_area_shapefile(tmp_path, (0, 0, 1, 1)), tmp_path).check_ras({"dir": str(tmp_path), "base": "X"}, plan)
    assert missing.status is None




# ---- WinRM session --------------------------------------------------------------------------------------------

def test_winrm_run_script_quotes_parameters_and_parses_json(monkeypatch):
    from rubric_review.winrm import WinRMSession

    sent = []

    class FakeClient:
        def execute_ps(self, script):
            sent.append(script)
            return '{"ok": true}', type("S", (), {"error": []})(), False

    session = WinRMSession("h", "u", "p")
    session._client = FakeClient()
    assert session.run_script("inventory_ras.ps1", Root=r"C:\My Models\it's") == {"ok": True}
    assert sent[0].startswith("& {") and sent[0].rstrip().endswith(r"-Root 'C:\My Models\it''s'")
    with pytest.raises(ValueError):
        session.run_script("inventory_ras.ps1", Root='x"; calc')


def test_winrm_remote_errors_raise(monkeypatch):
    from rubric_review.winrm import WinRMSession

    class BadClient:
        def execute_ps(self, script):
            return "", type("S", (), {"error": ["boom"]})(), True

    session = WinRMSession("h", "u", "p")
    session._client = BadClient()
    with pytest.raises(RuntimeError, match="boom"):
        session.run_script("inventory_software.ps1")


# ---- Progress snapshots -----------------------------------------------------------------------------------------

def test_status_callback_gets_snapshots_with_model_counts_instead_of_per_poll_text():
    from rubric_review import RunStatus

    snaps, messages = [], []
    busy = {**BUSY, "processes": ["RasUnsteady.exe (cpu 7s)"]}
    project = _ras_project("M", _plan("P1"))
    project["plans"].append(_plan("P2"))
    call = _fake_call([project], [], OK, polls=[busy, OK, busy])
    run_review(call, ReviewOptions(models_root="x", run_models=True, poll_seconds=0, progress=messages.append, status=snaps.append))
    assert [(s.unit, s.state, s.done, s.total) for s in snaps] == [
        ("P1", "running", 0, 2), ("P1", "finished", 0, 2), ("P2", "running", 1, 2), ("P2", "finished", 1, 2)]
    first = snaps[0]
    assert isinstance(first, RunStatus) and first.project == "M" and first.tool == "ras" and first.stage == "unsteady flow"
    assert "last file a.hdf" in first.detail and snaps[1].exit_code == 0
    assert not any("running 0:20" in m for m in messages)  # per-poll text suppressed
    assert any("finished after" in m for m in messages)  # events still reported


def test_stage_comes_from_the_running_hec_process():
    from rubric_review.review import _stage

    assert _stage({"processes": ["conhost.exe (cpu 0s)", "RasProcess.exe (cpu 2s)"], "lastFile": ""}) == "preprocessing geometry"
    assert _stage({"processes": ["java.exe (cpu 9s)"], "lastFile": ""}) == "computing"
    assert _stage({"processes": ["conhost.exe (cpu 0s)"], "lastFile": "M.p01.hdf"}) == "writing results"
    assert _stage({"processes": [], "lastFile": ""}) == "starting"


def test_notebook_progress_shows_models_complete_and_one_row_per_vm():
    from rubric_review import NotebookProgress, RunStatus

    board = NotebookProgress()
    board._display = None  # force the non-IPython path even if pytest runs under IPython
    board.say("dynamo02 started")
    board.status(RunStatus("L", "ras", "M", "Plan A", 95, "running", "unsteady flow", "last file x", host="dynamo02.tacc.utexas.edu", done=3, total=14))
    board.status(RunStatus("L2", "ras", "M", "Plan B", 10, "running", "starting", "", host="dynamo03.tacc.utexas.edu", done=3, total=14))
    html = board.render_html()
    assert "3 of 14 models complete (21%)" in html and "width:21%" in html
    assert "dynamo02" in html and "Plan A" in html and "1:35" in html and "unsteady flow" in html
    assert "dynamo03" in html and "Plan B" in html and "dynamo02 started" in html
    board.status(RunStatus("L", "ras", "M", "Plan A", 120, "finished", "finished", "", 0, host="dynamo02.tacc.utexas.edu", done=3, total=14))
    html = board.render_html()
    assert "Plan A" not in html and "4 of 14 models complete" in html  # finished rows leave the table and count up
