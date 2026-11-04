"""Ink on a PDF page once its text, rules and flat boxes are painted out.

Each page is rendered at one pixel per point in grey, without its annotations
(art drawn as one is not seen). Its text lines and its layout (`_pdf_layout`:
rules, frames, flat boxes) are painted white, as are the caller's areas
(pictures already cut, art left out on purpose). What ink is left is a drawing
or picture; it is gathered into blobs on a 6-pixel grid. Needs pypdfium2,
imported on use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from ._pdf_layout import layout_boxes
from ._pdf_lines import PdfPage

Box = tuple[float, float, float, float]

_CELL = 6  # pixels per grid cell
_CELL_ON = 3  # dark pixels that switch a cell on
_REACH = 2  # cells: ink this close (a gap under 12 px) joins one blob
_DARK = 200  # grey level below which a pixel is ink
_PAINT_MARGIN = 2  # pixels around each painted box: a stroke's width, a glyph's overhang
_SHAPE_CELLS = 12  # the widest drawing, in cells, that can be page furniture (an icon, a badge)
_SHAPE_SIZE = 0.25  # how far the same icon's size may differ between pages
_SHAPE_BITS = 12  # of 64: how far the same icon's look may differ between pages


@dataclass(frozen=True)
class Shape:
    """A small drawing's size and look, to find the same icon at another place or scale."""

    width: float  # points
    height: float
    bits: int  # 8x8 average hash of its ink

    def matches(self, other: Shape) -> bool:
        def close(a: float, b: float) -> bool:
            return abs(a - b) <= _SHAPE_SIZE * max(a, b)

        return (
            close(self.width, other.width)
            and close(self.height, other.height)
            and (self.bits ^ other.bits).bit_count() <= _SHAPE_BITS
        )


@dataclass(frozen=True)
class Blob:
    box: Box  # PDF points, origin bottom-left
    dark: int  # dark pixels
    cells: tuple[
        Box, ...
    ] = ()  # the grid cells it covers: its shape, where `box` is only its extent
    shape: Shape | None = None  # the whole small drawing it is part of, crops undone
    margin: bool = False  # in the running head or foot: counts toward an icon's pages only


@dataclass
class _Grid:
    width: int  # cells
    height: int
    counts: list[int]  # dark pixels per cell
    dark: Image.Image  # 255 where a pixel is ink


_DARK_PIXELS = [round(v * _CELL * _CELL / 255) for v in range(256)]  # a cell's mean → count


def _grid(img: Image.Image) -> _Grid:
    width, height = img.width // _CELL, img.height // _CELL
    dark = img.point(lambda v: 255 if v < _DARK else 0)
    cells = dark.crop((0, 0, width * _CELL, height * _CELL)).reduce(_CELL)
    return _Grid(width, height, [_DARK_PIXELS[v] for v in cells.tobytes()], dark)


def _flood(
    grid: _Grid, start: int, seen: bytearray, *, most: int | None = None
) -> list[int] | None:
    """The cells joined to `start`; None once they span `most` cells either way."""
    seen[start] = 1
    stack, members = [start], []
    xs, ys = [start % grid.width] * 2, [start // grid.width] * 2
    while stack:
        cell = stack.pop()
        members.append(cell)
        cy, cx = divmod(cell, grid.width)
        if most is not None:
            xs, ys = [min(xs[0], cx), max(xs[1], cx)], [min(ys[0], cy), max(ys[1], cy)]
            if xs[1] - xs[0] >= most or ys[1] - ys[0] >= most:
                return None
        for ny in range(max(0, cy - _REACH), min(grid.height, cy + _REACH + 1)):
            for nx in range(max(0, cx - _REACH), min(grid.width, cx + _REACH + 1)):
                n = ny * grid.width + nx
                if not seen[n] and grid.counts[n] >= _CELL_ON:
                    seen[n] = 1
                    stack.append(n)
    return members


def _shape(grid: _Grid, start: int) -> Shape | None:
    """The small drawing the cell `start` is part of, or None when it is no icon-sized drawing."""
    members = _flood(grid, start, bytearray(len(grid.counts)), most=_SHAPE_CELLS)
    return None if members is None else _shape_of(grid, members)


def _shape_of(grid: _Grid, members: list[int]) -> Shape | None:
    xs, ys = [m % grid.width for m in members], [m // grid.width for m in members]
    ink = grid.dark.crop(
        (min(xs) * _CELL, min(ys) * _CELL, (max(xs) + 1) * _CELL, (max(ys) + 1) * _CELL)
    )
    bbox = ink.getbbox()
    if bbox is None:
        return None
    values = ink.crop(bbox).resize((8, 8), Image.Resampling.BOX).tobytes()
    mean = sum(values) / len(values)
    bits = sum(1 << i for i, v in enumerate(values) if v > mean)
    return Shape(float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1]), bits)


