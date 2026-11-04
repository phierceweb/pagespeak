"""A PDF page's glyphs as a reader sees them, before any layout.

From pdfium's characters it keeps what is printed and read: no spaces (gaps
make them; a stream space is remembered on the next glyph), no sideways type,
no accent set as its own glyph, a glyph struck twice in one spot once, and no
text its clip path hides. A soft hyphen is marked on the glyph before it.
Needs pypdfium2, imported by the caller.
"""

from __future__ import annotations

import ctypes
import math
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

from ..utils._pdfium import object_bounds

Box = tuple[float, float, float, float]

UNMAPPED = "�"
_SOFT_HYPHENS = ("\x02", "\xad")  # pdfium marks a line-end soft hyphen with 0x02
_MAX_SLANT = 0.15  # |sin(angle)|: past this the glyph is set sideways
_DOUBLE_STRIKE = 0.8  # points: a second glyph this close is the same glyph drawn again
_FONT_NAME_BYTES = 256
_TEXT = 1  # pdfium page-object type


@dataclass(frozen=True)
class Glyph:
    ch: str
    box: Box  # the inked shape
    left: float  # the advance's start and end, in drawing order: word gaps are measured on these
    right: float
    base: float
    size: float
    index: int  # pdfium's character index, for the font name
    hyphen: bool = False  # a soft hyphen follows it
    space_before: bool = False  # the stream has a space between it and the glyph drawn before


@dataclass(frozen=True)
class ClippedText:
    """A text object reaching outside its clip path: its glyphs out there are hidden."""

    bounds: Box
    text: str
    clips: tuple[Box, ...]  # each clip path's extent; a glyph must be inside all of them


def _inside(at: tuple[float, float], box: Box, margin: float = 0.0) -> bool:
    return (
        box[0] - margin <= at[0] <= box[2] + margin and box[1] - margin <= at[1] <= box[3] + margin
    )


