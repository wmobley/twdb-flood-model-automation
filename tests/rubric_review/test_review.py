from pathlib import Path

import openpyxl
import pytest

from rubric_review import ReviewOptions, fill_workbook, load_modeling_checklist, run_review, write_html_report

WORKBOOK = Path(__file__).parents[2] / "docs/rubrics/FPPG_Project_Deliverables Checklist_FINAL.xlsx"


def _plan(title, geom=True, flow=True):
    return {"file": rf"C:\m\{title}.p01", "ext": "p01", "title": title, "shortId": "", "geomFile": "g01", "geomExists": geom,
            "flowFile": "f01", "flowExists": flow, "flowTitle": "Flow 1"}


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


def _ras_project(title, plan, shapes=None):
    return {"prj": rf"C:\m\{title}.prj", "dir": r"C:\m", "base": title, "title": title, "rasmapExists": True,
            "plans": [plan], "shapefiles": shapes if shapes is not None else [{"ref": r".\Features\Area.shp", "exists": True}]}


def test_checklist_parses_all_thirty_items_in_ten_groups():
    groups = load_modeling_checklist(WORKBOOK)
    assert len(groups) == 10 and sum(len(g.items) for g in groups) == 30
    first = groups[0]
    assert (first.tool, first.model_name, first.run_name) == ("hms", "P921 01 Ray Watershed Studyv3 2 21 25", "10-yr")
    assert [i.kind for i in first.items] == ["runs", "events", "area"] and first.items[0].row == 4
    assert groups[4].tool == "ras" and groups[4].model_name == "HEC-RAS Model (Outfall A - Existing)"


def test_missing_project_fails_every_item_with_reason():
    groups = load_modeling_checklist(WORKBOOK)
    out = run_review(_fake_call([], []), groups, ReviewOptions(models_root=r"C:\m"))
    assert {r.status for r in out.results} == {"N"} and "No HEC-HMS project" in out.results[0].comment


def test_ras_run_pass_and_fail_paths():
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.model_name.endswith("(Outfall A - Existing)")]
    project = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario"))
    ok = {"exitCode": 0, "timedOut": False, "planHdfUpdated": True, "errorLines": [], "seconds": 5, "messagesTail": "done"}
    call = _fake_call([project], [], ok)
    out = run_review(call, groups, ReviewOptions(models_root=r"C:\m", run_models=True))
    assert [r.status for r in out.results] == ["Y", None, "Y"]
    assert len(call.ran) == 1 and call.ran[0][1]["Exe"] == r"C:\ras\Ras.exe"  # preferred 6.6, computed once per group

    bad = {**ok, "errorLines": ["ERROR: negative depth"]}
    out = run_review(_fake_call([project], [], bad), groups, ReviewOptions(models_root=r"C:\m", run_models=True))
    assert out.results[0].status == "N" and "negative depth" in out.results[0].comment


def test_dependency_check_without_running_leaves_reviewer_decision():
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.model_name.endswith("(Outfall A - Existing)")]
    good = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario"))
    broken = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario", flow=False), shapes=[])
    assert run_review(_fake_call([good], []), groups, ReviewOptions(models_root="x")).results[0].status is None
    out = run_review(_fake_call([broken], []), groups, ReviewOptions(models_root="x"))
    assert [r.status for r in out.results] == ["N", "N", "N"]


def test_project_area_shapefile_name_is_enforced():
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.model_name.endswith("(Outfall A - Existing)")]
    project = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario"))
    opts = ReviewOptions(models_root="x", project_area_shapefile="GrantArea.shp")
    assert run_review(_fake_call([project], []), groups, opts).results[2].status == "N"
    opts = ReviewOptions(models_root="x", project_area_shapefile="area.shp")
    assert run_review(_fake_call([project], []), groups, opts).results[2].status == "Y"


def test_fill_workbook_and_report(tmp_path):
    groups = load_modeling_checklist(WORKBOOK)
    out = run_review(_fake_call([], []), groups, ReviewOptions(models_root="x"))
    results = {r.row: (r.status, r.comment) for r in out.results}
    filled = fill_workbook(WORKBOOK, tmp_path / "filled.xlsx", results)
    ws = openpyxl.load_workbook(filled)["C - Modeling Review"]
    assert ws["E4"].value == "N" and "No HEC-HMS project" in ws["F4"].value
    assert ws["D4"].value == "Model runs with no errors"  # source columns untouched
    html = write_html_report(out, tmp_path / "r.html", "Test <report>", "dynamo02").read_text()
    assert "Test &lt;report&gt;" in html and "30" not in html.split("<h1>")[0]


