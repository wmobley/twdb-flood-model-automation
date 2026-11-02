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


def _fake_call(ras_projects, hms_projects, run_result=None):
    ran = []

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
        return run_result
    call.ran = ran
    return call


OK = {"exitCode": 0, "timedOut": False, "planHdfUpdated": True, "errorLines": [], "seconds": 5,
      "messagesTail": "done", "freshDssFiles": 2, "outputTail": "done"}


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
    assert len(call.ran) == 1 and call.ran[0][1]["Exe"] == r"C:\ras\Ras.exe"  # preferred 6.6

    bad = {**OK, "errorLines": ["ERROR: negative depth"]}
    out = run_review(_fake_call([project], [], bad), ReviewOptions(models_root="x", run_models=True))
    status, comment, _ = out.findings[0].checks["runs"]
    assert status == "N" and "negative depth" in comment


def test_dependency_check_without_running():
    good = _ras_project("M", _plan("Plan"))
    broken = _ras_project("M", _plan("Plan", flow=False), shapes=[])
    assert run_review(_fake_call([good], []), ReviewOptions(models_root="x")).findings[0].checks["runs"][0] is None
    f = run_review(_fake_call([broken], []), ReviewOptions(models_root="x")).findings[0]
    assert (f.checks["runs"][0], f.checks["events"][0], f.checks["area"][0]) == ("N", "N", "N")


def test_hms_run_executes_with_hms_install():
    call = _fake_call([], [_hms_project("W", ["10-yr"])], OK)
    out = run_review(call, ReviewOptions(models_root="x", run_models=True))
    assert out.findings[0].checks["runs"][0] == "Y" and call.ran[0][1]["Cmd"] == r"C:\hms\hec-hms.cmd"


def test_event_matching_handles_return_periods_and_annual_chance():
    from rubric_review.events import find_events

    text = "Ray 10-yr | Q25yr | 50 year storm | 1% AEP | 2%"
    assert find_events(text, ["10-yr", "25-yr", "50-yr", "100-yr"]) == {"10-yr": True, "25-yr": True, "50-yr": True, "100-yr": True}
    assert find_events("100yr only", ["10-yr", "100-yr"]) == {"10-yr": False, "100-yr": True}  # 100yr is not 10yr


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


