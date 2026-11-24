"""Layout backend: what a ruled table's cells say — items within a cell, header text, and
sideways tables turned so their rows run the way the text reads."""

from __future__ import annotations

import re
from typing import Any

from ._layout_profile import LayoutProfile
from ._layout_text import BOLD, ITAL, clean, join

Line = dict[str, Any]
Item = tuple[str, float]


def _is_credit(t: str, prof: LayoutProfile) -> bool:
    """The art credit printed over a cell's drawing."""
    return bool(
        prof.credit.match(t) or prof.cell_credit.search(t) or prof.cell_credit_fragment.fullmatch(t)
    )


def _ordered(lines: list[Line]) -> tuple[list[Line], bool]:
    vert = [ln for ln in lines if ln.get("vertical")]
    upright = not (vert and len(vert) >= len(lines) / 2)
    if not upright:
        return sorted(lines, key=lambda ln: ln["x0"] if ln.get("up", True) else -ln["x0"]), False
    return sorted(lines, key=lambda ln: (-round(ln["base"], 0), ln["x0"])), True


def _starts_item(
    cur: str,
    t: str,
    ln: Line,
    gap: float,
    lead: float | None,
    pitch: float | None,
    upright: bool,
    soft: bool,
    ticked: float | None,
    prof: LayoutProfile,
) -> bool:
    lead_font = ln["runs"][0][0] if ln["runs"] else ""
    label = re.match(r"^[A-Za-z ]{2,24}:", t) and (
        BOLD.search(lead_font) or ITAL.search(lead_font.split("-")[-1])
    )
    # an item, a label, a key ("S =")
    starts = t.startswith((prof.checkbox, "•")) or bool(label) or bool(re.match(r"^[A-Z] =", t))
    starts = starts or ticked is not None
    blank = ln.get("drawn") or t.startswith("_")
    if lead and not blank and gap > 1.6 * lead and gap > 1.3 * max(ln["y1"] - ln["y0"], 6):
        starts = True  # a blank line between two paragraphs of one cell
    if pitch and upright and not soft and not blank and gap > 1.25 * pitch:
        starts = True  # set a step further down than the table's lines: the next item
    if prof.reference_run.fullmatch(cur) and re.match(r"[a-z]", t):
        starts = True  # a line of references, then the note
    if starts and cur.endswith("="):
        starts = False  # "M =" with its first label on the next line
    return bool(starts)


def cell_items(lines: list[Line], prof: LayoutProfile, pitch: float | None = None) -> list[Item]:
    """A cell's items with the x each starts at: items (bullets, checkboxes, bold labels, lines set a step apart)
    apart, wrapped lines joined. `pitch` is the table's line spacing: a wider step starts a new item (a list of
    names, one to a line)."""
    if not lines:
        return []
    lines, upright = _ordered(lines)
    bases = [ln["base"] for ln in lines if not ln.get("drawn")]
    steps = [a - b for a, b in zip(bases, bases[1:], strict=False) if a - b > 3]
    lead = min(steps) if upright and len(steps) >= 2 else None  # the cell's line spacing
    items: list[Item] = []
    cur, cur_x, soft, prev, ticked = "", 0.0, False, None, None
    for i, ln in enumerate(lines):
        t = ln["text"].strip()
        if _is_credit(t, prof):
            continue
        if t == prof.checkbox:
            ticked = ln["x0"]  # a checkbox set as a glyph of its own: the next line is an item
            continue
        gap = prev["base"] - ln["base"] if prev is not None else 0
        starts = _starts_item(cur, t, ln, gap, lead, pitch, upright, soft, ticked, prof)
        t = clean(t, prof.checkbox)
        followed = (
            i + 1 < len(lines)
            and abs(lines[i + 1]["base"] - ln["base"]) < 2
            and lines[i + 1]["x0"] > ln["x0"]
        )
        if re.fullmatch(r"•|\d{1,2}\.", t) and not followed:
            t += " ____"  # a bullet or a number with nothing after it: a blank to fill in
        if not t:
            continue
        if (
            cur
            and prev is not None
            and re.fullmatch(r"•|\d{1,2}\.", cur)
            and abs(prev["base"] - ln["base"]) < 2
        ):
            cur += " " + t  # the mark and its text, set apart on one line
        elif cur and not starts:
            cur = join(cur, t, soft)
        else:
            if cur:
                items.append((cur, cur_x))
            cur, cur_x = t, (ticked if ticked is not None else ln["x0"])
        soft, prev, ticked = ln.get("soft_hyphen", False), ln, None
    if cur:
        items.append((cur, cur_x))
    return [(t.replace("|", "\\|"), x) for t, x in items]


def rotate(t: dict[str, Any]) -> dict[str, Any]:
    """A table set sideways: read its grid so that rows run the way its text reads."""
    cells, rows, cols = t["cells"], t["rows"], t["cols"]
    lines = [ln for h in t["held"] for ln in h if ln.get("vertical")]
    up = sum(1 for ln in lines if ln.get("up", True)) >= len(lines) / 2
    new = []
    for x0, y0, x1, y1, r0, r1, c0, c1 in cells:
        if up:  # text reads bottom to top: rows go left to right, columns bottom to top
            new.append([x0, y0, x1, y1, c0, c1, rows - 1 - r1, rows - 1 - r0])
        else:  # top to bottom: rows go right to left, columns top to bottom
            new.append([x0, y0, x1, y1, cols - 1 - c1, cols - 1 - c0, r0, r1])
    return dict(t, cells=new, rows=cols, cols=rows)


def header_text(lines: list[Line], prof: LayoutProfile) -> str:
    """A header cell: its lines, with a line of references (the profile's `reference_line`) set in parentheses."""
    parts: list[str] = []
    refs: list[str] = []
    soft = False
    for ln in sorted(lines, key=lambda ln: (-round(ln["base"]), ln["x0"])):
        t = clean(ln["text"], prof.checkbox)
        if not t:
            continue
        if (parts and prof.reference_line.match(t)) or refs:
            refs.append(t)
        elif soft and parts:
            parts[-1] += t  # a word broken across the line end
        else:
            parts.append(t)
        soft = ln.get("soft_hyphen", False)
    if refs:
        parts.append("(" + " ".join(refs).rstrip(";") + ")")
    return " ".join(parts).replace("|", "\\|")
