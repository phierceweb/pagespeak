"""Verify check `picture_coverage`: ink on a page that no cut picture holds.

Needs the build's source map. Each page it read is rendered with its text,
layout paths, cut pictures, left-out areas and running head and foot painted
out (`_pdf_ink`). Ink touching a picture's edge means the crop cut a drawing
short; ink away from every picture, past a size floor, is a drawing the build
dropped. A small drawing found whole on three or more pages, counting the
running head and foot and art left out on purpose, is furniture (an icon, a
badge) wherever it sits. A crop whose edge runs through a label (a short line
set in another face than the document's body text) shows half of it.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pw_foundation.utils.env import resolve_int

from ._pdf_ink import Blob, Shape, ink_blobs
from ._pdf_lines import PdfLine, PdfPage
from ._source_map import Box, SourceMap
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding, finding_key

MIN_DROPPED_INK_DEFAULT = 150
_MIN_DROPPED_INK_ENV_VAR = "PAGESPEAK_VERIFY_MIN_DROPPED_INK"
_EDGE_MIN_DARK = 15  # a sliver a crop cut off can be tiny
_EDGE_GAP = 4.0  # points: ink this close to a picture's box carries on from it
_RULE_HEIGHT, _RULE_WIDTH = 6.0, 100.0  # a writing line or a table's heavy rule
_ICON_PAGES = 3  # the same drawing on this many pages is furniture: an icon, a badge
_PIECE_GAP = 36.0  # points: dropped ink this close to more is one drawing's piece
_LABEL_WORDS = 8  # a line this short, set in another face than the body's, is a label
_CUT_TEXT = 2.0  # points of a label's width on each side of a crop's edge: cut in two
_CUT_SHARE = 0.3  # of a label's height on each side of a crop's edge: cut in two
_SAME_SIZE = 0.25  # points: the body face set a hair larger or smaller is still the body face


def min_dropped_ink() -> int:
    n: int = resolve_int(None, _MIN_DROPPED_INK_ENV_VAR, default=MIN_DROPPED_INK_DEFAULT)
    return n


def _near(a: Box, b: Box, gap: float) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def _painted(page: PdfPage, smap: SourceMap) -> list[Box]:
    return [bg.box for bg in smap.background_on(page.number)]


def _margins(page: PdfPage, smap: SourceMap) -> list[Box]:
    """Where ink is never a finding but an icon still counts: the running head and
    foot, and art left out on purpose (a badge the build drops on every page)."""
    boxes = [lo.box for lo in smap.left_out_on(page.number)]
    if smap.body is not None:
        left, low, right, high = page.box
        bottom, top = smap.body
        boxes += [(left, top, right, high), (left, low, right, bottom)]
    return boxes


def _finding(
    kind: str,
    page: int,
    box: Box,
    message: str,
    *,
    blocking: bool = True,
    named: tuple[str, ...] = (),
) -> VerifyFinding:
    where = ",".join(str(round(v)) for v in box)
    key = finding_key("picture_coverage", kind, f"p{page}", where, *named)
    return VerifyFinding("picture_coverage", key, f"PDF p{page} [{where}]", message, blocking)


def _extent(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _suspects(
    blobs: dict[int, list[Blob]], smap: SourceMap, floor: int
) -> list[tuple[int, Blob, tuple[str, ...]]]:
    """Each blob that is a cut drawing (with the pictures it touches) or a dropped one (none)."""
    out: list[tuple[int, Blob, tuple[str, ...]]] = []
    for number in sorted(blobs):
        pictures = smap.pictures_on(number)
        for blob in blobs[number]:
            if blob.margin:
                continue
            touching = tuple(
                p.image
                for p in pictures
                if _near(blob.box, p.box, _EDGE_GAP)
                and any(_near(cell, p.box, _EDGE_GAP) for cell in blob.cells)
            )
            x0, y0, x1, y1 = blob.box
            rule = y1 - y0 <= _RULE_HEIGHT and x1 - x0 >= _RULE_WIDTH
            if touching or (blob.dark >= floor and not rule):
                out.append((number, blob, touching))
    return out


def _pieces(
    found: list[tuple[int, Blob, tuple[str, ...]]],
) -> list[tuple[int, list[Blob], tuple[str, ...]]]:
    """One drawing's pieces together: on a page, cuts at the same pictures' edges,
    and dropped ink within a short gap of more dropped ink."""
    groups: list[tuple[int, list[Blob], tuple[str, ...]]] = []
    for number, blob, touching in found:
        joined = [
            g
            for g in groups
            if g[0] == number
            and g[2] == touching
            and (touching or any(_near(blob.box, b.box, _PIECE_GAP) for b in g[1]))
        ]
        for g in joined:
            groups.remove(g)
        groups.append((number, [b for g in joined for b in g[1]] + [blob], touching))
    return sorted(groups, key=lambda g: (g[0], -_extent([b.box for b in g[1]])[3]))


def _cuts(line: Box, box: Box) -> bool:
    """Whether the box cuts the line in two: at least `_CUT_TEXT` of its width and
    `_CUT_SHARE` of its height inside, and as much of either outside."""
    w_in = min(line[2], box[2]) - max(line[0], box[0])
    h_in = min(line[3], box[3]) - max(line[1], box[1])
    width, height = line[2] - line[0], line[3] - line[1]
    if w_in < _CUT_TEXT or h_in < _CUT_SHARE * height or h_in <= 0:
        return False
    return width - w_in >= _CUT_TEXT or h_in <= (1 - _CUT_SHARE) * height


def _body_face(pages: dict[int, PdfPage]) -> tuple[str, float] | None:
    """The face most of the document's running text is set in, from lines too
    long to be labels: a document that is mostly figure is mostly labels."""
    weight: Counter[tuple[str, float]] = Counter()
    for page in pages.values():
        for line in page.lines:
            if len(line.text.split()) > _LABEL_WORDS:
                weight[(line.font, round(line.size, 1))] += len(line.text)
    return weight.most_common(1)[0][0] if weight else None


def _labels(page: PdfPage, body: tuple[str, float] | None) -> list[PdfLine]:
    def in_body(line: PdfLine) -> bool:
        return body is not None and line.font == body[0] and abs(line.size - body[1]) <= _SAME_SIZE

    return [
        line for line in page.lines if not in_body(line) and len(line.text.split()) <= _LABEL_WORDS
    ]


def _cut_labels(pages: dict[int, PdfPage], smap: SourceMap) -> list[VerifyFinding]:
    findings: list[VerifyFinding] = []
    body = _body_face(pages)
    for number in sorted(pages):
        labels = _labels(pages[number], body)
        for pic in smap.pictures_on(number):
            cut = [line.text for line in labels if _cuts(line.box, pic.box)]
            if cut:
                shown = "; ".join(f"«{text}»" for text in cut[:4]) + ("; …" if len(cut) > 4 else "")
                message = f"the crop of {pic.image} cuts {len(cut)} label(s) in two: {shown}"
                findings.append(_finding("label", number, pic.box, message, named=tuple(cut)))
    return findings


def check_picture_coverage(
    doc: VerifyDoc, pages: dict[int, PdfPage], smap: SourceMap, *, pdf: Path
) -> CheckResult:
    painted = {n: _painted(page, smap) for n, page in pages.items()}
    pictures = {n: [p.box for p in smap.pictures_on(n)] for n in pages}
    margins = {n: _margins(page, smap) for n, page in pages.items()}
    blobs = ink_blobs(
        pdf, pages, painted, min_dark=_EDGE_MIN_DARK, pictures=pictures, margins=margins
    )
    seen = [(n, b.shape) for n, on_page in blobs.items() for b in on_page if b.shape]
    found: list[tuple[int, Blob, tuple[str, ...]]] = []
    furniture: list[tuple[Shape, int, Blob, int]] = []
    for number, blob, touching in _suspects(blobs, smap, min_dropped_ink()):
        shape = blob.shape
        pages_like = {n for n, s in seen if shape and s.matches(shape)}
        if shape is None or len(pages_like) < _ICON_PAGES:
            found.append((number, blob, touching))
        elif not any(known.matches(shape) for known, *_ in furniture):
            furniture.append((shape, number, blob, len(pages_like)))
    findings: list[VerifyFinding] = []
    for number, group, touching in _pieces(found):
        box, pieces = _extent([b.box for b in group]), len(group)
        if touching:
            places = f" in {pieces} places" if pieces > 1 else ""
            message = f"ink runs past the edge of {', '.join(touching)}{places}: the crop may cut a drawing short"
            findings.append(_finding("cut", number, box, message))
        else:
            dark = sum(b.dark for b in group)
            parts = f" in {pieces} pieces" if pieces > 1 else ""
            message = f"ink no picture holds ({dark} dark px{parts}): a drawing the build dropped?"
            findings.append(_finding("dropped", number, box, message))
    for _, number, blob, count in furniture:
        message = f"the same small drawing on {count} pages (an icon or badge), not counted as cut or dropped"
        findings.append(_finding("repeated", number, blob.box, message, blocking=False))
    return CheckResult("picture_coverage", tuple(findings + _cut_labels(pages, smap)))
