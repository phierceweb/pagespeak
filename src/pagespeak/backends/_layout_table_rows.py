"""Layout backend: a ruled table's rows — its title, header, notes and group columns found,
its body read row by row (sub-rows, ticked items and spanning rows apart)."""

from __future__ import annotations

import re
from typing import Any

from ._layout_cells import cell_items, header_text, rotate
from ._layout_profile import LayoutProfile
from ._layout_text import INDENT_STEP

Row = tuple[Any, ...]


def _pitch(held: list[list[dict[str, Any]]]) -> float | None:
    """The table's line spacing: the tightest step that recurs between lines of one cell."""
    steps: list[float] = []
    for h in held:
        bs = sorted(
            (ln["base"] for ln in h if not ln.get("drawn") and not ln.get("vertical")), reverse=True
        )
        steps += [
            round(2 * (a - b)) / 2 for a, b in zip(bs, bs[1:], strict=False) if 3 < a - b < 30
        ]
    return min([s for s in set(steps) if steps.count(s) >= 2] or steps or [0]) or None


def prepare(f: dict[str, Any], prof: LayoutProfile) -> dict[str, Any]:
    t = f["table"]
    vert = sum(1 for h in t["held"] for ln in h if ln.get("vertical"))
    sideways = vert > sum(len(h) for h in t["held"]) / 2
    if sideways:
        t = rotate(t)
    held = t["held"]
    pitch = _pitch(held)
    parts = [cell_items(h, prof, pitch) for h in held]
    rows: dict[int, list[int]] = {}
    for k, c in enumerate(t["cells"]):
        rows.setdefault(c[4], []).append(k)
    return {
        "t": t,
        "cells": t["cells"],
        "held": held,
        "ncol": t["cols"],
        "parts": parts,
        "sideways": sideways,
        "texts": ["<br>".join(x for x, _ in p) for p in parts],
        "rows": rows,
        "order": sorted(rows),
    }


def head(tb: dict[str, Any], prof: LayoutProfile) -> None:
    """The title row, the header row (the first row in capitals; a note may sit above it), the group columns."""
    cells, held, texts, rows, order = tb["cells"], tb["held"], tb["texts"], tb["rows"], tb["order"]
    title_k = next(
        (
            k
            for k in rows.get(order[0], [])
            if any(prof.table_title.match(ln["text"]) for ln in held[k])
        ),
        None,
    )
    tb["title"] = header_text(held[title_k], prof) if title_k is not None else None
    body_rows = [r for r in order if not (title_k is not None and r == order[0])]
    header, notes = None, []
    for i, r0 in enumerate(body_rows[:3]):
        letters = re.sub(r"[^A-Za-z]", "", " ".join(ln["text"] for k in rows[r0] for ln in held[k]))
        if (
            letters
            and letters.isupper()
            and len(rows[r0]) >= 2
            and all(cells[k][4] == cells[k][5] for k in rows[r0])
        ):
            header = r0
            notes = [texts[k] for r in body_rows[:i] for k in rows[r] if texts[k]]
            body_rows = body_rows[i + 1 :]
            break
    group_cols = []
    for c in range(tb["ncol"]):  # columns that only hold sideways group labels become section rows
        ks = [k for k, cc in enumerate(cells) if cc[6] == c and cc[4] in body_rows and held[k]]
        if ks and all(any(ln.get("vertical") for ln in held[k]) for k in ks) and not tb["sideways"]:
            group_cols.append(c)
    data_cols = [c for c in range(tb["ncol"]) if c not in group_cols] or [0]
    names = [""] * len(data_cols)
    for k in rows.get(header, []) if header is not None else []:
        covered = [i for i, c in enumerate(data_cols) if cells[k][6] <= c <= cells[k][7]]
        if covered:
            names[covered[0]] = header_text(held[k], prof)
    tb.update(
        body_rows=body_rows,
        header=header,
        notes=notes,
        group_cols=group_cols,
        data_cols=data_cols,
        names=names,
    )


def key_column(tb: dict[str, Any]) -> None:
    cells, held, body_rows, key = tb["cells"], tb["held"], tb["body_rows"], tb["data_cols"][0]
    mains = sorted(
        (k for k, c in enumerate(cells) if c[6] <= key <= c[7] and c[4] in body_rows),
        key=lambda k: cells[k][4],
    )
    key_x = min((ln["x0"] for k in mains for ln in held[k] if not ln.get("vertical")), default=0)
    left = min((cells[k][0] for k in mains), default=0)
    shaded = set(tb["t"].get("shaded", []))
    spans: list[list[int]] = []
    for k in mains:
        if spans and not tb["texts"][k] and k in shaded:
            spans[-1][2] = cells[k][5]  # a grey filler under a key: more rows of the same key
        else:
            spans.append([k, cells[k][4], cells[k][5]])
    # terms set flush left, so an indent is a level (centred terms have none)
    tb.update(mains=mains, key_x=key_x, flush=key_x - left < 10, shaded=shaded, spans=spans)