def test_unsafe_remote_argument_rejected():
    pytest.importorskip("paramiko")
    from rubric_review.remote import _check_arg

    with pytest.raises(ValueError):
        _check_arg('C:\\x" ; calc')
    assert _check_arg(r"C:\Users\dynamo\My Models") == r"C:\Users\dynamo\My Models"


# ---- Scope of Work events -------------------------------------------------------------------------------------

def test_event_matching_handles_return_periods_and_annual_chance():
    from rubric_review.events import find_events

    text = "Ray 10-yr | Q25yr | 50 year storm | 1% AEP | 2%"
    assert find_events(text, ["10-yr", "25-yr", "50-yr", "100-yr"]) == {"10-yr": True, "25-yr": True, "50-yr": True, "100-yr": True}
    assert find_events("100yr only", ["10-yr", "100-yr"]) == {"10-yr": False, "100-yr": True}  # 100yr is not 10yr


def test_hms_events_need_a_run_for_every_expected_event():
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.tool == "hms"][:1]
    runs = [{"name": n, "basin": "b", "met": "m", "control": "c"} for n in ("10-yr", "25yr", "100yr")]
    hms = [{"hms": r"C:\m\p.hms", "dir": r"C:\m", "name": "P921_01_Ray_Watershed_Studyv3_2_21_25", "runs": runs, "shapefiles": [], "shpOnDisk": []}]
    opts = ReviewOptions(models_root="x", expected_events=["10-yr", "25-yr", "50-yr", "100-yr"])
    out = run_review(_fake_call([], hms), groups, opts)
    events_item = out.results[1]
    assert events_item.status == "N" and "50-yr" in events_item.comment
    assert out.events[0]["found"] == {"10-yr": True, "25-yr": True, "50-yr": False, "100-yr": True}


def test_ras_events_read_plan_and_flow_text_and_report_matrix(tmp_path):
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.model_name.endswith("(Outfall A - Existing)")]
    plan = {**_plan("Default Scenario"), "flowText": "Flow Title=Existing\nProfile Names=10-yr,25-yr,100-yr"}
    project = _ras_project("HEC-RAS Model (Outfall A - Existing)", plan)
    opts = ReviewOptions(models_root="x", expected_events=["10-yr", "25-yr", "100-yr"])
    out = run_review(_fake_call([project], []), groups, opts)
    assert out.results[1].status == "Y"
    opts = ReviewOptions(models_root="x", expected_events=["10-yr", "50-yr"])
    out = run_review(_fake_call([project], []), groups, opts)
    assert out.results[1].status == "N" and "50-yr" in out.results[1].comment
    html = write_html_report(out, tmp_path / "r.html", "t", "h").read_text()
    assert "Scope of Work events" in html and "✘" in html


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


def test_area_item_requires_both_footprint_and_rasmap_layer():
    groups = [g for g in load_modeling_checklist(WORKBOOK) if g.model_name.endswith("(Outfall A - Existing)")]

    class FakeGeo:
        def __init__(self, status):
            self.status = status

        def check_ras(self, project, plan):
            from rubric_review.geo import GeoResult
            return GeoResult(self.status, "geo comment", "fig.png")

    layer = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario"))
    nolayer = _ras_project("HEC-RAS Model (Outfall A - Existing)", _plan("Default Scenario"), shapes=[])
    run = lambda proj, geo: run_review(_fake_call([proj], []), groups, ReviewOptions(models_root="x"), geo=geo).results[2]
    assert run(layer, FakeGeo("Y")).status == "Y" and run(layer, FakeGeo("Y")).figure == "fig.png"
    assert run(layer, FakeGeo("N")).status == "N"
    assert run(nolayer, FakeGeo("Y")).status == "N"
    assert run(layer, FakeGeo(None)).status == "Y"  # footprint unavailable: falls back to the map-layer check
