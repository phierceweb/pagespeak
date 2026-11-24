"""Layout backend: a page's characters from pdfium's text layer, cleaned for line building.

Each character is a tuple ``(char, font, left, right, bottom, top, origin_y, size, angle,
origin_x)`` in PDF page space. Hidden text (drawn outside its clipping path) is dropped,
a glyph drawn twice is kept once, and spacing accents fold into the letter they sit over.
"""

from __future__ import annotations

import ctypes
import unicodedata
from collections.abc import Iterator
from typing import Any

from ..utils._pdfium import object_bounds

Char = tuple[Any, ...]
Box = tuple[float, float, float, float]

# spacing accents drawn as glyphs of their own, folded into the letter they sit over
ACCENTS = {"¯": "̄", "˘": "̆", "ˇ": "̆", "`": "̀", "¨": "̈", "ˆ": "̂", "˜": "̃"}
_STRESS = ("́", "´", "΄", "ʹ", "ˊ")


def _clip_box(obj: Any) -> Box | None:
    import pypdfium2.raw as R

    cp = R.FPDFPageObj_GetClipPath(obj.raw)
    if not cp:
        return None
    xs, ys = [], []
    for i in range(R.FPDFClipPath_CountPaths(cp)):
        for j in range(R.FPDFClipPath_CountPathSegments(cp, i)):
            seg = R.FPDFClipPath_GetPathSegment(cp, i, j)
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
            xs.append(x.value)
            ys.append(y.value)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _object_text(obj: Any, textpage: Any) -> str:
    import pypdfium2.raw as R

    n = R.FPDFTextObj_GetText(obj.raw, textpage.raw, None, 0)
    buf = (ctypes.c_ushort * max(n, 1))()
    R.FPDFTextObj_GetText(obj.raw, textpage.raw, buf, n * 2)
    return "".join(chr(c) for c in buf if c and not chr(c).isspace())


def hidden_runs(page: Any, textpage: Any) -> list[tuple[str, Box]]:
    """Text objects drawn entirely outside their clipping path: invisible on the page but present in the text layer."""
    runs = []
    px0, py0, px1, py1 = page.get_cropbox()
    for o in page.get_objects(max_depth=6):
        if o.type != 1:
            continue
        clip = _clip_box(o)
        if clip is None:
            continue
        x0, y0, x1, y1 = object_bounds(o)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if clip[0] <= cx <= clip[2] and clip[1] <= cy <= clip[3]:
            continue
        if not (px0 <= cx <= px1 and py0 <= cy <= py1):
            continue  # outside the page box: not judged hidden
        text = _object_text(o, textpage)
        if text:
            runs.append((text, (x0 - 1, y0 - 1, x1 + 1, y1 + 1)))
    return runs


def hidden_chars(chars: list[Char], runs: list[tuple[str, Box]]) -> set[int]:
    """Indices of chars belonging to hidden text objects: the object's letters, in order, inside its box."""
    hidden: set[int] = set()
    for text, (x0, y0, x1, y1) in runs:
        k, got = 0, []
        for i, c in enumerate(chars):
            if c[0].isspace():
                continue
            inside = x0 <= (c[2] + c[3]) / 2 <= x1 and y0 <= (c[4] + c[5]) / 2 <= y1
            if inside and c[0] == text[k]:
                got.append(i)
                k += 1
                if k == len(text):
                    # a hidden copy of drawn letters: de-duplication keeps one
                    if not _has_drawn_twin(chars, got):
                        hidden.update(got)
                    break
            elif got:
                k, got = 0, []
    return hidden


def _has_drawn_twin(chars: list[Char], got: list[int]) -> bool:
    return any(
        j not in got
        and any(
            d[0] == chars[g][0] and abs(d[2] - chars[g][2]) < 0.8 and abs(d[4] - chars[g][4]) < 0.8
            for g in got
        )
        for j, d in enumerate(chars)
    )


def page_chars(textpage: Any) -> Iterator[Char]:
    """Every character of a text page, as a `Char` tuple."""
    import pypdfium2.raw as R

    tp = textpage.raw if hasattr(textpage, "raw") else textpage
    buf = ctypes.create_string_buffer(256)
    n = R.FPDFText_CountChars(tp)
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    for i in range(n):
        code = R.FPDFText_GetUnicode(tp, i)
        R.FPDFText_GetFontInfo(tp, i, buf, 256, ctypes.byref(ctypes.c_int()))
        font = buf.value.decode("latin-1").split("+")[-1]
        R.FPDFText_GetCharBox(
            tp, i, ctypes.byref(left), ctypes.byref(right), ctypes.byref(bottom), ctypes.byref(top)
        )
        ox, oy = ctypes.c_double(), ctypes.c_double()
        R.FPDFText_GetCharOrigin(tp, i, ctypes.byref(ox), ctypes.byref(oy))
        size = R.FPDFText_GetFontSize(tp, i)
        angle = R.FPDFText_GetCharAngle(tp, i)
        yield (
            chr(code),
            font,
            left.value,
            right.value,
            bottom.value,
            top.value,
            oy.value,
            size,
            angle,
            ox.value,
        )


