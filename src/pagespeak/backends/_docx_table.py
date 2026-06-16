"""GFM table rendering for the structure-faithful DOCX backend.

python-docx flattens vMerge/gridSpan into a repeated-value rectangular
grid (a vMerge origin's text recurs in every spanned row). GFM has no
rowspan/colspan, so the grid is rendered AS-IS; the repetition is
intentional and RAG-friendly (each row self-contained). Row 0 is always
the header (GFM requires one; no w:tblHeader detection). Degrade-not-solve
for the rarer cases: an image-only cell -> "" (no per-cell image
extraction); a nested table inside a cell -> only the cell's direct
paragraph text (no recursion).
"""

from __future__ import annotations

from typing import Any

from ._docx_structured import _render_runs


def _render_cell(cell: Any) -> str:
    parts: list[str] = []
    for p in cell.paragraphs:
        s = _render_runs(p)
        if s:
            parts.append(s)
    text = "<br>".join(parts)
    text = text.replace("|", "\\|")
    return text.replace("\n", " ").replace("\r", " ")


def render_table(table: Any) -> list[str]:
    """Convert a python-docx Table to GFM lines (blank-padded block), or [] if
    the table has no columns/rows."""
    cols = len(table.columns)
    if cols == 0 or not table.rows:
        return []
    grid: list[list[str]] = []
    for row in table.rows:
        cells = [_render_cell(c) for c in row.cells]
        if len(cells) < cols:
            cells = cells + [""] * (cols - len(cells))
        elif len(cells) > cols:
            cells = cells[:cols]
        grid.append(cells)
    out: list[str] = [""]
    out.append("| " + " | ".join(grid[0]) + " |")
    out.append("| " + " | ".join(["---"] * cols) + " |")
    for r in grid[1:]:
        out.append("| " + " | ".join(r) + " |")
    out.append("")
    return out
