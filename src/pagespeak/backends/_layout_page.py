"""Layout backend: one page's reading items — furniture dropped, ruled tables and figures
taken out as floats, writing lines found, the rest returned as text items.

Every item and float carries ``top`` (a y in PDF page space) for reading order.
"""

from __future__ import annotations

from typing import Any

from ._layout_boxes import near, overlap
from ._layout_fields import bad
from ._layout_figures import page_figures
from ._layout_profile import LayoutProfile
from ._layout_tables import find_tables

Line = dict[str, Any]
Item = dict[str, Any]


def is_opener(rec: dict[str, Any], prof: LayoutProfile) -> bool:
    o = prof.opener
    return any(
        ln["text"] == o.text and ln["base"] > o.above and o.font_contains in ln["font"]
        for ln in rec["lines"]
    )


def furniture(ln: Line, opener: bool, prof: LayoutProfile) -> bool:
    t = ln["text"].strip()
    if ln["font"].startswith(prof.furniture_fonts):
        return True  # a watermark
    inner_left, inner_right = prof.page_number_inner
    if (
        ln["base"] < prof.page_number_below
        and prof.page_number.fullmatch(t)
        and (ln["x1"] < inner_left or ln["x0"] > inner_right)
    ):
        return True  # page number
    if ln["base"] > prof.head_y:
        return True  # running head
    o = prof.opener
    # an opener's big number and its title (the chapter heading carries it)
    return opener and (
        ln["y1"] - ln["y0"] > o.drop_taller_than
        or (ln["font"].endswith(o.drop_font_suffix) and ln.get("h", 0) > o.drop_min_cap)
    )


