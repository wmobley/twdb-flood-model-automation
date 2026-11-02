"""Match Scope of Work events (e.g. "25-yr", "1%") against model text."""

from __future__ import annotations

import re

_RETURN_PERIOD = re.compile(r"(\d+)[\s_\-]*(?:yr|year)s?", re.I)


def _patterns(event: str) -> list[re.Pattern]:
    m = _RETURN_PERIOD.fullmatch(event.strip())
    if not m:
        return [re.compile(re.escape(event.strip()), re.I)]
    years = int(m.group(1))
    pct = 100 / years
    pct_text = str(int(pct)) if pct == int(pct) else f"{pct:.1f}".rstrip("0").rstrip(".")
    return [
        re.compile(rf"(?<!\d){years}[\s_\-]*(?:yr|year)s?\b", re.I),
        re.compile(rf"(?<![\d.]){re.escape(pct_text)}\s*(?:%|percent|[\s_\-]*pct)", re.I),
    ]


def find_events(text: str, events: list[str]) -> dict[str, bool]:
    return {event: any(p.search(text) for p in _patterns(event)) for event in events}
