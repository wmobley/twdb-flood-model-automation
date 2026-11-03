"""The fleet runner shares plans/runs among several VMs and merges the findings back into one outcome."""

import threading

import pytest

from rubric_review import Fleet, ReviewOptions, run_review_fleet, write_html_report
from rubric_review.fleet import DYNAMO_HOSTS, short_name

from test_review import BUSY, OK, _fake_call, _hms_project, _plan, _ras_project

HOSTS = ["dynamo.tacc.utexas.edu", "dynamo02.tacc.utexas.edu", "dynamo03.tacc.utexas.edu"]


def _models(n_ras=6, hms_runs=("10-yr", "100-yr")):
    return [_ras_project(f"M{i}", _plan(f"P{i}")) for i in range(n_ras)], [_hms_project("W", list(hms_runs))]


def _fleet_calls(hosts, ras, hms, **kw):
    """One independent fake VM per host (each with its own call log), all holding the same staged models."""
    return {h: _fake_call(ras, hms, **kw) for h in hosts}


def test_hosts_list_and_short_names():
    assert DYNAMO_HOSTS[0] == "dynamo.tacc.utexas.edu" and DYNAMO_HOSTS[-1] == "dynamo08.tacc.utexas.edu" and len(DYNAMO_HOSTS) == 8
    assert short_name("dynamo05.tacc.utexas.edu") == "dynamo05" and short_name("dynamo.tacc.utexas.edu") == "dynamo"


def test_every_unit_is_tested_once_across_hosts_in_discovery_order():
    ras, hms = _models()
    calls = _fleet_calls(HOSTS, ras, hms, run_result=OK, polls=[BUSY] * 8)  # each compute is "busy" for one poll
    out = run_review_fleet(calls, ReviewOptions(models_root=r"C:\m", run_models=True, poll_seconds=0.05))
    labels = [(f.tool, f.project, f.unit) for f in out.findings]
    assert labels == [("hms", "W", "10-yr"), ("hms", "W", "100-yr")] + [("ras", f"M{i}", f"P{i}") for i in range(6)]
    starts = {h: [p["Unit"] for name, p in c.ran if name == "start_run.ps1"] for h, c in calls.items()}
    assert sum(len(v) for v in starts.values()) == 8 and len([h for h, v in starts.items() if v]) > 1  # really shared out
    assert all(f.host in HOSTS for f in out.findings) and all(f.checks["runs"][0] == "Y" for f in out.findings)
    assert len(out.executions) == 8 and all(e["host"] in HOSTS for e in out.executions)
    assert out.environment["computer"] == "dynamo, dynamo02, dynamo03" and len(out.environment["hosts"]) == 3
    assert all("plans/runs tested" in line for line in out.environment["hosts"])


def test_single_host_fleet_matches_sequential_review():
    from rubric_review import run_review

    ras, hms = _models(2)
    solo = run_review(_fake_call(ras, hms), ReviewOptions(models_root="x"))
    fleet = run_review_fleet({"h": _fake_call(ras, hms)}, ReviewOptions(models_root="x"))
    assert [f.checks for f in solo.findings] == [f.checks for f in fleet.findings]
    assert fleet.inventory == solo.inventory and fleet.environment["models_found"] == solo.environment["models_found"]


def test_failing_host_hands_its_model_to_another_vm_and_stops_taking_work():
    ras, hms = _models(4, ())
    calls = _fleet_calls(HOSTS[:2], ras, hms, run_result=OK, polls=[BUSY] * 4)
    good, bad = calls.values()

    def flaky(script, timeout=None, **params):
        if script == "start_run.ps1":
            raise RuntimeError("WinRM connection dropped")
        return bad(script, timeout, **params)
    flaky.ran = bad.ran
    calls[HOSTS[1]] = flaky

    messages = []
    out = run_review_fleet(calls, ReviewOptions(models_root="x", run_models=True, poll_seconds=0.02, progress=messages.append))
    assert len(out.findings) == 4 and all(f.checks["runs"][0] == "Y" for f in out.findings)
    assert all(f.host == HOSTS[0] for f in out.findings)  # the bad VM contributed nothing usable
    assert sorted(p["Unit"] for n, p in good.ran if n == "start_run.ps1") == [f"C:\\m\\P{i}.p01" for i in range(4)]  # order depends on timing
    assert any("returned to the queue" in m for m in messages)
    assert any("error: " in line and "dynamo02" in line for line in out.environment["hosts"])


