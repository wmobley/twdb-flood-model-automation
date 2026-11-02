"""Build a completed FPPG modeling checklist: the workbook is a template; one block is written per model found."""

from __future__ import annotations

from copy import copy
from pathlib import Path

import openpyxl

from .review import ModelFinding

SHEET = "C - Modeling Review"
FIRST_DATA_ROW = 4
BLOCK_ROWS = 3  # runs / events / area
LAST_COL = 10
ITEM_COL, CATEGORY_COL, TARGET_COL, TEXT_COL, INCLUDED_COL, COMMENT_COL = 1, 2, 3, 4, 5, 6
KINDS = ("runs", "events", "area")
_CATEGORY = {"hms": "Hydrologic Model", "ras": "Hydraulic Model"}


def _target(f: ModelFinding) -> str:
    if f.tool == "hms":
        return f"Model Name: {f.project}\n\nSimulation Run Name: {f.unit}\n\n"
    return f"Project Name: {f.project}\nPlan Name: {f.unit}"


def build_review_workbook(source: str | Path, dest: str | Path, findings: list[ModelFinding]) -> Path:
    """Copy the checklist template to ``dest`` with one 3-row block per finding.

    The template's example model names are discarded; its wording, columns and formatting are kept.
    Status ``None`` leaves "Included" blank for the reviewer and still writes the evidence comment.
    """
    wb = openpyxl.load_workbook(source)
    ws = wb[SHEET]
    first = FIRST_DATA_ROW

    texts = [ws.cell(first + i, TEXT_COL).value for i in range(BLOCK_ROWS)]
    styles = [[copy(ws.cell(first + i, c)._style) for c in range(1, LAST_COL + 1)] for i in range(BLOCK_ROWS)]
    heights = [ws.row_dimensions[first + i].height for i in range(BLOCK_ROWS)]

    guide_row = next((r for r in range(first, ws.max_row + 1)
                      if "guideline" in str(ws.cell(r, CATEGORY_COL).value or "").lower()), None)
    tail, tail_merges = [], []
    if guide_row:
        for r in range(guide_row, ws.max_row + 1):
            tail.append(([ws.cell(r, c).value for c in range(1, LAST_COL + 1)],
                         [copy(ws.cell(r, c)._style) for c in range(1, LAST_COL + 1)], ws.row_dimensions[r].height))
        tail_merges = [(m.min_col, m.max_col, m.min_row - guide_row, m.max_row - guide_row)
                       for m in ws.merged_cells.ranges if m.min_row >= guide_row]

    for rng in [m for m in ws.merged_cells.ranges if m.min_row >= first]:
        ws.unmerge_cells(str(rng))
    ws.delete_rows(first, ws.max_row - first + 1)

    for g, f in enumerate(findings):
        top = first + g * BLOCK_ROWS
        for i, kind in enumerate(KINDS):
            row = top + i
            for c in range(1, LAST_COL + 1):
                ws.cell(row, c)._style = copy(styles[i][c - 1])
            ws.row_dimensions[row].height = heights[i]
            status, comment, _figure = f.checks[kind]
            ws.cell(row, ITEM_COL).value = f"C{g * BLOCK_ROWS + i + 1}"
            ws.cell(row, TEXT_COL).value = texts[i]
            ws.cell(row, INCLUDED_COL).value = status
            ws.cell(row, COMMENT_COL).value = comment
        ws.cell(top, CATEGORY_COL).value = _CATEGORY[f.tool]
        ws.cell(top, TARGET_COL).value = _target(f)
        for col in (CATEGORY_COL, TARGET_COL):
            ws.merge_cells(start_row=top, end_row=top + BLOCK_ROWS - 1, start_column=col, end_column=col)

    start = first + len(findings) * BLOCK_ROWS + 1
    for offset, (values, row_styles, height) in enumerate(tail):
        for c in range(1, LAST_COL + 1):
            cell = ws.cell(start + offset, c)
            cell.value = values[c - 1]
            cell._style = copy(row_styles[c - 1])
        ws.row_dimensions[start + offset].height = height
    for min_col, max_col, min_off, max_off in tail_merges:
        ws.merge_cells(start_row=start + min_off, end_row=start + max_off, start_column=min_col, end_column=max_col)

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    return dest
