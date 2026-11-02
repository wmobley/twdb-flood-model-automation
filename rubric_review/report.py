"""Render a review outcome as a standalone HTML report."""

from __future__ import annotations

from collections import Counter
import os
from datetime import datetime
from html import escape
from pathlib import Path

from .review import ReviewOutcome

_LABEL = {"Y": "Pass", "N": "Fail", "N/A": "N/A", None: "Needs reviewer"}


def write_html_report(outcome: ReviewOutcome, dest: str | Path, title: str, host: str) -> Path:
    counts = Counter(r.status for r in outcome.results)
    dest = Path(dest)

    def evidence(r) -> str:
        img = f"<br><img src='{escape(os.path.relpath(r.figure, dest.parent).replace(os.sep, '/'))}' width='420'>" if r.figure else ""
        return escape(r.comment) + img

    rows = "\n".join(
        f"<tr class='s-{(r.status or 'review').replace('/', '')}'><td>{escape(r.item_no)}</td>"
        f"<td>{escape(r.model)}<br><small>{escape(r.run)}</small></td><td>{escape(r.kind)}</td>"
        f"<td><b>{_LABEL[r.status]}</b></td><td>{evidence(r)}</td></tr>"
        for r in outcome.results
    )
    runs = "\n".join(
        f"<details><summary>{escape(e['tool'])} — {escape(e['project'])} / {escape(e['plan'])}</summary>"
        f"<pre>{escape(e.get('messagesTail') or e.get('outputTail') or '')}</pre></details>"
        for e in outcome.executions
    )
    events = list(dict.fromkeys(e for row in outcome.events for e in row["found"]))  # Scope of Work order
    matrix = ""
    if events:
        head = "".join(f"<th>{escape(e)}</th>" for e in events)
        body = "".join(
            f"<tr><td>{escape(row['model'])}<br><small>{escape(row['run'])}</small></td>"
            + "".join(f"<td>{'✔' if row['found'].get(e) else '✘'}</td>" for e in events) + "</tr>"
            for row in outcome.events)
        matrix = f"<h2>Scope of Work events</h2><table><tr><th>Model / run</th>{head}</tr>{body}</table>"
    env = "\n".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in outcome.environment.items())
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{escape(title)}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}} th,td{{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;vertical-align:top}}
.s-Y td:nth-child(4){{color:#0a6b2d}} .s-N td:nth-child(4){{color:#b00020}} .s-review td:nth-child(4){{color:#8a5a00}}
pre{{background:#f4f4f4;padding:.6rem;overflow:auto}}
</style>
<h1>{escape(title)}</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} on <b>{escape(host)}</b>.
<b>{counts.get('Y', 0)}</b> pass · <b>{counts.get('N', 0)}</b> fail · <b>{counts.get(None, 0)}</b> need reviewer judgement.</p>
<table><tr><th>Item</th><th>Model / run</th><th>Check</th><th>Result</th><th>Evidence</th></tr>
{rows}</table>
{matrix}
<h2>Execution logs</h2>{runs or '<p>No models were executed.</p>'}
<h2>Environment</h2><table>{env}</table>
</html>"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    return dest
