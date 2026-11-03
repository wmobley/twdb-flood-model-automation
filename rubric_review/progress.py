"""An in-place progress board for notebooks: an overall "N of M models complete" bar plus one row per VM that
updates instead of printing a line per poll.

Use it as both ``ReviewOptions.progress`` (event lines) and ``ReviewOptions.status`` (per-poll snapshots)::

    board = NotebookProgress()
    options = ReviewOptions(..., progress=board.say, status=board.status)

Outside IPython it degrades to printing: events are printed, snapshots are summarised one line per minute.
"""

from __future__ import annotations

import time
from html import escape

from .review import RunStatus

def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


class NotebookProgress:
    def __init__(self, keep_events: int = 12, min_interval: float = 0.5):
        self.rows: dict[str, RunStatus] = {}  # key: host (fleet) or label (single VM)
        self.done: int | None = None  # models complete / to test, from the latest snapshot
        self.total: int | None = None
        self.events: list[str] = []
        self.keep_events = keep_events
        self.min_interval = min_interval
        self._handle = None
        self._last_render = 0.0
        self._last_print = 0.0
        self._display, self._html = None, None
        try:
            from IPython.display import HTML, display  # noqa: WPS433 - optional dependency
            from IPython import get_ipython

            if get_ipython() is not None:
                self._display, self._html = display, HTML
        except Exception:  # noqa: BLE001 - not in IPython
            pass

    # ---- callbacks -----------------------------------------------------------------------------------------------
    def say(self, message: str) -> None:
        """Event line (started, finished, verdict, errors). Kept in a short rolling list under the table."""
        self.events.append(f"{time.strftime('%H:%M:%S')}  {message}")
        del self.events[: -self.keep_events]
        if self._display is None:
            print(message, flush=True)
        else:
            self._render(force=True)

    def status(self, snapshot: RunStatus) -> None:
        """Per-poll snapshot of one compute; replaces that VM's row."""
        key = snapshot.host or snapshot.label
        if snapshot.total is not None:
            self.done, self.total = snapshot.done, snapshot.total
            if snapshot.state == "finished":
                self.done = (self.done or 0) + 1  # this one just completed; the runner counts it after we return
        if snapshot.state == "running":
            self.rows[key] = snapshot
        else:
            self.rows.pop(key, None)
        if self._display is None:
            if time.monotonic() - self._last_print >= 60:
                self._last_print = time.monotonic()
                print(" | ".join(self._text_row(r) for r in self.rows.values()), flush=True)
        else:
            self._render()

    # ---- rendering -----------------------------------------------------------------------------------------------
    def _text_row(self, r: RunStatus) -> str:
        who = f"{r.host.split('.')[0]}: " if r.host else ""
        return f"{who}{r.unit} {_clock(r.seconds)} {r.stage}"

    def overall(self) -> str:
        if not self.total:
            return "counting models"
        pct = 100.0 * (self.done or 0) / self.total
        return f"{self.done or 0} of {self.total} models complete ({pct:.0f}%)"

    def render_html(self) -> str:
        pct = 100.0 * (self.done or 0) / self.total if self.total else 0.0
        header = (f"<div style='font:14px system-ui;margin-bottom:6px'><b>{escape(self.overall())}</b><br>"
                  f"<div style='background:#d8dee4;border-radius:4px;height:12px;width:420px;margin-top:4px'>"
                  f"<div style='background:#1a7f37;height:12px;border-radius:4px;width:{pct:.0f}%'></div></div></div>")
        rows = sorted(self.rows.values(), key=lambda r: (r.host or "", r.label))
        body = "".join(
            f"<tr><td><b>{escape((r.host or '').split('.')[0] or '-')}</b></td><td>{escape(r.project)}<br><small>{escape(r.unit)}</small></td>"
            f"<td>{escape(r.stage)}</td><td style='text-align:right'>{_clock(r.seconds)}</td><td><small>{escape(r.detail)}</small></td></tr>"
            for r in rows)
        if not body:
            body = "<tr><td colspan=5><i>no compute running</i></td></tr>"
        events = "".join(f"<div><code>{escape(e)}</code></div>" for e in reversed(self.events))
        return (header + "<table style='border-collapse:collapse;font:13px system-ui'><tr style='text-align:left'>"
                "<th>VM</th><th>Model / plan</th><th>Stage</th><th>Elapsed</th><th>Detail</th></tr>"
                f"<style>td,th{{padding:3px 10px;border-bottom:1px solid #d8dee4;vertical-align:top}}</style>{body}"
                f"</table><div style='margin-top:6px;font-size:12px;max-height:12em;overflow:auto'>{events}</div>")

    def _render(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_render < self.min_interval:
            return
        self._last_render = now
        html = self._html(self.render_html())
        if self._handle is None:
            self._handle = self._display(html, display_id=True)
        else:
            self._handle.update(html)