def margin(lines: list[Line]) -> float:
    """The page's left text margin (left and right pages are set at different offsets)."""
    xs = sorted(ln["x0"] for ln in lines if len(ln["text"]) > 40 and not ln.get("vertical"))
    return xs[len(xs) // 4] if xs else 90


def merge_tracked(lines: list[Line]) -> list[Line]:
    """Join the words of a letter-spaced head that the text layer gives as separate lines."""
    out: list[Line] = []
    for ln in sorted(lines, key=lambda ln: (-round(ln["base"]), ln["x0"])):
        prev = out[-1] if out else None
        if (
            prev is not None
            and not ln.get("vertical")
            and not prev.get("vertical")
            and abs(prev["base"] - ln["base"]) < 1
            and prev["font"] == ln["font"]
            and max(prev.get("h", 0), ln.get("h", 0)) >= 8
            and 0 < ln["x0"] - prev["x1"] < 20
        ):
            prev = dict(prev)
            prev["text"] += " " + ln["text"]
            prev["x1"] = ln["x1"]
            prev["runs"] = prev["runs"] + [[ln["font"], " " + ln["text"]]]
            prev["h"] = max(prev.get("h", 0), ln.get("h", 0))
            out[-1] = prev
            continue
        out.append(ln)
    return out


def page_lines(rec: dict[str, Any], prof: LayoutProfile) -> list[Line]:
    """The page's reading lines: furniture dropped, letter-spaced heads joined."""
    opener = is_opener(rec, prof)
    return merge_tracked([ln for ln in rec["lines"] if not furniture(ln, opener, prof)])


def flow_chart(rec: dict[str, Any], prof: LayoutProfile) -> tuple[list[Item], list[Item]]:
    """A page that is one chart of boxes and arrows: everything below its lead-in text is one figure, every box's
    name a label of it."""
    opener = is_opener(rec, prof)
    lines = [ln for ln in rec["lines"] if not furniture(ln, opener, prof)]
    cap = next((ln for ln in lines if prof.figure_caption.match(ln["text"])), None)
    drawn = [
        r[:4]
        for r in rec["rules"] + rec["fills"] + rec["art"] + rec["images"]
        if cap is not None and r[1] < prof.head_y and r[3] > cap["y1"]
    ]
    if cap is None or not drawn:
        raise bad(
            f"pages.flow_charts: page {rec['page']} (0-based) has no figure caption with a "
            "chart drawn above it"
        )
    top = max(r[3] for r in drawn)
    lead = [ln for ln in lines if ln["y0"] > top]
    box = [min(r[0] for r in drawn), cap["y1"] + 2, max(r[2] for r in drawn), top]
    labels = [ln for ln in lines if ln is not cap and ln not in lead]
    return (
        [{"kind": "text", "top": ln["y1"], "line": ln} for ln in lead],
        [
            {
                "kind": "figure",
                "box": box,
                "caption": cap,
                "page": rec["page"],
                "labels": labels,
                "top": top,
            }
        ],
    )


def _cell_pictures(t: dict[str, Any], pics: list[list[float]]) -> list[tuple[int, list[float]]]:
    """A cell's picture: every picture area that overlaps it, clipped to the cell (drawings stacked down a column
    come as one area; a drawing is often a raster with line art over it)."""
    out = []
    for k, c in enumerate(t["cells"]):
        parts = []
        for r in pics:
            ix0, iy0, ix1, iy1 = max(r[0], c[0]), max(r[1], c[1]), min(r[2], c[2]), min(r[3], c[3])
            if ix1 - ix0 > 15 and iy1 - iy0 > 15 and (ix1 - ix0) * (iy1 - iy0) > 600:
                parts.append([ix0, iy0, ix1, iy1])
        if parts:
            out.append(
                (
                    k,
                    [
                        min(p[0] for p in parts),
                        min(p[1] for p in parts),
                        max(p[2] for p in parts),
                        max(p[3] for p in parts),
                    ],
                )
            )
    return out


def _table_floats(
    rec: dict[str, Any], lines: list[Line], used: set[int], prof: LayoutProfile
) -> tuple[list[Item], list[list[float]]]:
    pics = [r for r in rec["images"] + rec["art"] if r[1] < prof.head_y]
    # a drawing in a table cell, too slim for a figure
    slim = [r for r in rec.get("slim", []) if r[1] < prof.head_y]

    def covered(f: list[float]) -> float:
        return sum(overlap(r, f) for r in pics)

    tabs = [
        t
        # a grid drawn in a picture's strokes, or a frame around a picture
        for t in find_tables(rec, rules_below=prof.table_rules_below)
        if any(prof.table_title.match(ln["text"]) for h in t["held"] for ln in h)
        or covered(t["frame"])
        < 0.4 * (t["frame"][2] - t["frame"][0]) * (t["frame"][3] - t["frame"][1])
    ]
    floats: list[Item] = []
    for t in tabs:
        for held in t["held"]:
            used.update(id(ln) for ln in held)
        if t["kind"] == "box":
            floats.append(
                {"kind": "box", "top": t["frame"][3], "lines": t["held"][0], "page": rec["page"]}
            )
            continue
        t["pics"] = _cell_pictures(t, pics + slim)
        t["shaded"] = [
            k
            for k, c in enumerate(t["cells"])
            if any(
                f[4][0] < 200
                and f[0] <= c[0] + 3
                and f[2] >= c[2] - 3
                and f[1] <= c[1] + 3
                and f[3] >= c[3] - 3
                for f in rec["fills"]
            )
        ]
        fr = t["frame"]  # an instruction set sideways beside the table
        t["lead"] = [
            ln
            for ln in lines
            if id(ln) not in used
            and ln.get("vertical")
            and fr[0] - 30 <= ln["x1"] <= fr[0] + 2
            and ln["y0"] < fr[3]
            and fr[1] < ln["y1"]
        ]
        used.update(id(ln) for ln in t["lead"])
        floats.append({"kind": "table", "top": t["frame"][3], "table": t, "page": rec["page"]})
    return floats, [t["frame"] for t in tabs]


def _writing_lines(
    rec: dict[str, Any],
    lines: list[Line],
    frames: list[list[float]],
    figures: list[Item],
    opener: bool,
    prof: LayoutProfile,
) -> list[Item]:
    """Lines drawn outside tables and figures, not underlining any text (a rectangle's edge is a frame)."""
    blanks = []
    for r in [] if opener else rec["strokes"]:
        if r[3] - r[1] > 1.3 or r[2] - r[0] < 90 or r[1] > prof.head_y:
            continue
        if any(
            f[0] - 2 <= r[0] and r[2] <= f[2] + 2 and f[1] - 8 <= r[1] <= f[3] + 8 for f in frames
        ):
            continue  # a table's own border, drawn apart from its grid
        if any(f["box"] and near(f["box"], r, 2) for f in figures):
            continue
        if any(0 <= ln["y0"] - r[3] < 4 and ln["x0"] < r[2] and r[0] < ln["x1"] for ln in lines):
            continue
        blanks.append({"kind": "blank", "top": r[1], "x0": r[0], "line": None})
    return blanks


def classify(rec: dict[str, Any], prof: LayoutProfile) -> tuple[list[Item], list[Item]]:
    """Return (items, floats) for one page; both carry a 'top' y for reading order."""
    opener = is_opener(rec, prof)
    lines = page_lines(rec, prof)
    rec = dict(rec, lines=lines)
    used: set[int] = set()
    floats, frames = _table_floats(rec, lines, used, prof)
    figures = page_figures(rec, lines, used, frames, prof)
    floats += figures
    items: list[Item] = [
        {"kind": "text", "top": ln["y1"], "line": ln} for ln in lines if id(ln) not in used
    ]
    items += _writing_lines(rec, lines, frames, figures, opener, prof)
    return items, floats


__all__ = [
    "classify",
    "flow_chart",
    "furniture",
    "is_opener",
    "margin",
    "merge_tracked",
    "page_lines",
]
