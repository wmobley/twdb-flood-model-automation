"""Render a review outcome as a standalone, themed HTML report (narrative sections, not one flat table)."""

from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from .review import ModelFinding, ReviewOutcome

_BADGE = {"Y": ("Pass", "pass"), "N": ("Fail", "fail"), "N/A": ("N/A", "na"), None: ("Reviewer", "review")}
_KIND_TITLE = {"runs": "Runs without errors", "events": "Scope of Work events", "area": "Project area"}
_THEMES = (
    ("hms", "Hydrologic models (HEC-HMS)"),
    ("ras", "Hydraulic models (HEC-RAS)"),
)

_CSS = """
:root{--ink:#1b1f24;--muted:#5b6670;--line:#d8dee4;--pass:#1a7f37;--fail:#c4261d;--review:#9a6700;--bg:#fff;--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--ink:#e6edf3;--muted:#9aa5b1;--line:#30363d;--pass:#3fb950;--fail:#f85149;--review:#d29922;--bg:#0d1117;--card:#161b22}}
body{font:15px/1.55 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:980px;margin:2rem auto;padding:0 1rem}
h1{margin-bottom:.2rem} h2{margin-top:2.4rem;border-bottom:2px solid var(--line);padding-bottom:.3rem} h3{margin-top:1.6rem}
.meta{color:var(--muted)} .callout{background:var(--card);border-left:4px solid var(--review);padding:.7rem 1rem;margin:1rem 0}
.callout.fail{border-color:var(--fail)} .callout.pass{border-color:var(--pass)}
.badge{display:inline-block;font-size:.78rem;font-weight:600;padding:.05rem .5rem;border-radius:999px;border:1px solid currentColor;margin-right:.4rem}
.badge.pass{color:var(--pass)} .badge.fail{color:var(--fail)} .badge.review{color:var(--review)} .badge.na{color:var(--muted)}
.model{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:.7rem 1rem;margin:.8rem 0}
.model h4{margin:.1rem 0 .4rem} .model ul{margin:.2rem 0;padding-left:1.1rem} .model small{color:var(--muted)}
table.matrix{border-collapse:collapse} .matrix th,.matrix td{border:1px solid var(--line);padding:.3rem .7rem;text-align:center}
.matrix td:first-child,.matrix th:first-child{text-align:left} .yes{color:var(--pass)} .no{color:var(--fail)}
img{max-width:100%;border:1px solid var(--line);border-radius:4px;margin:.4rem 0}
pre{background:var(--card);padding:.6rem;overflow:auto;font-size:.8rem} details{margin:.3rem 0}
table.env{border-collapse:collapse} .env th,.env td{border-bottom:1px solid var(--line);padding:.25rem .8rem;text-align:left;vertical-align:top}
"""


def _badge(status: str | None) -> str:
    label, css = _BADGE[status]
    return f"<span class='badge {css}'>{label}</span>"


