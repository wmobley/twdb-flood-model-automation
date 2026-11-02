"""Read the TWDB FPPG modeling checklist workbook and write review results back into it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

SHEET = "C - Modeling Review"
FIRST_DATA_ROW = 4
ITEM_COL, CATEGORY_COL, TARGET_COL, TEXT_COL = 1, 2, 3, 4
INCLUDED_COL, COMMENT_COL = 5, 6  # "TWDB PM Draft Review"

_ITEM_NO = re.compile(r"^C\d+$")
_MODEL = re.compile(r"(?:Model|Project) Name:\s*(.+)")
_RUN = re.compile(r"(?:Simulation Run|Plan) Name:\s*(.+)")


@dataclass(frozen=True)
class ChecklistItem:
    item_no: str
    row: int
    text: str
    kind: str  # "runs" | "events" | "area" | "other"


@dataclass
class ChecklistGroup:
    """One model/plan with its checklist items (three rows in the FPPG workbook)."""

    category: str  # "Hydrologic Model" (HEC-HMS) or "Hydraulic Model" (HEC-RAS)
    model_name: str
    run_name: str
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def tool(self) -> str:
        return "hms" if self.category.lower().startswith("hydrologic") else "ras"


def _kind(text: str) -> str:
    lowered = text.lower()
    if "runs with no errors" in lowered:
        return "runs"
    if "events" in lowered:
        return "events"
    if "project area" in lowered:
        return "area"
    return "other"


def load_modeling_checklist(path: str | Path) -> list[ChecklistGroup]:
    ws = openpyxl.load_workbook(path)[SHEET]
    groups: list[ChecklistGroup] = []
    category = ""
    for row in range(FIRST_DATA_ROW, ws.max_row + 1):
        item_no = ws.cell(row, ITEM_COL).value
        if not (isinstance(item_no, str) and _ITEM_NO.match(item_no.strip())):
            continue
        category = ws.cell(row, CATEGORY_COL).value or category
        target = ws.cell(row, TARGET_COL).value
        if target:
            model = _MODEL.search(target)
            run = _RUN.search(target)
            if not (model and run):
                raise ValueError(f"{SHEET}!C{row}: cannot parse model/run names from {target!r}")
            groups.append(ChecklistGroup(category.strip(), model.group(1).strip(), run.group(1).strip()))
        if not groups:
            raise ValueError(f"{SHEET}!A{row}: checklist item appears before any model/run header")
        text = str(ws.cell(row, TEXT_COL).value or "").strip()
        groups[-1].items.append(ChecklistItem(item_no.strip(), row, text, _kind(text)))
    return groups


def fill_workbook(source: str | Path, dest: str | Path, results: dict[int, tuple[str | None, str]]) -> Path:
    """Copy ``source`` to ``dest`` writing ``{row: (Y/N/N/A/None, comment)}`` into the PM Draft Review columns.

    Rows with a ``None`` status are left unanswered for the reviewer; only the comment is written.
    """
    wb = openpyxl.load_workbook(source)
    ws = wb[SHEET]
    for row, (status, comment) in results.items():
        if status is not None:
            ws.cell(row, INCLUDED_COL).value = status
        ws.cell(row, COMMENT_COL).value = comment
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    return dest