def test_models_nobody_could_test_are_reported_not_dropped():
    ras, hms = _models(2, ())

    def broken(script, timeout=None, **params):
        if script == "start_run.ps1":
            raise RuntimeError("boom")
        return _fake_call(ras, hms)(script, timeout, **params)

    out = run_review_fleet({"a": broken, "b": broken}, ReviewOptions(models_root="x", run_models=True, poll_seconds=0))
    assert len(out.findings) == 2
    assert all(f.verdict is None and "Not tested" in f.checks["runs"][1] for f in out.findings)
    assert all(f.project == f"M{i}" and f.unit == f"P{i}" for i, f in enumerate(out.findings))


def test_host_without_hms_only_takes_ras_work():
    ras, hms = _models(2, ("10-yr",))
    with_both = _fake_call(ras, hms, run_result=OK)
    ras_only_base = _fake_call(ras, hms, run_result=OK)

    def ras_only(script, timeout=None, **params):
        if script == "inventory_software.ps1":
            sw = ras_only_base(script)
            return {**sw, "installs": [i for i in sw["installs"] if i["product"] == "HEC-RAS"]}
        return ras_only_base(script, timeout, **params)
    ras_only.ran = ras_only_base.ran

    out = run_review_fleet({"both": with_both, "rasonly": ras_only}, ReviewOptions(models_root="x", run_models=True, poll_seconds=0))
    hms_findings = [f for f in out.findings if f.tool == "hms"]
    assert hms_findings and all(f.host == "both" for f in hms_findings)
    assert all(p["Kind"] == "ras" for n, p in ras_only.ran if n == "start_run.ps1")
    assert all(f.checks["runs"][0] == "Y" for f in out.findings)


def test_interrupt_stops_the_compute_on_every_vm():
    ras, hms = _models(2, ())
    calls = _fleet_calls(HOSTS[:2], ras, hms, run_result=OK, polls=[BUSY] * 1000)
    first, second = calls.values()
    both_polling = threading.Barrier(2)

    def wrap(c):
        def call(script, timeout=None, **params):
            if script == "poll_run.ps1" and not getattr(call, "seen", False):
                call.seen = True
                both_polling.wait(timeout=5)
            return c(script, timeout, **params)
        call.ran = c.ran
        return call
    calls = {h: wrap(c) for h, c in calls.items()}

    def interrupt_main():
        both_polling.wait(timeout=5)  # third party: lets both workers pass, then interrupts the main thread
        import _thread
        _thread.interrupt_main()
    both_polling = threading.Barrier(3)
    threading.Thread(target=interrupt_main, daemon=True).start()
    with pytest.raises(KeyboardInterrupt):
        run_review_fleet(calls, ReviewOptions(models_root="x", run_models=True, poll_seconds=0.05))
    assert ("stop_run.ps1", {"ProcessId": 4242}) in first.ran and ("stop_run.ps1", {"ProcessId": 4242}) in second.ran


def test_report_names_the_vm_that_tested_each_model(tmp_path):
    ras, hms = _models(1, ())
    out = run_review_fleet(_fleet_calls(HOSTS[:1], ras, hms, run_result=OK), ReviewOptions(models_root="x", run_models=True, poll_seconds=0))
    html = write_html_report(out, tmp_path / "r.html", "T", "dynamo fleet").read_text()
    assert "tested on dynamo" in html and "(dynamo)" in html and "plans/runs tested" in html


