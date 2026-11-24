"""Layout backend: the labels and keys printed around a figure, claimed as its text."""

from __future__ import annotations

from typing import Any

from ._layout_boxes import inside
from ._layout_profile import LayoutProfile

Line = dict[str, Any]
Box = list[float]


def _is_head(ln: Line, prof: LayoutProfile) -> bool:
    return bool(
        ln.get("h", 0) >= prof.label_head_min_cap and ln["font"].startswith(prof.heading_font)
    )


def _claim_above(
    f: dict[str, Any], lines: list[Line], used: set[int], frames: list[Box], prof: LayoutProfile
) -> float:
    """A key and its instructions may start above the drawing: claim them up to the nearest head."""
    box = f["box"]
    above = [
        ln
        for ln in lines
        if id(ln) not in used
        and box[3] < ln["y0"]
        and ln["y1"] < box[3] + 120
        and not prof.instruction.match(ln["text"])
    ]
    heads = [ln["y0"] for ln in above if _is_head(ln, prof) and not ln.get("vertical")]
    ceiling = min(heads + [f2[1] for f2 in frames if f2[1] > box[3]] + [box[3] + 120])
    for ln in above:
        # the body face is running text
        if ln["y1"] <= ceiling and not ln["font"].startswith(prof.body_font):
            f["labels"].append(ln)
            used.add(id(ln))
    roof = min(
        [prof.head_y]
        + [f2[1] for f2 in frames if f2[1] > box[3]]
        + [ln["y0"] for ln in lines if prof.instruction.match(ln["text"])]
    )
    reach = max([box[3]] + [ln["y1"] for ln in f["labels"]])
    grew = len(f["labels"]) > 0
    while grew:  # a key block taller than that: claim on upward while its lines run on, to a head
        more = [
            ln
            for ln in lines
            if id(ln) not in used
            and not ln.get("vertical")
            and reach < ln["y0"] < reach + 16
            and ln["y1"] <= roof
            and box[0] - 40 < ln["x1"]
            and ln["x0"] < box[2] + 40
            and not ln["font"].startswith(prof.body_font)
            and not prof.instruction.match(ln["text"])
            and not _is_head(ln, prof)
        ]
        for ln in more:
            f["labels"].append(ln)
            used.add(id(ln))
        reach = max([reach] + [ln["y1"] for ln in more])
        grew = bool(more)
    return float(reach)


def _claim_around(
    f: dict[str, Any], lines: list[Line], used: set[int], prof: LayoutProfile
) -> None:
    box, cap = f["box"], f["caption"]
    low = min(box[1], cap["y1"] + 1) if cap is not None and not cap.get("vertical") else box[1]
    around = [box[0] - 40, low - 40, box[2] + 40, box[3] + 40]
    band = [0, low - 6, 1e9, box[3] + 6]
    for ln in lines:
        if id(ln) in used or prof.instruction.match(ln["text"]):
            continue
        prose = ln["font"].startswith(prof.body_font)
        if (
            inside(ln, around, 0)
            and not (prose and not inside(ln, box, 0))
            or (inside(ln, band, 0) and not prose)
        ):
            f["labels"].append(ln)
            used.add(id(ln))


def _claim_key_below(
    f: dict[str, Any], lines: list[Line], used: set[int], prof: LayoutProfile
) -> None:
    """A numbered key set below the picture, row by row and column by column."""
    floor = min([f["box"][1]] + [ln["y0"] for ln in f["labels"] if not ln.get("vertical")])
    pool = [
        ln
        for ln in lines
        if id(ln) not in used
        and not ln.get("vertical")
        and ln["y1"] <= floor
        and not ln["font"].startswith(prof.body_font)
        and len(ln["text"]) < 50
    ]
    got = [ln for ln in pool if prof.key_entry.match(ln["text"]) and floor - ln["y1"] < 20]
    grew = bool(got)
    while grew:
        more = [
            ln
            for ln in pool
            if ln not in got
            and any(
                abs(ln["base"] - g["base"]) < 1.5
                or (0 < g["base"] - ln["base"] < 13 and abs(ln["x0"] - g["x0"]) < 25)
                for g in got
            )
        ]
        got += more
        grew = bool(more)
    for ln in got:
        f["labels"].append(ln)
        used.add(id(ln))


def claim_labels(
    f: dict[str, Any], lines: list[Line], used: set[int], frames: list[Box], prof: LayoutProfile
) -> None:
    box = f["box"]
    reach = _claim_above(f, lines, used, frames, prof)
    # the key above the art
    top = max(
        [box[3]]
        + [ln["y1"] for ln in f["labels"] if box[3] < ln["y1"] < max(box[3] + 60, reach + 1)]
    )
    f["box"] = [box[0], box[1], box[2], top]
    _claim_around(f, lines, used, prof)
    _claim_key_below(f, lines, used, prof)
    note = [ln for ln in lines if prof.instruction.match(ln["text"]) and inside(ln, f["box"], 2)]
    # the page's instruction line, printed over the top of the picture: it reads first, apart
    if note:
        f["top"] = min(f["top"], max(ln["base"] for ln in note) + 6)
        f["box"][3] = min(f["box"][3], min(ln["y0"] for ln in note) - 2)
    f["frames"] = frames
