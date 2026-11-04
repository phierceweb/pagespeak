"""The source PDF's own text lines and outline, read independently of any build.

Verify compares a conversion against these, so they come from the glyphs a
reader sees (`_pdf_glyphs`) by position alone, never from the order a content
stream happens to draw them in: glyphs on one baseline (a smaller super- or
subscript with them) and no column-sized gap make a line; word spaces come
from the gaps. Positions are PDF points, origin bottom-left. Needs pypdfium2,
imported on use.
"""

from __future__ import annotations

import bisect
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils._pdfium import outline
from ._pdf_glyphs import UNMAPPED, ClippedText, Glyph, clipped_text, font_name, page_glyphs

__all__ = [
    "UNMAPPED",
    "OutlineEntry",
    "PdfLine",
    "PdfPage",
    "page_count",
    "read_outline",
    "read_pages",
]

Box = tuple[float, float, float, float]

_WORD_GAP = 0.18  # of the type size: a wider gap between advances is a word space
_ROW_REACH = 0.15  # of the type size: baselines this close are one row
_SCRIPT = 0.85  # a run this much smaller than a line's type is a super- or subscript…
_SCRIPT_REACH = 0.6  # …when it sits this far (of the line's size) off the baseline at most…
_SCRIPT_GLYPHS = 6  # …and is this short
_CELL_GAP = 2.5  # a gap this many times the line's usual word space parts two table cells…
_CELL_GAP_EM = 0.5  # …when it is also this wide, of the type size


@dataclass(frozen=True)
class PdfLine:
    page: int  # 1-based
    text: str
    box: Box
    size: float
    font: str
    hyphenated: bool  # ends in a hyphen a reader joins to the next line
    base: float  # baseline y
    cells: tuple[str, ...] = ()  # the text split at gaps far wider than its word spaces


@dataclass(frozen=True)
class PdfPage:
    number: int  # 1-based
    box: Box  # what shows: the crop box within the media box; its origin need not be (0, 0)
    lines: list[PdfLine]
    sideways: tuple[Box, ...] = ()  # glyphs set sideways: not read as lines, but still text
    rotation: int = 0  # degrees the page is turned to be shown (its /Rotate)


@dataclass(frozen=True)
class OutlineEntry:
    level: int  # 0 = top
    title: str
    page: int | None  # 1-based


def _drawn_runs(glyphs: list[Glyph]) -> list[list[Glyph]]:
    """Glyphs as the content stream draws them, cut wherever it moves to another
    baseline, jumps back, or leaves a column-sized gap."""
    runs: list[list[Glyph]] = []
    for g in glyphs:
        if runs:
            prev = runs[-1][-1]
            same_base = abs(g.base - prev.base) <= max(1.0, _ROW_REACH * g.size)
            if same_base and prev.left - 1 <= g.left <= prev.right + _gutter(prev.size, g.size):
                runs[-1].append(g)
                continue
        runs.append([g])
    return runs


def _rows(runs: list[list[Glyph]]) -> list[list[list[Glyph]]]:
    """Runs on one baseline, top of the page first (a row may span columns)."""
    rows: list[tuple[float, list[list[Glyph]]]] = []  # kept sorted by baseline
    for run in sorted(runs, key=lambda r: -_main_base(r)):
        base, size = _main_base(run), _median([g.size for g in run])
        reach = max(1.0, _ROW_REACH * size)
        lo = bisect.bisect_left(rows, base - reach, key=lambda r: r[0])
        hi = bisect.bisect_right(rows, base + reach, key=lambda r: r[0])
        near = min(rows[lo:hi], key=lambda r: abs(r[0] - base), default=None)
        if near is None:
            bisect.insort(rows, (base, [run]), key=lambda r: r[0])
        else:
            near[1].append(run)
    return [members for _, members in reversed(rows)]


def _segments(row: list[list[Glyph]]) -> list[list[Glyph]]:
    """A row's runs joined left to right where they meet; a column-sized gap, or
    one run printed over another (a watermark across a label), keeps them apart."""
    out: list[list[Glyph]] = []
    for run in sorted(row, key=lambda r: r[0].left):
        size = _median([g.size for g in run])
        for seg in out:
            gap = run[0].left - seg[-1].right
            if -0.5 * size <= gap <= _gutter(seg[-1].size, run[0].size):
                seg.extend(run)
                break
        else:
            out.append(list(run))
    return out


def _gutter(a: float, b: float) -> float:
    """The widest gap one line can have: wider is a column gutter. Set by the
    smaller type, so a big heading does not reach across into the next column."""
    return max(7.0, 0.9 * min(a, b))