# ---- Fleet sessions --------------------------------------------------------------------------------------------

class FakeSession:
    def __init__(self, host, root=r"C:\Users\dynamo\rubric-review\models", count=12, fail=False):
        self.host, self.root, self.count, self.fail, self.closed, self.uploaded = host, root, count, fail, False, []

    def connect(self):
        if self.fail:
            raise RuntimeError("login refused")
        return self

    def run_script(self, name, timeout=None, **params):
        assert name == "stage_models.ps1" and params["Zip"] == "rubric-review\\models.zip"
        return {"root": self.root, "fileCount": self.count}

    def upload(self, local, remote_name):
        self.uploaded.append((str(local), remote_name))
        return f"rubric-review\\{remote_name}"

    def close(self):
        self.closed = True


def test_stage_uploads_to_every_vm_and_checks_they_agree(tmp_path):
    zip_path = tmp_path / "models.zip"
    zip_path.write_bytes(b"zip")
    sessions = {h: FakeSession(h) for h in HOSTS}
    fleet = Fleet(sessions)
    assert fleet.stage(zip_path, "rubric-review\\models", progress=lambda m: None) == r"C:\Users\dynamo\rubric-review\models"
    assert all(s.uploaded == [(str(zip_path), "models.zip")] for s in sessions.values())
    assert set(fleet.calls) == set(HOSTS)
    fleet.close()
    assert all(s.closed for s in sessions.values())

    sessions[HOSTS[2]].count = 11
    with pytest.raises(RuntimeError, match="different numbers of files"):
        Fleet(sessions).stage(zip_path, "rubric-review\\models", progress=lambda m: None)
    sessions[HOSTS[2]].count = 12
    sessions[HOSTS[2]].root = r"D:\elsewhere"
    with pytest.raises(RuntimeError, match="different paths"):
        Fleet(sessions).stage(zip_path, "rubric-review\\models", progress=lambda m: None)


def test_connect_stops_at_first_host_if_its_login_fails(monkeypatch):
    import rubric_review.fleet as fleet_mod

    attempts = []

    def fake_session(host, username, password):
        attempts.append(host)
        return FakeSession(host, fail=(host == HOSTS[0]))
    monkeypatch.setattr("rubric_review.winrm.WinRMSession", fake_session)
    with pytest.raises(RuntimeError, match="lockout"):
        fleet_mod.Fleet.connect_winrm(HOSTS, "u", "p", progress=lambda m: None)
    assert attempts == [HOSTS[0]]  # the other VMs were never tried


def test_connect_skips_a_later_host_that_fails(monkeypatch):
    import rubric_review.fleet as fleet_mod

    monkeypatch.setattr("rubric_review.winrm.WinRMSession", lambda host, u, p: FakeSession(host, fail=(host == HOSTS[1])))
    messages = []
    fleet = fleet_mod.Fleet.connect_winrm(HOSTS, "u", "p", progress=messages.append)
    assert fleet.hosts == [HOSTS[0], HOSTS[2]] and any("SKIPPED" in m for m in messages)


def test_fleet_tags_status_snapshots_with_the_host_and_suppresses_poll_text():
    ras, hms = _models(2, ())
    snaps, messages = [], []
    calls = _fleet_calls(HOSTS[:2], ras, hms, run_result=OK, polls=[BUSY] * 2)
    run_review_fleet(calls, ReviewOptions(models_root="x", run_models=True, poll_seconds=0.02, progress=messages.append, status=snaps.append))
    assert snaps and all(s.host in HOSTS[:2] for s in snaps)
    assert {s.state for s in snaps} == {"running", "finished"} and all(s.total == 2 for s in snaps)
    assert max(s.done for s in snaps) >= 1  # the later snapshots see the earlier completions
    assert not any("running 0:20" in m for m in messages)
