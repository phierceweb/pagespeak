"""Layout backend: pictures — where a figure's crop runs, which way it turns, the ink a
box holds, and the text printed on and around the art."""

from __future__ import annotations

import re
from typing import Any

from ._layout_boxes import near, union
from ._layout_figure_text import label_text
from ._layout_pages import render_page
from ._layout_profile import LayoutProfile
from ._layout_text import Doc, clean, join, styled

Line = dict[str, Any]
Box = list[float]


class PageSource:
    """The open PDF, its page records, and pages rendered with their text (and rules) painted out."""

    def __init__(self, doc: Any, records: dict[int, dict[str, Any]]) -> None:
        self.doc = doc
        self.records = records
        self._rendered: dict[tuple[int, bool], tuple[Any, tuple[float, float]]] = {}

    def page(self, pg: int) -> dict[str, Any]:
        return self.records[pg]

    def masked(self, pg: int, ruled: bool = False) -> tuple[Any, tuple[float, float]]:
        """The page at 1pt a pixel with its text painted out (and with `ruled`, its rules and grey bars too:
        in a table those are the grid, not a drawing)."""
        if (pg, ruled) not in self._rendered:
            p = self.doc[pg]
            img = render_page(p, 1.0).convert("L")
            left, _, _, top = p.get_cropbox()
            rec = self.page(pg)
            for ln in rec["lines"]:
                img.paste(
                    255,
                    (
                        round(ln["x0"] - left - 1),
                        round(top - ln["y1"] - 2),
                        round(ln["x1"] - left + 1),
                        round(top - ln["y0"] + 2),
                    ),
                )
            for r in (rec["rules"] + [f[:4] for f in rec["fills"]]) if ruled else []:
                img.paste(
                    255,
                    (
                        round(r[0] - left - 1),
                        round(top - r[3] - 1),
                        round(r[2] - left + 1),
                        round(top - r[1] + 1),
                    ),
                )
            self._rendered[(pg, ruled)] = (img, (left, top))
        return self._rendered[(pg, ruled)]

    def ink(self, pg: int, box: Box) -> float:
        """Share of the box's area drawn in, text aside (a picture area cut down to blank page is not a picture)."""
        img, (left, top) = self.masked(pg)
        region = img.crop(
            (round(box[0] - left), round(top - box[3]), round(box[2] - left), round(top - box[1]))
        )
        hist = region.histogram()
        return float(sum(hist[:200]) / max(1, region.width * region.height))

    def ink_box(self, pg: int, box: Box, inset: float = 2, level: int = 230) -> Box | None:
        """The drawn part of a box, text aside, inside its border (a cell's drawing without its name or rules)."""
        img, (left, top) = self.masked(pg, ruled=True)
        x0, y0, x1, y1 = box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset
        region = img.crop((round(x0 - left), round(top - y1), round(x1 - left), round(top - y0)))
        bb = region.point(lambda v: 255 if v < level else 0).getbbox()
        return [x0 + bb[0], y1 - bb[3], x0 + bb[2], y1 - bb[1]] if bb else None


def picture(
    d: Doc,
    pg: int,
    box: Box,
    label: str,
    turn: int = 0,
    ceiling: float | None = None,
    alt: str | None = None,
) -> list[str]:
    """Cut a picture; `label` names its file, `alt` (default: the label) is what the captioner is told it is."""
    x0, y0, x1, y1 = box[0] - 3, box[1] - 3, box[2] + 3, min(box[3] + 3, ceiling or 1e9)
    stem = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60] or "picture"
    name = f"p{pg:04d}-{stem}.jpeg"
    if any(c[2] == name for c in d.crops):
        name = name.replace(".jpeg", f"-{len(d.crops)}.jpeg")
    d.crops.append((pg, [x0, y0, x1, y1], name, turn))
    return [f"![{(alt or label).replace(']', ')')}](images/{name})"]


