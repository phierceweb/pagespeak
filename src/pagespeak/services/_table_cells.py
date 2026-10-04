"""Pipe-table row → cells. A backslash-escaped pipe (`\\|`) is cell content, not a boundary."""

from __future__ import annotations

import re

_CELL_BOUNDARY_RE = re.compile(r"(?<!\\)\|")


def split_table_row(line: str) -> list[str]:
    """The unstripped cells of one pipe-table row, outer pipes dropped."""
    cells = _CELL_BOUNDARY_RE.split(line.strip())
    while cells and not cells[0]:
        cells.pop(0)
    while cells and not cells[-1]:
        cells.pop()
    return cells
