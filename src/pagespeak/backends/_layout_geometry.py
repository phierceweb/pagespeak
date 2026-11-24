"""Layout backend: what a page draws besides text, from pdfium's page objects.

Raster picture areas (tiles joined on a grid), filled rectangles with their colour,
rules (lines, rectangle edges, thick separators), strokes (the rules drawn as lines:
the only writing-line candidates), line-art areas, and slim line-art areas (25pt or
less across). Boxes are ``[x0, y0, x1, y1]`` in PDF page space, rounded to 0.1pt.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Any

from ..utils._pdfium import object_bounds

Rect = list[float]
Point = tuple[float, float]


@dataclass
class Geometry:
    images: list[Rect] = field(default_factory=list)
    fills: list[list[Any]] = field(default_factory=list)
    rules: list[Rect] = field(default_factory=list)
    art: list[Rect] = field(default_factory=list)
    strokes: list[Rect] = field(default_factory=list)
    slim: list[Rect] = field(default_factory=list)


def regions(
    rects: list[Any],
    size: tuple[float, float],
    cell: int = 3,
    gap: int = 4,
    origin: tuple[float, float] = (0, 0),
) -> list[Rect]:
    """Picture areas from object rects: a figure is often thousands of 1–2pt tiles, so join them on a grid.

    The grid covers a page `size` wide and tall whose bottom-left corner is at `origin`.
    """
    ox, oy = origin
    w, h = int(size[0] / cell) + 2, int(size[1] / cell) + 2
    grid = bytearray(w * h)
    for x0, y0, x1, y1 in rects:
        rows = range(max(0, int((y0 - oy - gap) / cell)), min(h, int((y1 - oy + gap) / cell) + 1))
        cols = range(max(0, int((x0 - ox - gap) / cell)), min(w, int((x1 - ox + gap) / cell) + 1))
        for gy in rows:
            row = gy * w
            for gx in cols:
                grid[row + gx] = 1
    seen, out = bytearray(w * h), []
    for start in range(w * h):
        if not grid[start] or seen[start]:
            continue
        cells = _flood(grid, seen, start, w, h)
        xs, ys = [c % w for c in cells], [c // w for c in cells]
        box = [
            min(xs) * cell + gap + ox,
            min(ys) * cell + gap + oy,
            (max(xs) + 1) * cell - gap + ox,
            (max(ys) + 1) * cell - gap + oy,
        ]
        inner = [
            r
            for r in rects
            if box[0] - gap <= r[0]
            and r[2] <= box[2] + gap
            and box[1] - gap <= r[1]
            and r[3] <= box[3] + gap
        ]
        if inner:
            out.append(
                [
                    min(r[0] for r in inner),
                    min(r[1] for r in inner),
                    max(r[2] for r in inner),
                    max(r[3] for r in inner),
                ]
            )
    return out


def _flood(grid: bytearray, seen: bytearray, start: int, w: int, h: int) -> list[int]:
    stack, cells = [start], []
    seen[start] = 1
    while stack:
        c = stack.pop()
        cells.append(c)
        cx = c % w
        for n in (c - 1 if cx else -1, c + 1 if cx < w - 1 else -1, c - w, c + w):
            if 0 <= n < w * h and grid[n] and not seen[n]:
                seen[n] = 1
                stack.append(n)
    return cells


def _subpaths(obj: Any) -> list[list[Any]]:
    """A path's pieces in page space: ``[points, has_curve]`` per subpath."""
    import pypdfium2.raw as R

    m = R.FS_MATRIX()
    R.FPDFPageObj_GetMatrix(obj.raw, ctypes.byref(m))
    out: list[list[Any]] = []
    cur: list[Any] | None = None
    for i in range(R.FPDFPath_CountSegments(obj.raw)):
        seg = R.FPDFPath_GetPathSegment(obj.raw, i)
        x, y = ctypes.c_float(), ctypes.c_float()
        R.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        pt = (m.a * x.value + m.c * y.value + m.e, m.b * x.value + m.d * y.value + m.f)
        kind = R.FPDFPathSegment_GetType(seg)
        if kind == R.FPDF_SEGMENT_MOVETO or cur is None:
            cur = [[pt], False]
            out.append(cur)
        else:
            cur[0].append(pt)
            cur[1] |= kind == R.FPDF_SEGMENT_BEZIERTO
    return out