def figure_crop(f: dict[str, Any], src: PageSource, prof: LayoutProfile) -> Box:
    """What to cut for a figure: the art with its labels and key beside it, short of its caption and of any table."""
    art, box = f["box"], list(f["box"])
    for ln in f["labels"]:
        if (ln["x1"] < art[0] - 60 or ln["x0"] > art[2] + 60) and not re.fullmatch(
            r"\d{1,2}\.?", ln["text"].strip()
        ):
            continue  # a label across the page in the figure's band (a callout number is the figure's own)
        box = [
            min(box[0], ln["x0"]),
            min(box[1], ln["y0"]),
            max(box[2], ln["x1"]),
            max(box[3], ln["y1"]),
        ]
    rec = src.page(f["page"])
    for r in rec.get("slim", []):  # a slim drawing out past the cut's 3pt margin: a key's circles
        if near(box, r, 4) and (
            r[0] < box[0] - 3 or r[1] < box[1] - 3 or r[2] > box[2] + 3 or r[3] > box[3] + 3
        ):
            box = union(box, r)
    caps = [f["caption"]] if f["caption"] is not None else []
    # a neighbour's too
    caps += [
        ln
        for ln in rec["lines"]
        if prof.figure_caption.match(ln["text"]) and not ln.get("vertical")
    ]
    for cap in caps:
        if cap.get("vertical") or not (
            cap["y0"] < box[3] + 3
            and box[1] - 3 < cap["y1"]
            and cap["x0"] < box[2]
            and box[0] < cap["x1"]
        ):
            continue
        if cap["y0"] + cap["y1"] < art[1] + art[3]:
            box[1] = max(box[1], cap["y1"] + 4)  # clear of the caption, the cut's padding included
        else:
            box[3] = min(box[3], cap["y0"] - 4)
    for fr in f.get("frames", []):
        if (
            fr[1] < box[3] + 3
            and box[1] - 3 < fr[3]
            and fr[0] < box[2]
            and box[0] < fr[2]
            and not (fr[1] >= art[1] and fr[3] <= art[3])
        ):
            if fr[1] + fr[3] > art[1] + art[3]:
                box[3] = min(box[3], fr[1] - 4)
            else:
                box[1] = max(box[1], fr[3] + 4)
    return [box[0], max(box[1], prof.floor_y), box[2], min(box[3], prof.head_y)]


def figure_turn(f: dict[str, Any]) -> int:
    """A figure printed sideways is cut upright: turned the way its caption, or most of its labels, read."""
    cap = f["caption"]
    vert = [ln for ln in f["labels"] if ln.get("vertical")]
    if cap is not None and cap.get("vertical"):
        ups = [cap.get("up", True)]
    elif len(vert) >= 3 and len(vert) >= 0.6 * len(f["labels"]):
        ups = [ln.get("up", True) for ln in vert]
    else:
        return 0
    return -90 if sum(ups) >= len(ups) / 2 else 90


def text_ceiling(box: Box, lines: list[Line]) -> float | None:
    """Just under a cell's own text (its name) set above or over the top of its drawing: the cut stops short of it."""
    ys = [
        ln["y0"]
        for ln in lines
        if ln["x0"] < box[2]
        and box[0] < ln["x1"]
        and (box[1] + box[3]) / 2 < ln["y0"] < box[3] + 15
    ]
    return float(min(ys) - 1) if ys else None


def render_figure(
    d: Doc, f: dict[str, Any], pg: int, fallback: str, src: PageSource, prof: LayoutProfile
) -> None:
    cap = f["caption"]
    captext = clean(cap["text"], prof.checkbox) if cap is not None else None
    if captext:
        d.heading(2, captext)
    label = captext.split(".")[0] if captext else fallback
    if f["box"] and not cap and not f["labels"] and src.ink(pg, f["box"]) < 0.002:
        return
    out = (
        picture(d, pg, figure_crop(f, src, prof), label, figure_turn(f), alt=captext)
        if f["box"]
        else []
    )
    labels = label_text(f["labels"], prof)
    if labels:
        out += ["", "*Figure text:* " + " · ".join(labels)]
    d.block(out)


def render_box(d: Doc, f: dict[str, Any], prof: LayoutProfile) -> None:
    text = ""
    for ln in sorted(f["lines"], key=lambda ln: (-round(ln["base"]), ln["x0"])):
        text = join(text, styled(ln, prof.checkbox))
    if text:
        d.block(["> " + text])


def render_raster(d: Doc, spec: dict[str, Any], pg: int) -> None:
    """A table printed inside a page's picture, with no text layer: transcribed in the profile; the drawing it
    numbers is cut apart from it."""
    d.heading(2, spec["title"])
    d.block(picture(d, pg, spec["figure"], spec["label"]))
    d.block(
        ["| " + " | ".join(spec["header"]) + " |", "|" + "---|" * len(spec["header"])]
        + ["| " + " | ".join(r) + " |" for r in spec["rows"]]
    )
