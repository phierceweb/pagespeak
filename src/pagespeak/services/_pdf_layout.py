"""Which parts of a PDF page are layout, not drawing: rules, frames, flat boxes, type.

A path is layout when it is a hairline or a thin bar, a rectangle's outline or
fill, or a frame drawn in level and upright strokes with small rounded corners
(stroked, or filled as a thin ring); a text object is layout when it is one
run of type. `_pdf_ink` paints these out before looking for drawings.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Any

from ..utils._pdfium import object_bounds

Box = tuple[float, float, float, float]

_RULE = 2.5  # points: a straight path thinner than this is a rule
_SEPARATOR = 9.0  # points: a stroked bar no thicker than this is a separator
_TEXT_RUN = 24.0  # points: a text object this thin is one run of type
_CORNER = 36.0  # points: the most a frame's rounded corner spans
_FRAME_MIN = 36.0  # points: a frame drawn as a filled ring is at least this big each way…
_RING_FILL = 0.15  # …and fills less than this share of its box: it is nearly all hole
_TEXT, _PATH, _FORM = 1, 2, 5  # pdfium page-object types


@dataclass
class _Subpath:
    points: list[tuple[float, float]]
    kinds: list[int]  # each point's segment type
    curved: bool = False
    straight: bool = False  # has a straight side


def _subpaths(raw: Any, obj: Any) -> list[_Subpath]:
    """A path's pieces in page space."""
    m = raw.FS_MATRIX()
    raw.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
    x, y = ctypes.c_float(), ctypes.c_float()
    out: list[_Subpath] = []
    for i in range(raw.FPDFPath_CountSegments(obj)):
        seg = raw.FPDFPath_GetPathSegment(obj, i)
        raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        point = (m.a * x.value + m.c * y.value + m.e, m.b * x.value + m.d * y.value + m.f)
        kind = raw.FPDFPathSegment_GetType(seg)
        if kind == raw.FPDF_SEGMENT_MOVETO or not out:
            out.append(_Subpath([point], [kind]))
            continue
        out[-1].points.append(point)
        out[-1].kinds.append(kind)
        out[-1].curved |= kind == raw.FPDF_SEGMENT_BEZIERTO
        out[-1].straight |= kind == raw.FPDF_SEGMENT_LINETO
    return out


def _on_edges(points: list[tuple[float, float]], box: Box, *, corners: bool) -> bool:
    """Every point on the box's edges: at its corners (a rectangle), or anywhere
    along them (a rounded rectangle, whose corner curves keep to its edges)."""

    def near(a: float, b: float) -> bool:
        return abs(a - b) < 0.6

    def fits(px: float, py: float) -> bool:
        on_x = near(px, box[0]) or near(px, box[2])
        on_y = near(py, box[1]) or near(py, box[3])
        return (on_x and on_y) if corners else (on_x or on_y)

    return len(points) >= 4 and all(fits(px, py) for px, py in points)


def _frame_strokes(sub: _Subpath, line_to: int) -> list[Box] | None:
    """Each stroke of an outline drawn only in level and upright lines and small
    corner curves (a box's frame, its tab), else None. Painting the strokes, not
    the box, keeps whatever the frame encloses."""
    if not sub.straight:
        return None
    strokes: list[Box] = []
    pts, i = sub.points, 1
    closing = [(pts[-1], pts[0])] if pts[-1] != pts[0] else []
    while i < len(pts):
        span = pts[i - 1 : i + 1] if sub.kinds[i] == line_to else pts[i - 1 : i + 3]
        xs, ys = [p[0] for p in span], [p[1] for p in span]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if (sub.kinds[i] == line_to and min(w, h) > 0.6) or (
            sub.kinds[i] != line_to and max(w, h) > _CORNER
        ):
            return None
        strokes.append((min(xs), min(ys), max(xs), max(ys)))
        i += 1 if sub.kinds[i] == line_to else 3
    for (x0, y0), (x1, y1) in closing:
        if min(abs(x1 - x0), abs(y1 - y0)) <= 0.6:
            strokes.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return strokes


def _ring(points: list[tuple[float, float]], box: Box) -> bool:
    """A hairline frame drawn as a filled outline: big, and nearly all hole (a solid shape is a drawing)."""
    w, h = box[2] - box[0], box[3] - box[1]
    if min(w, h) < _FRAME_MIN:
        return False
    pairs = zip(points, points[1:] + points[:1], strict=True)
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs)) / 2
    return area < _RING_FILL * w * h


def _edges(box: Box) -> list[Box]:
    x0, y0, x1, y1 = box
    return [(x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)]


def _flat_parts(raw: Any, obj: Any) -> list[Box]:
    """The parts of a path that are layout, not drawing."""
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    raw.FPDFPath_GetDrawMode(obj, ctypes.byref(fill), ctypes.byref(stroke))
    out: list[Box] = []
    for sub in _subpaths(raw, obj):
        xs, ys = [p[0] for p in sub.points], [p[1] for p in sub.points]
        box = (min(xs), min(ys), max(xs), max(ys))
        w, h = box[2] - box[0], box[3] - box[1]
        if not sub.curved and (w < _RULE or h < _RULE):
            out.append(box)
        elif sub.straight and _on_edges(sub.points, box, corners=not sub.curved):
            # A circle's points also keep to its box's edges, but it has no straight side.
            # A wide rounded corner bows in from the box's edges: paint each stroke's span.
            frame = None if fill.value else _frame_strokes(sub, raw.FPDF_SEGMENT_LINETO)
            out += [box] if fill.value else frame or _edges(box)
        elif not sub.curved and stroke.value and not fill.value and min(w, h) <= _SEPARATOR:
            out.append(box)
        elif (stroke.value and not fill.value) or (
            fill.value and not sub.curved and _ring(sub.points, box)
        ):
            out += _frame_strokes(sub, raw.FPDF_SEGMENT_LINETO) or []
    return out


def _out_of(forms: list[Any], box: Box) -> Box:
    """`box` in page space, through each enclosing form's matrix, innermost first."""
    corners = [(box[0], box[1]), (box[2], box[3]), (box[0], box[3]), (box[2], box[1])]
    for m in reversed(forms):
        corners = [m.on_point(x, y) for x, y in corners]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def layout_boxes(page: Any, raw: Any) -> list[Box]:
    """The page's layout as boxes to paint out: short text objects and every
    layout part of its paths, in page space even when drawn inside a form."""
    boxes: list[Box] = []
    forms: list[Any] = []  # matrices of the forms around the current object
    for obj in page.get_objects(max_depth=4):
        del forms[obj.level :]
        if obj.type == _FORM:
            forms.append(obj.get_matrix())
            continue
        parts: list[Box] = []
        if obj.type == _PATH:
            parts = _flat_parts(raw, obj.raw)
        elif obj.type == _TEXT:
            x0, y0, x1, y1 = object_bounds(obj)
            if min(x1 - x0, y1 - y0) <= _TEXT_RUN:  # a whole paragraph object could hide a drawing
                parts = [(x0, y0, x1, y1)]
        boxes += [_out_of(forms, b) for b in parts]
    return boxes