def _median(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


def _main_base(run: list[Glyph]) -> float:
    """The baseline of a run's full-size type: a folded-in script sits off it."""
    big = max(g.size for g in run)
    return _median([g.base for g in run if g.size >= _SCRIPT * big])


def _attach_scripts(runs: list[list[Glyph]]) -> list[list[Glyph]]:
    """Fold a short run of smaller type set just above or below a line, within
    or right after it, into that line: a superscript or subscript, wherever
    the content stream happened to draw it."""
    kept = [True] * len(runs)
    stats = [(_median([g.size for g in r]), _median([g.base for g in r])) for r in runs]
    for k, run in enumerate(runs):
        size, base = stats[k]
        if len(run) > _SCRIPT_GLYPHS:
            continue
        x0 = min(g.left for g in run)
        hosts = [
            h
            for h, other in enumerate(runs)
            if h != k
            and kept[h]
            and size < _SCRIPT * stats[h][0]
            and abs(base - stats[h][1]) <= _SCRIPT_REACH * stats[h][0]
            and min(g.left for g in other) - 2
            <= x0
            <= max(g.right for g in other) + 0.5 * stats[h][0]
        ]
        if hosts:
            host = min(hosts, key=lambda h: abs(stats[h][1] - base))
            runs[host] = sorted(runs[host] + run, key=lambda g: (g.left, g.index))
            kept[k] = False
    return [run for run, keep in zip(runs, kept, strict=True) if keep]


def _line(raw: Any, tp: Any, page: int, run: list[Glyph]) -> PdfLine | None:
    chars: list[str] = []
    spaces: list[tuple[int, float]] = []  # each word space: where in `chars`, how wide
    for prev, g in zip([None, *run[:-1]], run, strict=True):
        gap = g.left - prev.right if prev is not None else 0.0
        if prev is not None and (
            gap > _WORD_GAP * g.size or (g.space_before and gap > -0.2 * g.size)
        ):
            spaces.append((len(chars), gap))
            chars.append(" ")
        chars.append(g.ch)
    text = _normal("".join(chars))
    if not text:
        return None
    sizes = sorted(g.size for g in run)
    cells = _cells(chars, spaces, sizes[len(sizes) // 2])
    base = _main_base(run)
    box = (
        min(g.box[0] for g in run),
        min(g.box[1] for g in run),
        max(g.box[2] for g in run),
        max(g.box[3] for g in run),
    )
    hyphen = run[-1].hyphen or text.endswith("-")
    if run[-1].hyphen and not text.endswith("-"):
        text += "-"  # pdfium reads a printed line-end hyphen, hard or soft, as one code
    font = font_name(raw, tp, run[0].index)
    return PdfLine(page, text, box, sizes[len(sizes) // 2], font, hyphen, base, cells)


def _normal(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _cells(chars: list[str], spaces: list[tuple[int, float]], size: float) -> tuple[str, ...]:
    """The line cut at each gap far wider than its usual word space (justified
    text spaces one line evenly), or () when it has none."""
    if len(spaces) < 2:
        return ()
    usual = sorted(w for _, w in spaces)[(len(spaces) - 1) // 2]
    wide = [at for at, w in spaces if w >= max(_CELL_GAP * usual, _CELL_GAP_EM * size)]
    if not wide:
        return ()
    bounds = [0, *wide, len(chars)]
    return tuple(_normal("".join(chars[a:b])) for a, b in zip(bounds, bounds[1:], strict=False))


def _page_lines(
    raw: Any,
    tp: Any,
    page: int,
    glyphs: dict[str, dict[str, str]] | None = None,
    hidden: list[ClippedText] | None = None,
    sideways: list[Box] | None = None,
) -> list[PdfLine]:
    """One page's text lines, top to bottom and left to right. `glyphs`,
    `hidden` and `sideways`: see `_pdf_glyphs.page_glyphs`."""
    # Scripts fold in first: a subscript between two words would otherwise leave a
    # gap wide enough to read as a column gutter.
    runs = _attach_scripts(_drawn_runs(page_glyphs(raw, tp, glyphs, hidden, sideways)))
    out: list[PdfLine] = []
    for row in _rows(runs):
        for seg in _segments(row):
            if (line := _line(raw, tp, page, seg)) is not None:
                out.append(line)
    return out


def read_pages(
    pdf: Path, pages: Iterable[int], *, glyphs: dict[str, dict[str, str]] | None = None
) -> dict[int, PdfPage]:
    """Each asked-for page (1-based) with its crop box and text lines; pages past
    the end are skipped. `glyphs`: see `_page_lines`."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument(str(pdf))
    try:
        out: dict[int, PdfPage] = {}
        for number in pages:
            if not 1 <= number <= len(doc):
                continue
            page = doc[number - 1]
            x0, y0, x1, y1 = (float(v) for v in page.get_bbox())
            textpage = page.get_textpage()
            hidden = clipped_text(page, raw, textpage.raw)
            sideways: list[Box] = []
            lines = [
                line
                for line in _page_lines(raw, textpage.raw, number, glyphs, hidden, sideways)
                if x0 <= (line.box[0] + line.box[2]) / 2 <= x1
                and y0 <= (line.box[1] + line.box[3]) / 2 <= y1
            ]
            box = (x0, y0, x1, y1)
            out[number] = PdfPage(number, box, lines, tuple(sideways), page.get_rotation())
            textpage.close()
            page.close()
        return out
    finally:
        doc.close()


def read_outline(pdf: Path) -> list[OutlineEntry]:
    """The PDF's bookmark outline, in order."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [
            OutlineEntry(level, (title or "").strip(), None if index is None else index + 1)
            for level, title, index in outline(doc)
        ]
    finally:
        doc.close()


def page_count(pdf: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return len(doc)
    finally:
        doc.close()
