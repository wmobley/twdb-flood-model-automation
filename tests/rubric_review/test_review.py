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