def _middle(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _hidden_indices(raw: Any, tp: Any, hidden: list[ClippedText]) -> set[int]:
    """pdfium's indices of the glyphs each clipped object draws outside its clip:
    the object's own run of characters, found by its text and place, so a line
    of the page it lies across keeps every letter."""
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    chars: list[tuple[int, str, Box]] = []
    for i in range(raw.FPDFText_CountChars(tp)):
        ch = chr(raw.FPDFText_GetUnicode(tp, i))
        if not ch.isspace():
            raw.FPDFText_GetCharBox(
                tp,
                i,
                ctypes.byref(left),
                ctypes.byref(right),
                ctypes.byref(bottom),
                ctypes.byref(top),
            )
            chars.append((i, ch, (left.value, bottom.value, right.value, top.value)))
    out: set[int] = set()
    for h in hidden:
        want = "".join(h.text.split())
        for k in range(len(chars) - len(want) + 1) if want else ():
            run = chars[k : k + len(want)]
            if run[0][1] != want[0] or "".join(c[1] for c in run) != want:
                continue
            if all(_inside(_middle(box), h.bounds, 1.0) for _, _, box in run):
                out |= {
                    i for i, _, box in run if not all(_inside(_middle(box), c) for c in h.clips)
                }
                break
    return out


def font_name(raw: Any, tp: Any, index: int) -> str:
    buf = ctypes.create_string_buffer(_FONT_NAME_BYTES)
    raw.FPDFText_GetFontInfo(tp, index, buf, _FONT_NAME_BYTES, None)
    return buf.value.decode("latin-1").split("+")[-1]


def _clip_boxes(raw: Any, obj: Any) -> tuple[Box, ...]:
    clip = raw.FPDFPageObj_GetClipPath(obj)
    if not clip:
        return ()
    x, y = ctypes.c_float(), ctypes.c_float()
    out: list[Box] = []
    for p in range(raw.FPDFClipPath_CountPaths(clip)):
        xs, ys = [], []
        for s in range(raw.FPDFClipPath_CountPathSegments(clip, p)):
            seg = raw.FPDFClipPath_GetPathSegment(clip, p, s)
            raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
            xs.append(x.value)
            ys.append(y.value)
        if xs:
            out.append((min(xs), min(ys), max(xs), max(ys)))
    return tuple(out)


def clipped_text(page: Any, raw: Any, tp: Any) -> list[ClippedText]:
    """The page's top-level text objects that reach outside their clip path."""
    out: list[ClippedText] = []
    for obj in page.get_objects(max_depth=1):
        if obj.type != _TEXT or obj.level != 0:
            continue
        clips = _clip_boxes(raw, obj.raw)
        x0, y0, x1, y1 = object_bounds(obj)
        if not clips or all(_inside((x0, y0), c) and _inside((x1, y1), c) for c in clips):
            continue
        n = raw.FPDFTextObj_GetText(obj.raw, tp, None, 0)
        buf = (ctypes.c_ushort * max(n, 1))()
        raw.FPDFTextObj_GetText(obj.raw, tp, buf, 2 * n)
        text = bytes(buf).decode("utf-16-le", errors="replace").rstrip("\x00")
        out.append(ClippedText((x0, y0, x1, y1), text, clips))
    return out


def _struck_before(
    seen: dict[tuple[str, int, int], list[tuple[float, float]]],
    ch: str,
    origin: tuple[float, float],
) -> bool:
    """Whether `ch` was already drawn within a fraction of a point of `origin`."""
    kx, ky = int(origin[0] // _DOUBLE_STRIKE), int(origin[1] // _DOUBLE_STRIKE)
    return any(
        abs(x - origin[0]) < _DOUBLE_STRIKE and abs(y - origin[1]) < _DOUBLE_STRIKE
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for x, y in seen.get((ch, kx + dx, ky + dy), ())
    )


def page_glyphs(
    raw: Any,
    tp: Any,
    glyphs: dict[str, dict[str, str]] | None = None,
    hidden: list[ClippedText] | None = None,
    sideways: list[Box] | None = None,
) -> list[Glyph]:
    """The page's glyphs worth reading, in pdfium's order. `glyphs` maps a font
    to the symbols its stand-in letters show; `hidden` is `clipped_text()`;
    each sideways glyph's box is added to `sideways` when it is given."""
    out: list[Glyph] = []
    seen: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    last_origin: tuple[float, float] | None = None
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    ox, oy = ctypes.c_double(), ctypes.c_double()
    loose = raw.FS_RECTF()
    matrix = raw.FS_MATRIX()
    spaced = False
    unseen = _hidden_indices(raw, tp, hidden) if hidden else set()
    for i in range(raw.FPDFText_CountChars(tp)):
        if i in unseen:
            continue
        ch = chr(raw.FPDFText_GetUnicode(tp, i))
        if raw.FPDFText_HasUnicodeMapError(tp, i):
            ch = UNMAPPED  # a glyph with no Unicode (a ligature the font never mapped)
        elif glyphs and (table := glyphs.get(font_name(raw, tp, i))) is not None:
            ch = table.get(ch, ch)
        if ch in _SOFT_HYPHENS:
            if out:
                out[-1] = replace(out[-1], hyphen=True)
            continue
        if ch.isspace():
            spaced |= ch not in "\r\n"  # a tightly set line can leave a word gap too narrow to see
            continue
        if unicodedata.combining(ch) or unicodedata.category(ch) == "Sk":
            continue  # an accent set as its own glyph: no letters, and a gap that is no word break
        raw.FPDFText_GetCharBox(
            tp, i, ctypes.byref(left), ctypes.byref(right), ctypes.byref(bottom), ctypes.byref(top)
        )
        box = (left.value, bottom.value, right.value, top.value)
        if abs(math.sin(raw.FPDFText_GetCharAngle(tp, i))) > _MAX_SLANT:
            if sideways is not None:
                sideways.append(box)
            continue
        raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(ox), ctypes.byref(oy))
        origin = (ox.value, oy.value)
        # The halves of an "ff" ligature come one after the other at the very same origin.
        if origin != last_origin and _struck_before(seen, ch, origin):
            continue
        cell = (ch, int(origin[0] // _DOUBLE_STRIKE), int(origin[1] // _DOUBLE_STRIKE))
        seen.setdefault(cell, []).append(origin)
        last_origin = origin
        raw.FPDFText_GetLooseCharBox(tp, i, ctypes.byref(loose))
        # Type size times the horizontal scale: some PDFs set every font at size 1 and scale it.
        raw.FPDFText_GetMatrix(tp, i, ctypes.byref(matrix))
        size = max(raw.FPDFText_GetFontSize(tp, i) * matrix.a, 1.0)
        # Drawing order, whichever way pdfium orders the box: turned type advances right to left.
        start, end = sorted((loose.left, loose.right), reverse=matrix.a < 0)
        out.append(Glyph(ch, box, start, end, oy.value, size, i, space_before=spaced))
        spaced = False
    return out