def _attach_combining(chars: list[Char], acute_as_prime: bool) -> list[Char]:
    out: list[Char] = []
    for c in chars:
        if acute_as_prime and c[0] in _STRESS:
            c = ("′", *c[1:])
            if out and out[-1][0] == " " and len(out) > 1:
                out.pop()
        if unicodedata.combining(c[0]) and out:
            if out[-1][0] == " " and len(out) > 1:
                out.pop()
            prev = out[-1]
            out[-1] = (
                unicodedata.normalize("NFC", prev[0] + c[0]),
                prev[1],
                prev[2],
                max(prev[3], c[3]),
                *prev[4:],
            )
            continue
        out.append(c)
    return out


def _normal_space(c: Char) -> Char:
    # pdfium's own word break: its position is unreliable, its presence is not
    if c[0] == " " and c[3] - c[2] < 0.5:
        return ("\x00", *c[1:])
    if c[0] in (" ", " ", "\xa0"):  # thin / hair / no-break spaces are word spaces
        return (" ", *c[1:])
    return c


def _fold_over_previous(out: list[Char], c: Char) -> bool:
    """Fold a spacing accent into the letter just before it, when it sits over that letter."""
    cx = (c[2] + c[3]) / 2
    prev = next((o for o in reversed(out) if o[0] != " "), None)
    if prev is None or not prev[0].isalpha() or not (prev[2] - 1.5 <= cx <= prev[3] + 1.5):
        return False
    i = len(out) - 1 - [o[0] for o in reversed(out)].index(prev[0])
    out[i] = (unicodedata.normalize("NFC", prev[0] + ACCENTS[c[0]]), *prev[1:])
    while out and out[-1][0] == " " and i < len(out) - 1:
        out.pop()
    return True


def folded(chars: list[Char], acute_as_prime: bool = False) -> list[Char]:
    """Fold a spacing accent into the letter it sits over; drop zero-width spaces.

    With `acute_as_prime` (the profile's `fonts.acute_as_prime`), an acute or tonos is a
    stress mark and reads as a prime after its syllable.
    """
    out: list[Char] = []
    pending: Char | None = None
    for c in _attach_combining(list(chars), acute_as_prime):
        c = _normal_space(c)
        ch, x0, x1 = c[0], c[2], c[3]
        if ch in ACCENTS:
            if not _fold_over_previous(out, c):
                pending = c
            continue
        if pending is not None:
            px = (pending[2] + pending[3]) / 2
            if ch.isalpha() and x0 - 1.5 <= px <= x1 + 1.5:
                c = (unicodedata.normalize("NFC", ch + ACCENTS[pending[0]]), *c[1:])
                # a space emitted for the accent's own advance is not a word break
                if out and out[-1][0] == " " and len(out) > 1 and x0 - out[-2][3] < 1.8:
                    out.pop()
            else:
                out.append(pending)
            pending = None
        out.append(c)
    if pending is not None:
        out.append(pending)
    return out


def deduped(chars: list[Char]) -> list[Char]:
    """Drop a glyph drawn a second time a fraction of a point from the first (a faux-bold label, a line set twice).

    The copy drawn first is kept whole, so a line set twice still reads in its own order.
    """
    seen: dict[tuple[str, int, int], list[Char]] = {}
    out = []
    for c in chars:
        if c[0].isspace():
            out.append(c)
            continue
        kx, ky = int(c[2] // 0.8), int(c[4] // 0.8)
        near = [
            p
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for p in seen.get((c[0], kx + dx, ky + dy), [])
        ]
        # the two halves of an "ff" ligature share a box: not a copy
        if any(
            abs(c[2] - p[2]) < 0.8
            and abs(c[4] - p[4]) < 0.8
            and not (c[0] == "f" and c[2] == p[2] and c[4] == p[4])
            for p in near
        ):
            continue
        seen.setdefault((c[0], kx, ky), []).append(c)
        out.append(c)
    return out