def _home(tb: dict[str, Any], j: int) -> int | None:
    return next((c for c in tb["data_cols"] if tb["cells"][j][6] <= c <= tb["cells"][j][7]), None)


def _sub_rows(
    tb: dict[str, Any],
    k: int,
    split: list[int],
    per: dict[int, list[int]],
    starts: list[int],
    at: Any,
    lvl: int,
) -> list[Row]:
    """Sub-rows (cells ruled apart beside one key cell): one table row each, the key named on every row."""
    held, texts = tb["held"], tb["texts"]
    lefts = {j: min(ln["x0"] for ln in held[j]) for c in split for j in per[c] if held[j]}
    inset: set[int] = set()
    # entries set in under the one above them (a group's members): one consistent step
    for c in split:
        xs = [lefts[j] for j in per[c] if j in lefts]
        deep = [j for j in per[c] if j in lefts and lefts[j] - min(xs) > 10]
        if len(deep) >= 2 and max(lefts[j] for j in deep) - min(lefts[j] for j in deep) < 2:
            inset.update(deep)
    out: list[Row] = []
    for s in starts:
        row = [texts[k]]
        for c in tb["data_cols"][1:]:
            j = next((j for j in per[c] if at(j) == s), None)
            text = texts[j] if j is not None else ""
            if j is not None and not text and j in tb["shaded"]:
                text = "—"
            if text and j in inset:
                text = "— " + text
            row.append(text)
        if any(row[1:]) or s == starts[0]:
            out.append(("row", row, lvl))
    return out


def _span_rows(tb: dict[str, Any], k: int, r0: int, r1: int, prof: LayoutProfile) -> list[Row]:
    cells, held, texts, data_cols = tb["cells"], tb["held"], tb["texts"], tb["data_cols"]
    if len(data_cols) > 1 and cells[k][7] >= data_cols[-1]:
        return [("section", texts[k].replace("<br>", " "))]  # a row spanning the whole table
    xs = [ln["x0"] for ln in held[k] if not ln.get("vertical")]
    # nesting is drawn with indented checkboxes
    checked = any(ln["text"].startswith(prof.checkbox) for ln in held[k])
    lvl = (
        max(0, round((min(xs) - tb["key_x"]) / INDENT_STEP))
        if xs and tb["flush"] and checked
        else 0
    )
    per = {
        c: sorted(
            (
                j
                for j, cc in enumerate(cells)
                if not (cc[5] < r0 or cc[4] > r1) and _home(tb, j) == c
            ),
            key=lambda j: cells[j][4],
        )
        for c in data_cols
    }

    def at(j: int) -> int:
        # a cell running down from the row above starts at this row
        return int(max(cells[j][4], r0))

    def blank(j: int) -> bool:
        return bool(re.fullmatch(r"(•|\d{1,2}\.)( _+)?|", texts[j])) or texts[j].startswith("•")

    split = [c for c in data_cols[1:] if len({at(j) for j in per[c]}) > 1]
    # lists ruled apart (blanks under a lead-in or two), or one entry in ruled space
    bulleted = all(
        len(per[c]) - sum(map(blank, per[c])) <= max(1, int(0.3 * len(per[c])))
        or sum(bool(texts[j]) for j in per[c]) <= 1
        for c in split
    )
    starts = sorted({at(j) for c in data_cols[1:] for j in per[c]}) or [r0]
    if split and not bulleted:
        return _sub_rows(tb, k, split, per, starts, at, lvl)
    row = []
    for c in data_cols:
        text = "<br>".join(texts[j] for j in per[c] if texts[j])
        if not text and per[c] and all(j in tb["shaded"] for j in per[c]):
            text = "—"
        row.append(text)
    shared = all(
        not texts[j] or cells[j][4] < r0 or cells[j][5] > r1 for c in data_cols[1:] for j in per[c]
    )
    if (
        shared
        and len(tb["parts"][k]) >= 2
        and sum(ln["text"].startswith(prof.checkbox) for ln in held[k]) >= 2
    ):
        # several terms ticked off in one cell: a row each, at its own indent
        return [
            (
                "row",
                [item, *row[1:]],
                max(0, round((x - tb["key_x"]) / INDENT_STEP)) if tb["flush"] else lvl,
            )
            for item, x in tb["parts"][k]
        ]
    return [("row", row, lvl)]


def body_rows(tb: dict[str, Any], prof: LayoutProfile) -> list[Row]:
    out: list[Row] = []
    done: set[int] = set()
    cells, held = tb["cells"], tb["held"]
    for k, r0, r1 in tb["spans"]:
        for gc in tb["group_cols"]:
            g = next(
                (
                    j
                    for j, c in enumerate(cells)
                    if c[6] <= gc <= c[7] and c[4] <= r0 <= c[5] and held[j]
                ),
                None,
            )
            if g is not None and g not in done:
                done.add(g)
                out.append(("section", tb["texts"][g].replace("<br>", " ")))
        out += _span_rows(tb, k, r0, r1, prof)
    return out