def _img(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return f"<img alt='project area map' width='520' src='data:image/png;base64,{data}'>"


def _summary(outcome: ReviewOutcome, root: str) -> str:
    findings = outcome.findings
    if not findings:
        found = outcome.inventory
        listing = "".join(f"<li>{escape(x)}</li>" for x in found.get("ras", []) + found.get("hms", [])) or "<li><i>nothing</i></li>"
        return (f"<div class='callout fail'><b>No HEC-RAS plans or HEC-HMS runs were found under</b> <code>{escape(root)}</code>, "
                f"so nothing could be tested. Projects detected:<ul>{listing}</ul>"
                "Point the notebook's models folder at the extracted submission (the folder that contains the "
                "<code>.prj</code> / <code>.hms</code> files).</div>")
    verdicts = Counter(f.verdict for f in findings)
    projects = len({(f.tool, f.project) for f in findings})
    text = (f"<p>The submission at <code>{escape(root)}</code> contains <b>{len(findings)}</b> plans/runs across "
            f"<b>{projects}</b> projects. <b>{verdicts['Y']}</b> meet every automated check, <b>{verdicts['N']}</b> fail at least one, "
            f"and <b>{verdicts[None]}</b> need a reviewer's judgement.</p>")
    if not outcome.environment.get("run_models"):
        text += ("<div class='callout'>Models were <b>not executed</b>: execution is judged from dependencies only. "
                 "Re-run with <code>RUN_MODELS = True</code> to compute each plan.</div>")
    return text


def _card(f: ModelFinding) -> str:
    lines = "".join(
        f"<li>{_badge(status)}<b>{_KIND_TITLE[kind]}.</b> {escape(comment)}</li>"
        for kind, (status, comment, _fig) in f.checks.items()
    )
    figures = "".join(_img(fig) for _s, _c, fig in f.checks.values())
    return (f"<div class='model'><h4>{escape(f.project)} <small>· {escape(f.unit)}</small> {_badge(f.verdict)}</h4>"
            f"<small><code>{escape(f.path)}</code></small><ul>{lines}</ul>{figures}</div>")


def _theme(outcome: ReviewOutcome, tool: str, title: str) -> str:
    findings = [f for f in outcome.findings if f.tool == tool]
    if not findings:
        return ""
    runs = Counter(f.checks["runs"][0] for f in findings)
    parts = [f"<h2>{escape(title)}</h2>",
             f"<p>{len(findings)} found. Execution: <b>{runs['Y']}</b> computed without errors, "
             f"<b>{runs['N']}</b> failed, <b>{runs[None]}</b> not decided automatically.</p>"]
    with_events = [f for f in findings if f.events]
    if with_events:
        events = list(dict.fromkeys(e for f in with_events for e in f.events))
        head = "".join(f"<th>{escape(e)}</th>" for e in events)
        body = "".join(
            f"<tr><td>{escape(f.project)} <small>· {escape(f.unit)}</small></td>"
            + "".join(f"<td class={'yes' if f.events.get(e) else 'no'}>{'✔' if f.events.get(e) else '✘'}</td>" for e in events)
            + "</tr>" for f in with_events)
        parts.append(f"<h3>Scope of Work events</h3><table class='matrix'><tr><th>Model / run</th>{head}</tr>{body}</table>")
    parts.append("<h3>Model-by-model findings</h3>")
    parts += [_card(f) for f in findings]
    return "".join(parts)


def write_html_report(outcome: ReviewOutcome, dest: str | Path, title: str, host: str) -> Path:
    dest = Path(dest)
    root = str(outcome.environment.get("models_root", ""))
    needs_review = [(f, _KIND_TITLE[k], c) for f in outcome.findings for k, (s, c, _) in f.checks.items() if s is None]
    review = ""
    if needs_review:
        items = "".join(f"<li><b>{escape(f.project)}</b> · {escape(f.unit)} — <i>{kind}</i>: {escape(c)}</li>" for f, kind, c in needs_review)
        review = f"<h2>Items for the reviewer</h2><p>These could not be decided automatically.</p><ul>{items}</ul>"
    runs = "".join(
        f"<details><summary>{escape(e['tool'])} — {escape(e['project'])} / {escape(e['plan'])}</summary>"
        f"<pre>{escape(e.get('messagesTail') or e.get('outputTail') or '')}</pre></details>"
        for e in outcome.executions
    )
    env = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in outcome.environment.items())
    inv = "".join(f"<li>{escape(x)}</li>" for x in outcome.inventory.get("hms", []) + outcome.inventory.get("ras", []))
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{_CSS}</style>
<h1>{escape(title)}</h1>
<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M} on {escape(host)}</p>
<h2>Summary</h2>{_summary(outcome, root)}
{''.join(_theme(outcome, tool, name) for tool, name in _THEMES)}
{review}
<h2>Appendix</h2>
<h3>Projects found in the submission</h3><ul>{inv or '<li><i>none</i></li>'}</ul>
<h3>Execution logs</h3>{runs or '<p>No models were executed.</p>'}
<h3>Environment</h3><table class="env">{env}</table>
</html>"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    return dest