def _rect(pts: list[Point]) -> tuple[float, float, float, float] | None:
    """The box of a closed axis-aligned rectangle, else None."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    on_edge = all(
        (abs(p[0] - x0) < 0.6 or abs(p[0] - x1) < 0.6)
        and (abs(p[1] - y0) < 0.6 or abs(p[1] - y1) < 0.6)
        for p in pts
    )
    return (x0, y0, x1, y1) if len(pts) >= 4 and on_edge else None


def _edges(x0: float, y0: float, x1: float, y1: float) -> list[Rect]:
    return [
        [x0, y0, x1, y0 + 0.5],
        [x0, y1 - 0.5, x1, y1],
        [x0, y0, x0 + 0.5, y1],
        [x1 - 0.5, y0, x1, y1],
    ]


def _fill_color(obj: Any) -> list[int] | None:
    import pypdfium2.raw as R

    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if (
        R.FPDFPageObj_GetFillColor(
            obj.raw, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)
        )
        and a.value > 0
    ):
        return [r.value, g.value, b.value]
    return None


def _draw_mode(obj: Any) -> tuple[int, int]:
    import pypdfium2.raw as R

    fm, st = ctypes.c_int(), ctypes.c_int()
    R.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fm), ctypes.byref(st))
    return fm.value, st.value


def _classify_subpath(
    geo: Geometry,
    art: list[Any],
    pts: list[Point],
    curved: bool,
    filled: int,
    stroked: int,
    color: list[int] | None,
) -> None:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    w, h = bx1 - bx0, by1 - by0
    rect = None if curved else _rect(pts)
    if not curved and len(pts) == 2 and ((h < 2.5 and w > 5) or (w < 2.5 and h > 5)):
        geo.rules.append([bx0, by0, bx1, by1])
        geo.strokes.append(geo.rules[-1])
    elif not curved and stroked and not filled and w > 20 and h <= 9 and len(pts) <= 8:
        # a thick separator
        geo.rules.append([bx0, (by0 + by1) / 2 - 0.5, bx1, (by0 + by1) / 2 + 0.5])
        geo.strokes.append(geo.rules[-1])
    elif not curved and stroked and not filled and h > 20 and w <= 9 and len(pts) <= 8:
        geo.rules.append([(bx0 + bx1) / 2 - 0.5, by0, (bx0 + bx1) / 2 + 0.5, by1])
    elif rect is not None:
        if (rect[3] - rect[1]) < 2.5 or (rect[2] - rect[0]) < 2.5:
            geo.rules.append(list(rect))  # a hairline drawn as a filled sliver
            geo.strokes.append(geo.rules[-1])
            return
        geo.rules.extend(_edges(*rect))
        if filled and color is not None and color != [255, 255, 255]:
            geo.fills.append([round(v, 1) for v in rect] + [color])
    elif curved and len(pts) <= 14 and w > 40 and h > 15:
        if filled and color is not None:
            # a rounded note box
            geo.fills.append([round(v, 1) for v in (bx0, by0, bx1, by1)] + [color])
    else:
        art.append((bx0, by0, bx1, by1))


def page_geometry(page: Any) -> Geometry:
    """Everything the page draws besides text, sorted into the `Geometry` kinds."""
    geo = Geometry()
    images: list[tuple[float, float, float, float]] = []
    art: list[tuple[float, float, float, float]] = []
    left, bottom, right, top = page.get_cropbox()
    size, origin = (right - left, top - bottom), (left, bottom)
    for o in page.get_objects(max_depth=4):
        x0, y0, x1, y1 = object_bounds(o)
        if o.type == 3:
            # a picture bleeding off the page
            images.append((max(x0, left), max(y0, bottom), min(x1, right), min(y1, top)))
            continue
        if o.type != 2:
            continue
        filled, stroked = _draw_mode(o)
        color = _fill_color(o) if filled else None
        for pts, curved in _subpaths(o):
            _classify_subpath(geo, art, pts, curved, filled, stroked, color)
    geo.rules = [[round(v, 1) for v in r] for r in geo.rules]
    geo.strokes = [[round(v, 1) for v in r] for r in geo.strokes]
    geo.images = [
        [round(v, 1) for v in r]
        for r in regions(images, size, origin=origin)
        if (r[2] - r[0]) * (r[3] - r[1]) > 400
    ]
    areas = [(r, r[2] - r[0], r[3] - r[1]) for r in regions(art, size, gap=6, origin=origin)]
    geo.art = [[round(v, 1) for v in r] for r, w, h in areas if w > 25 and h > 25]
    geo.slim = [
        [round(v, 1) for v in r]
        for r, w, h in areas
        if not (w > 25 and h > 25) and max(w, h) > 30 and min(w, h) > 6
    ]
    return geo
