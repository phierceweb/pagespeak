"""Synthetic text lines and page records for the layout backend's logic tests.

A line mirrors what `_layout_lines.page_lines` returns: PDF page space (y up), a
cap height ``h``, one run per font.
"""

from __future__ import annotations

from typing import Any


def line(
    text: str,
    x0: float,
    base: float,
    *,
    font: str = "Times-Roman",
    h: float = 7.0,
    size: float = 11.0,
    x1: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    width = x1 if x1 is not None else x0 + 5.0 * len(text)
    return {
        "text": text,
        "x0": x0,
        "x1": width,
        "base": base,
        "y0": base - 2,
        "y1": base + h,
        "h": h,
        "xh": h * 0.7,
        "size": size,
        "font": font,
        "runs": [[font, text]],
        "xs": [x0 + 5.0 * i for i in range(len(text))],
        "soft_hyphen": False,
        **extra,
    }


def record(
    lines: list[dict[str, Any]],
    *,
    page: int = 2,
    rules: list[list[float]] | None = None,
    images: list[list[float]] | None = None,
    fills: list[list[Any]] | None = None,
) -> dict[str, Any]:
    return {
        "page": page,
        "size": [612.0, 792.0],
        "box": [0.0, 0.0, 612.0, 792.0],
        "lines": lines,
        "images": images or [],
        "fills": fills or [],
        "rules": rules or [],
        "art": [],
        "strokes": [],
        "slim": [],
    }


def grid_rules(xs: list[float], ys: list[float]) -> list[list[float]]:
    """The rules of a full grid: a horizontal at each y, a vertical at each x."""
    hs = [[xs[0], y - 0.25, xs[-1], y + 0.25] for y in ys]
    vs = [[x - 0.25, min(ys), x + 0.25, max(ys)] for x in xs]
    return hs + vs


def table(rows: list[list[str]], *, title: str | None = None) -> dict[str, Any]:
    """A ruled table float of `rows` (a full grid; a title row spanning it when `title` is given)."""
    from pagespeak.backends._layout_tables import find_tables

    ys = [500 - 20 * i for i in range(len(rows) + (2 if title else 1))]
    xs = [72 + 150 * c for c in range(len(rows[0]) + 1)]
    rules = grid_rules(xs, ys)
    lines = []
    if title:
        rules = [
            r for r in rules if not (r[1] > ys[1] and r[2] - r[0] < 2.5 and xs[0] < r[0] < xs[-1])
        ]
        lines.append(line(title, 80, ys[0] - 14))
    for r, row in enumerate(rows):
        top = ys[r + (1 if title else 0)]
        lines += [line(text, x + 8, top - 14) for x, text in zip(xs, row, strict=False) if text]
    (t,) = find_tables(record(lines, rules=rules), rules_below=700)
    return {"table": t}


def ruled(
    rows: list[list[str]],
    *,
    merged: tuple[tuple[int, int, int, int], ...] = (),
    shaded: tuple[tuple[int, int], ...] = (),
    extra: tuple[dict[str, Any], ...] = (),
    row_h: float = 20,
    top: float = 500,
) -> dict[str, Any]:
    """A ruled table float with merged cells: each `merged` block ``(row0, col0, row1, col1)`` is
    drawn as one cell (no rule inside it) and takes the text of its first cell. `shaded` cells
    are marked as the page's grey fills mark them; `extra` lines are added as given. Cell
    ``(r, c)`` spans x ``72 + 150c`` to ``222 + 150c`` and y ``top - row_h * (r + 1)`` to ``top - row_h * r``.
    """
    from pagespeak.backends._layout_tables import find_tables

    xs = [72 + 150 * c for c in range(len(rows[0]) + 1)]
    ys = [top - row_h * r for r in range(len(rows) + 1)]

    def block(r: int, c: int) -> tuple[int, int, int, int]:
        return next((m for m in merged if m[0] <= r <= m[2] and m[1] <= c <= m[3]), (r, c, r, c))

    rules, lines = [], []
    for r in range(len(rows)):
        for c in range(len(rows[0])):
            r0, c0, r1, c1 = block(r, c)
            if r == r0:
                rules.append([xs[c], ys[r] - 0.25, xs[c + 1], ys[r] + 0.25])
            if r == r1:
                rules.append([xs[c], ys[r + 1] - 0.25, xs[c + 1], ys[r + 1] + 0.25])
            if c == c0:
                rules.append([xs[c] - 0.25, ys[r + 1], xs[c] + 0.25, ys[r]])
            if c == c1:
                rules.append([xs[c + 1] - 0.25, ys[r + 1], xs[c + 1] + 0.25, ys[r]])
            if rows[r][c] and (r, c) == (r0, c0):
                lines.append(line(rows[r][c], xs[c] + 8, ys[r] - 14))
    (t,) = find_tables(record([*lines, *extra], rules=rules), rules_below=700)
    t["shaded"] = [
        k
        for k, cell in enumerate(t["cells"])
        if any(cell[4] <= r <= cell[5] and cell[6] <= c <= cell[7] for r, c in shaded)
    ]
    return {"table": t}