def _blobs(
    img: Image.Image, left: float, top: float, min_dark: int, whole: Image.Image | None = None
) -> list[Blob]:
    grid = _grid(img)
    full = _grid(whole) if whole is not None else grid
    seen = bytearray(grid.width * grid.height)
    out: list[Blob] = []
    for start in range(grid.width * grid.height):
        if seen[start] or grid.counts[start] < _CELL_ON:
            continue
        members = _flood(grid, start, seen) or []
        total = sum(grid.counts[m] for m in members)
        if total >= min_dark:
            cells = tuple(
                (left + x * _CELL, top - (y + 1) * _CELL, left + (x + 1) * _CELL, top - y * _CELL)
                for y, x in (divmod(m, grid.width) for m in members)
            )
            box = (
                min(c[0] for c in cells),
                min(c[1] for c in cells),
                max(c[2] for c in cells),
                max(c[3] for c in cells),
            )
            out.append(Blob(box, total, cells, _shape(full, start)))
    return out


def _margin_icons(img: Image.Image, left: float, top: float, strips: list[Box]) -> list[Blob]:
    """Icon-sized drawings in the running head and foot, as margin blobs."""
    grid = _grid(img)
    seen = bytearray(len(grid.counts))
    out: list[Blob] = []
    for x0, y0, x1, y1 in strips:
        rows = range(
            max(0, int((top - y1) // _CELL)), min(grid.height, int((top - y0) // _CELL) + 1)
        )
        cols = range(
            max(0, int((x0 - left) // _CELL)), min(grid.width, int((x1 - left) // _CELL) + 1)
        )
        for start in (cy * grid.width + cx for cy in rows for cx in cols):
            if seen[start] or grid.counts[start] < _CELL_ON:
                continue
            members = _flood(grid, start, seen, most=_SHAPE_CELLS)
            if members and (shape := _shape_of(grid, members)) is not None:
                ys, xs = zip(*(divmod(m, grid.width) for m in members), strict=True)
                box = (
                    left + min(xs) * _CELL,
                    top - (max(ys) + 1) * _CELL,
                    left + (max(xs) + 1) * _CELL,
                    top - min(ys) * _CELL,
                )
                out.append(Blob(box, sum(grid.counts[m] for m in members), (), shape, margin=True))
    return out


def ink_blobs(
    pdf: Path,
    pages: dict[int, PdfPage],
    painted: dict[int, list[Box]],
    *,
    min_dark: int,
    pictures: dict[int, list[Box]] | None = None,
    margins: dict[int, list[Box]] | None = None,
) -> dict[int, list[Blob]]:
    """Each page's ink blobs of at least `min_dark` dark pixels, after painting
    out its text, layout paths, `painted[page]`, `margins[page]` (the running
    head and foot) and `pictures[page]`. A blob's shape is read with the
    pictures left in, so an icon a crop overlaps is whole; icon-sized drawings
    in the margins come back as `margin` blobs, which only count toward an
    icon's pages."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    def paint(draw: ImageDraw.ImageDraw, boxes: list[Box], left: float, top: float) -> None:
        m = _PAINT_MARGIN
        for x0, y0, x1, y1 in boxes:
            draw.rectangle((x0 - left - m, top - y1 - m, x1 - left + m, top - y0 + m), fill=255)

    doc = pdfium.PdfDocument(str(pdf))
    try:
        out: dict[int, list[Blob]] = {}
        for number, parsed in pages.items():
            page = doc[number - 1]
            page.set_rotation(0)  # in memory only: pixels line up with the page's own coordinates
            left, bottom, right, top = page.get_bbox()
            if right <= left or top <= bottom:  # a crop box off the media box shows nothing
                out[number] = []
                page.close()
                continue
            img = page.render(scale=1, draw_annots=False).to_pil().convert("L")
            boxes = [line.box for line in parsed.lines] + [
                *parsed.sideways,
                *layout_boxes(page, raw),
            ]
            paint(ImageDraw.Draw(img), [*boxes, *painted.get(number, [])], left, top)
            strips = (margins or {}).get(number, [])
            edge = img.copy() if strips else None
            paint(ImageDraw.Draw(img), strips, left, top)
            whole = img.copy()
            paint(ImageDraw.Draw(img), (pictures or {}).get(number, []), left, top)
            out[number] = _blobs(img, left, top, min_dark, whole)
            if edge is not None:
                out[number] += _margin_icons(edge, left, top, strips)
            page.close()
        return out
    finally:
        doc.close()
