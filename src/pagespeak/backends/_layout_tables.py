"""Layout backend: ruled tables, read from their drawn grid.

A table is a connected set of straight rules (horizontal and vertical) that frames text.
Its cells come from the grid of rule positions, merged wherever the separating rule is
missing (spanning cells), so merged and nested cells need no guessing from the text.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

TOL = 1.6
Rule = tuple[Any, ...]


def _norm(
    rules: list[list[float]],
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    hs, vs = [], []
    for x0, y0, x1, y1 in rules:
        if y1 - y0 < 2.5 and x1 - x0 >= 5:
            hs.append((x0, x1, (y0 + y1) / 2))
        elif x1 - x0 < 2.5 and y1 - y0 >= 5:
            vs.append(((x0 + x1) / 2, y0, y1))
    return hs, vs


def _hit_box(it: Rule) -> tuple[float, float, float, float]:
    if it[0] == "h":
        return (it[1] - TOL, it[3] - TOL, it[2] + TOL, it[3] + TOL)
    return (it[1] - TOL, it[2] - TOL, it[1] + TOL, it[3] + TOL)


def components(rules: list[list[float]], cell: int = 24) -> list[list[Rule]]:
    """Group rules that touch into connected sets (a spatial hash keeps it fast on line-art pages)."""
    hs, vs = _norm(rules)
    items: list[Rule] = [("h", *h) for h in hs] + [("v", *v) for v in vs]
    boxes = [_hit_box(it) for it in items]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                grid[(gx, gy)].append(i)
    for bucket in grid.values():
        for a in range(len(bucket)):
            i = bucket[a]
            bi = boxes[i]
            for b in range(a + 1, len(bucket)):
                j = bucket[b]
                bj = boxes[j]
                if bi[0] <= bj[2] and bj[0] <= bi[2] and bi[1] <= bj[3] and bj[1] <= bi[3]:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
    groups: dict[int, list[Rule]] = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    return list(groups.values())


def _levels(values: list[float], tol: float = TOL) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def _covers(segs: list[tuple[float, float]], lo: float, hi: float) -> bool:
    return sum(max(0, min(b, hi) - max(a, lo)) for a, b in segs) >= 0.6 * (hi - lo)


def grid(comp: list[Rule]) -> list[list[Any]]:
    """Cells of one connected rule set: ``[x0, y0, x1, y1, row0, row1, col0, col1]``, rows counted from the top."""
    hs = [it[1:] for it in comp if it[0] == "h"]
    vs = [it[1:] for it in comp if it[0] == "v"]
    # a column border drawn a little apart from row to row
    xs = _levels([v[0] for v in vs], tol=4.0)
    ys = sorted(_levels([h[2] for h in hs]), reverse=True)
    if len(xs) < 2 or len(ys) < 2:
        return []
    vat: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for x, y0, y1 in vs:
        vat[min(range(len(xs)), key=lambda i: abs(xs[i] - x))].append((y0, y1))
    hat: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for x0, x1, y in hs:
        hat[min(range(len(ys)), key=lambda i: abs(ys[i] - y))].append((x0, x1))
    rows, cols = len(ys) - 1, len(xs) - 1
    parent = {(r, c): (r, c) for r in range(rows) for c in range(cols)}

    def find(u: tuple[int, int]) -> tuple[int, int]:
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for r in range(rows):
        for c in range(cols - 1):
            if not _covers(vat[c + 1], ys[r + 1], ys[r]):
                parent[find((r, c))] = find((r, c + 1))
    for c in range(cols):
        for r in range(rows - 1):
            if not _covers(hat[r + 1], xs[c], xs[c + 1]):
                parent[find((r, c))] = find((r + 1, c))
    groups: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for u in parent:
        groups[find(u)].append(u)
    cells = []
    for us in groups.values():
        r0, r1 = min(u[0] for u in us), max(u[0] for u in us)
        c0, c1 = min(u[1] for u in us), max(u[1] for u in us)
        cells.append([xs[c0], ys[r1 + 1], xs[c1 + 1], ys[r0], r0, r1, c0, c1])
    return sorted(cells, key=lambda c: (c[4], c[6]))


def _drawn_blanks(
    rec: dict[str, Any], cells: list[list[Any]], held: list[list[dict[str, Any]]]
) -> None:
    """A writing line drawn inside a cell, clear of its borders, becomes a blank in that cell."""
    for s in rec.get("strokes", []):
        if s[3] - s[1] > 1.3 or s[2] - s[0] < 20:
            continue
        k = next(
            (
                i
                for i, c in enumerate(cells)
                if c[0] + 2 < s[0] and s[2] < c[2] - 2 and c[1] + 2 < s[1] < c[3] - 2
            ),
            None,
        )
        if k is None or any(
            ln["x0"] < s[2]
            and s[0] < ln["x1"]
            and (0 <= ln["y0"] - s[3] < 4 or ("__" in ln["text"] and abs(ln["base"] - s[1]) < 5))
            for ln in held[k]
        ):
            continue  # an underline, or a blank the text layer already gives as underscores
        held[k].append(
            {
                "text": "____________",
                "x0": s[0],
                "x1": s[2],
                "y0": s[1] - 1,
                "y1": s[3] + 1,
                "base": s[1],
                "font": "rule",
                "runs": [["rule", "____________"]],
                "h": 0,
                "drawn": True,
            }
        )


def _frame(hs: list[Rule], vs: list[Rule]) -> list[float]:
    x0 = min(min(h[1] for h in hs), min(v[1] for v in vs))
    x1 = max(max(h[2] for h in hs), max(v[1] for v in vs))
    y0 = min(min(h[3] for h in hs), min(v[2] for v in vs))
    y1 = max(max(h[3] for h in hs), max(v[3] for v in vs))
    return [x0, y0, x1, y1]


def find_tables(
    rec: dict[str, Any], *, rules_below: float, min_text: int = 2
) -> list[dict[str, Any]]:
    """Ruled tables on a page: frame, cells, and the lines each cell holds.

    Rules at or above `rules_below` (a running head's bars) are not a table.
    """
    lines = rec["lines"]
    out = []
    for comp in components([r for r in rec["rules"] if r[1] < rules_below]):
        hs = [it for it in comp if it[0] == "h"]
        vs = [it for it in comp if it[0] == "v"]
        if len(hs) < 2 or len(vs) < 2:
            continue
        long_h = [h for h in hs if h[2] - h[1] >= 40]
        long_v = [v for v in vs if v[2] - v[1] >= 40]
        if len(long_h) < 2 and len(long_v) < 2:  # a table set sideways has its long rules upright
            continue
        x0, y0, x1, y1 = _frame(hs, vs)
        if x1 - x0 < 50 or y1 - y0 < 15:
            continue
        cells = grid(comp)
        if not cells:
            continue
        inside = [
            ln
            for ln in lines
            if x0 - 1 <= (ln["x0"] + ln["x1"]) / 2 <= x1 + 1
            and y0 - 1 <= (ln["y0"] + ln["y1"]) / 2 <= y1 + 1
        ]
        if len(inside) < min_text:
            continue
        held: list[list[dict[str, Any]]] = [[] for _ in cells]
        for ln in inside:
            cx, cy = (ln["x0"] + ln["x1"]) / 2, (ln["y0"] + ln["y1"]) / 2
            k = next(
                (
                    i
                    for i, c in enumerate(cells)
                    if c[0] - 1 <= cx <= c[2] + 1 and c[1] - 1 <= cy <= c[3] + 1
                ),
                None,
            )
            if k is not None:
                held[k].append(ln)
        _drawn_blanks(rec, cells, held)
        rows, cols = max(c[5] for c in cells) + 1, max(c[7] for c in cells) + 1
        if (cols > 12 and len(inside) < 0.5 * len(cells)) or (
            x1 - x0 < 140 and y1 - y0 < 70 and len(inside) <= 3
        ):
            continue  # line art drawn in strokes, or a box of a flow chart
        kind = "box" if len(cells) == 1 else "table"
        out.append(
            {
                "frame": [x0, y0, x1, y1],
                "cells": cells,
                "held": held,
                "rows": rows,
                "cols": cols,
                "kind": kind,
            }
        )
    return out
