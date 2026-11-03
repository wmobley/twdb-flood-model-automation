"""Spread one rubric review across several DYNAMO VMs.

The submission is staged at the same path on every VM; the plans/runs it contains are put in a queue and each VM
takes the next one as soon as it is free, so a review that takes hours on one VM finishes in roughly that time
divided by the number of VMs. Findings are merged back into a single ``ReviewOutcome`` in discovery order.
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .review import (Call, Discovery, ModelFinding, ReviewOptions, ReviewOutcome, ReviewStopped, RunStatus, WorkUnit,
                     discover, environment_summary, evaluate_unit, pick_installs)

DYNAMO_HOSTS = ["dynamo.tacc.utexas.edu"] + [f"dynamo{n:02d}.tacc.utexas.edu" for n in range(2, 9)]


def short_name(host: str) -> str:
    return host.split(".")[0]


@dataclass
class _Job:
    index: int
    work: WorkUnit
    attempts: int = 0


class Fleet:
    """A set of connected VM sessions (anything with ``run_script``, ``upload`` and ``close``), keyed by host name."""

    def __init__(self, sessions: dict[str, Any]):
        if not sessions:
            raise ValueError("Fleet needs at least one connected session")
        self.sessions = dict(sessions)

    @classmethod
    def connect_winrm(cls, hosts: list[str], username: str, password: str | None,
                      progress: Callable[[str], None] = print) -> "Fleet":
        """Log in to each host **in turn** with one attempt each.

        The first host must succeed before any other is tried: a wrong password tried on eight VMs is eight
        failed logins on the same domain account, which locks it. Later hosts that fail are skipped, not retried.
        """
        from .winrm import WinRMSession

        sessions: dict[str, Any] = {}
        for host in hosts:
            try:
                sessions[host] = WinRMSession(host, username, password).connect()
                progress(f"[{short_name(host)}] connected")
            except Exception as exc:  # noqa: BLE001 - we report and move on; never retry a login
                if not sessions:
                    raise RuntimeError(f"Login to {host} failed; not trying the other hosts (account lockout protection): {exc}") from exc
                progress(f"[{short_name(host)}] SKIPPED, could not connect: {str(exc)[:200]}")
        return cls(sessions)

    @property
    def hosts(self) -> list[str]:
        return list(self.sessions)

    @property
    def calls(self) -> dict[str, Call]:
        return {host: session.run_script for host, session in self.sessions.items()}

    def stage(self, local_zip: str | Path, dest: str, progress: Callable[[str], None] = print) -> str:
        """Upload the zip to every VM at once and extract it; returns the (identical) models root on the VMs."""
        local_zip = Path(local_zip)

        def one(host: str) -> dict:
            session = self.sessions[host]
            progress(f"[{short_name(host)}] uploading {local_zip.name} ({local_zip.stat().st_size / 1e6:.0f} MB)")
            started = time.monotonic()
            zip_on_vm = session.upload(local_zip, "models.zip")
            progress(f"[{short_name(host)}] upload done in {time.monotonic() - started:.0f}s; extracting")
            staged = session.run_script("stage_models.ps1", timeout=1800, Zip=zip_on_vm, Dest=dest)
            progress(f"[{short_name(host)}] extracted {staged['fileCount']} files to {staged['root']}")
            return staged

        with ThreadPoolExecutor(max_workers=len(self.sessions)) as pool:
            results = dict(zip(self.hosts, pool.map(one, self.hosts)))
        roots = {r["root"] for r in results.values()}
        counts = {r["fileCount"] for r in results.values()}
        if len(roots) != 1:
            raise RuntimeError(f"The models were extracted to different paths on different VMs: {sorted(roots)}")
        if len(counts) != 1:
            raise RuntimeError(f"The VMs extracted different numbers of files: " + ", ".join(
                f"{short_name(h)}={r['fileCount']}" for h, r in results.items()))
        return roots.pop()

    def close(self) -> None:
        for session in self.sessions.values():
            session.close()


def run_review_fleet(calls: dict[str, Call], opts: ReviewOptions, geo: Any = None) -> ReviewOutcome:
    """Like ``run_review`` but the plans/runs are shared out among the VMs behind ``calls``.

    * Discovery runs on the first VM; ``opts.models_root`` must hold the same files on every VM (use ``Fleet.stage``).
    * Each VM picks its own HEC-RAS / HEC-HMS install and only takes work it can run.
    * If a VM errors while testing a model, that model goes back in the queue once for another VM and the failed VM
      stops taking work. Anything still untested at the end is reported as a reviewer item, never dropped.
    * Interrupting (Ctrl-C) asks every VM to stop its current compute, then re-raises.
    """
    if not calls:
        raise ValueError("No VM sessions given")
    print_lock = threading.Lock()

    def say(message: str) -> None:  # one line at a time: eight threads printing at once otherwise interleave
        with print_lock:
            opts.progress(message)

    first = next(iter(calls))
    say(f"Distributing the review over {len(calls)} VM(s): {', '.join(short_name(h) for h in calls)}")
    software = {first: calls[first]("inventory_software.ps1")}
    found = discover(calls[first], opts)

    jobs: queue.Queue[_Job] = queue.Queue()
    for index, work in enumerate(found.units):
        jobs.put(_Job(index, work))
    stop = threading.Event()
    lock = threading.Lock()
    results: dict[int, ModelFinding] = {}
    executions: list[dict] = []
    installs_by_host: dict[str, dict] = {}
    host_errors: dict[str, str] = {}
    done_count = [0]
    workers_left = [len(calls)]
    all_done = threading.Event()

    def worker(host: str) -> None:
        try:
            _work(host)
        finally:
            with lock:
                workers_left[0] -= 1
                if workers_left[0] == 0:
                    all_done.set()

    def _work(host: str) -> None:
        tag = short_name(host)

        def host_status(snapshot: RunStatus, _host: str = host) -> None:
            snapshot.host = _host
            with lock:
                snapshot.done, snapshot.total = done_count[0], len(found.units)
            with print_lock:
                opts.status(snapshot)

        host_opts = replace(opts, progress=lambda m: say(f"[{tag}] {m}"), stopped=stop.is_set,
                            status=host_status if opts.status is not None else None)
        call = calls[host]
        try:
            if host not in software:
                software[host] = call("inventory_software.ps1")
            installs = pick_installs(software[host], opts)
            installs_by_host[host] = installs
        except Exception as exc:  # noqa: BLE001
            host_errors[host] = f"could not inventory software: {exc}"
            say(f"[{tag}] dropped: {host_errors[host]}")
            return
        skipped = 0
        while not stop.is_set():
            try:
                job = jobs.get_nowait()
            except queue.Empty:
                return
            if opts.run_models and installs[job.work.tool] is None:
                jobs.put(job)  # another VM may have that tool installed
                skipped += 1
                if skipped > jobs.qsize():
                    say(f"[{tag}] nothing left this VM can run (no usable HEC-{job.work.tool.upper()} install)")
                    return
                continue
            skipped = 0
            mine: list[dict] = []
            try:
                say(f"[{tag}] Testing {job.work.label}")
                finding = evaluate_unit(call, installs, job.work, host_opts, geo, mine)
            except ReviewStopped:
                return
            except Exception as exc:  # noqa: BLE001
                job.attempts += 1
                host_errors[host] = f"{job.work.label}: {exc}"
                say(f"[{tag}] ERROR on {job.work.label}: {str(exc)[:200]}")
                if job.attempts == 1:
                    jobs.put(job)
                    say(f"[{tag}] {job.work.label} returned to the queue for another VM; {tag} takes no more work")
                else:
                    jobs.put(job)  # leaves it for the final 'not tested' pass
                return
            finding.host = host
            for row in mine:
                row["host"] = host
            with lock:
                results[job.index] = finding
                executions.extend(mine)
                done_count[0] += 1
                n = done_count[0]
            say(f"[{tag}] [{n}/{len(found.units)}] {job.work.label} → "
                + "  ".join(f"{k}={s or 'REVIEW'}" for k, (s, _c, _f) in finding.checks.items()))

    threads = [threading.Thread(target=worker, args=(host,), name=short_name(host), daemon=True) for host in calls]
    try:
        for thread in threads:
            thread.start()
        # Wait on an Event in short steps so Ctrl-C in a notebook is noticed. Do NOT use Thread.join(timeout) here:
        # on Python <= 3.12 a KeyboardInterrupt raised inside join(timeout) marks the thread as already stopped
        # (bpo-45274), after which join() returns at once and the workers' stop requests would never be awaited.
        while not all_done.wait(0.5):
            pass
    except BaseException:
        stop.set()
        say("Stopping: asking every VM to end its current compute")
        all_done.wait()
        raise
    for thread in threads:
        thread.join()

    leftovers: list[_Job] = []
    while True:
        try:
            leftovers.append(jobs.get_nowait())
        except queue.Empty:
            break
    for job in leftovers:
        if job.index in results:
            continue
        why = "; ".join(f"{short_name(h)}: {e}" for h, e in host_errors.items()) or "no VM could run it"
        comment = f"Not tested: every VM that tried failed or none could run it ({why}). Re-run this model."
        results[job.index] = ModelFinding(job.work.tool, job.work.project.get("title") or job.work.project.get("name") or "",
                                          job.work.unit.get("title") or job.work.unit.get("name") or "",
                                          job.work.unit.get("file") or job.work.project.get("hms") or "",
                                          {"runs": (None, comment, None), "events": (None, comment, None), "area": (None, comment, None)})
    findings = [results[i] for i in sorted(results)]
    say("Review finished")

    environment = environment_summary(software[first], pick_installs(software[first], opts), found, opts, findings)
    environment["hosts"] = [
        f"{short_name(h)}: HEC-RAS {(installs_by_host.get(h) or {}).get('ras') and installs_by_host[h]['ras']['version'] or '-'}, "
        f"HEC-HMS {(installs_by_host.get(h) or {}).get('hms') and installs_by_host[h]['hms']['version'] or '-'}, "
        f"{sum(1 for f in findings if f.host == h)} plans/runs tested"
        + (f" (error: {host_errors[h][:120]})" if h in host_errors else "")
        for h in calls
    ]
    environment["computer"] = ", ".join(short_name(h) for h in calls)
    return ReviewOutcome(environment, executions, found.inventory, findings)
