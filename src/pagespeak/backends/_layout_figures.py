"""Layout backend: a page's figures — picture areas matched to their captions, with the
labels and keys printed around them claimed as the figure's text.

A figure is a dict: ``box`` (the art), ``caption`` (a line, or None), ``labels`` (lines),
``page``, ``top`` and ``frames`` (the page's table frames, which a crop must stay clear
of). A line shaped like a caption that no picture takes is left in the page's text.
"""

from __future__ import annotations

from typing import Any

from ._layout_boxes import mid, near, overlap, union
from ._layout_labels import claim_labels
from ._layout_profile import LayoutProfile

Line = dict[str, Any]
Box = list[float]


def picture_groups(regions: list[Box], gap: float = 12) -> list[Box]:
    groups: list[Box] = []
    for r in sorted(regions, key=lambda r: -r[3]):
        for g in [g for g in groups if near(g, r, gap)]:
            groups.remove(g)
            r = union(r, g)
        groups.append(list(r))
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if near(groups[i], groups[j], gap):
                    groups[i] = union(groups[i], groups.pop(j))
                    changed = True
                    break
            if changed:
                break
    return groups


def _captions(
    lines: list[Line], used: set[int], prof: LayoutProfile
) -> tuple[list[Line], dict[int, list[Line]]]:
    """The lines shaped like a figure caption, each joined to a second line it runs onto, and
    for each (by id) the page lines it is made of."""
    caps = [ln for ln in lines if id(ln) not in used and prof.figure_caption.match(ln["text"])]
    made_of = {id(c): [c] for c in caps}
    taken: set[int] = set()
    for i, c in enumerate(caps):
        if c.get("vertical"):
            continue
        tail = c["runs"][-1][0] if c["runs"] else c["font"]
        more = [
            ln
            for ln in lines
            if id(ln) not in used
            and id(ln) not in taken
            and ln is not c
            and not ln.get("vertical")
            and ln["font"] == tail
            and 6 < c["base"] - ln["base"] < 1.8 * max(c["y1"] - c["y0"], 6)
            and c["x0"] - 20 <= ln["x0"]
            and ln["x1"] <= c["x1"] + 20
        ]
        if more:
            nxt = max(more, key=lambda ln: ln["base"])
            taken.update((id(c), id(nxt)))
            caps[i] = dict(c, text=c["text"] + " " + nxt["text"], y0=min(c["y0"], nxt["y0"]))
            made_of[id(caps[i])] = [c, nxt]
    return caps, made_of


def _cut_at_captions(regions: list[Box], caps: list[Line]) -> list[Box]:
    """Two figures drawn as one area: cut it at each caption that lies inside it, leaving the caption out."""
    cut = []
    for r in regions:
        inner = sorted(
            [
                c
                for c in caps
                if r[1] + 10 < mid(c)[1] < r[3] - 10
                and not c.get("vertical")
                and r[0] <= mid(c)[0] <= r[2]
            ],
            key=lambda c: -c["y1"],
        )
        top = r[3]
        for lo, hi in [(c["y1"] + 2, c["y0"] - 2) for c in inner] + [(r[1], None)]:
            if top - lo > 20:
                cut.append([r[0], lo, r[2], top])
            top = hi if hi is not None else top
    return cut


def _assign(
    cut: list[Box], caps: list[Line], frames: list[Box]
) -> tuple[dict[int, list[Any]], list[Box]]:
    """Each picture area belongs to the nearest caption below it (or to the right, set sideways)."""
    by_cap: dict[int, list[Any]] = {}
    loose: list[Box] = []
    side = [c for c in caps if c.get("vertical")]
    for r in cut:
        below = [
            c
            for c in caps
            if not c.get("vertical")
            and c["y1"] <= r[1] + 14
            # a table set between picture and caption
            and not any(f[3] < r[1] and f[1] > c["y1"] for f in frames)
            and c["x0"] < r[2] + 40
            and r[0] - 40 < c["x1"]
        ]
        beside = [c for c in side if c["y0"] < r[3] and r[1] < c["y1"] and c["x0"] > r[0]]
        if not beside and len(side) == 1 and side[0]["x0"] > (r[0] + r[2]) / 2:
            beside = side  # several views of one figure stacked beside a single sideways caption
        cap = (
            max(below, key=lambda c: c["y1"])
            if below
            else (min(beside, key=lambda c: c["x0"]) if beside else None)
        )
        if cap is None:
            loose.append(r)
        else:
            by_cap.setdefault(id(cap), [cap, None])
            by_cap[id(cap)][1] = r if by_cap[id(cap)][1] is None else union(by_cap[id(cap)][1], r)
    for r in list(loose):  # a picture set inside a captioned figure's area is part of that figure
        host = next(
            (v for v in by_cap.values() if overlap(r, v[1]) >= 0.8 * (r[2] - r[0]) * (r[3] - r[1])),
            None,
        )
        if host is not None:
            loose.remove(r)
            host[1] = union(host[1], r)
    return by_cap, loose


def page_figures(
    rec: dict[str, Any], lines: list[Line], used: set[int], frames: list[Box], prof: LayoutProfile
) -> list[dict[str, Any]]:
    """The page's figures, in the order the reader emits them, each with its labels claimed."""
    # cell drawings belong to their table
    regions = [
        r
        for r in rec["images"] + rec["art"]
        if r[1] < prof.head_y
        and r[3] > prof.floor_y
        and (r[2] - r[0]) * (r[3] - r[1]) > 900
        and sum(overlap(r, f) for f in frames) < 0.3 * (r[2] - r[0]) * (r[3] - r[1])
    ]
    caps, made_of = _captions(lines, used, prof)
    by_cap, loose = _assign(_cut_at_captions(regions, caps), caps, frames)
    figures: list[dict[str, Any]] = []
    for cap, box in by_cap.values():
        used.update(id(ln) for ln in made_of[id(cap)])
        figures.append(
            {
                "kind": "figure",
                "box": box,
                "caption": cap,
                "page": rec["page"],
                "labels": [],
                "top": box[3],
            }
        )
    for g in picture_groups(loose, gap=30):
        figures.append(
            {
                "kind": "figure",
                "box": g,
                "caption": None,
                "page": rec["page"],
                "labels": [],
                "top": g[3],
            }
        )
    for f in sorted(figures, key=lambda f: -f["box"][3]):
        claim_labels(f, lines, used, frames, prof)
    return figures
