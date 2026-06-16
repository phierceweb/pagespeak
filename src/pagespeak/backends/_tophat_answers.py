"""Read the correct answer(s) from a Top Hat *answers-populated* export.

When an instructor exports a Top Hat quiz after the due date, the correct
option is revealed — but **only visually**: the correct option's letter glyph
is rendered light grey (`#ABABAB` → RGB 171,171,171) with a green check, while
every other option letter is dark. There is no textual "correct answer"
marker in the PDF.

That grey letter, though, IS a deterministic, text-layer signal: pdfium
exposes each glyph's fill color. So we walk the page characters in reading
order, find the question markers (`Question N … Correct Answer`) and the grey
*uppercase standalone* option letters, and bucket each grey letter under the
most recent preceding marker. The result is `{question_number: [correct
letters]}` — $0, offline, no vision.

This is its own module (separate from `_tophat`'s parse/render), one
concern per file. Only multiple-choice answers are recovered this way;
fill-in-the-blank answers appear as body text (handled by the renderer),
not as a grey letter.
"""

from __future__ import annotations

import ctypes
import re
from pathlib import Path

# Unanchored marker finder for the flat page-character stream (no newlines, so
# words are space-joined). `.{0,40}?` spans the "Hide "/"Show " between the
# number and "Correct Answer".
_MARKER_FIND = re.compile(
    r"Question\s+(\d+)\b.{0,40}?(?:Show|Hide)\s*Correct\s*Answer", re.IGNORECASE | re.DOTALL
)
_OPTION_LETTERS = "ABCDEFGH"
# Page-order offset so a later page's char index always sorts after an earlier
# page's; larger than any single page's char count.
_PAGE_STRIDE = 1_000_000


def is_answer_color(rgb: tuple[int, int, int]) -> bool:
    """True for the muted grey (≈171,171,171) Top Hat uses on the correct letter.

    The discriminator is equal channels: the correct letter is a true grey
    (`r == g == b`), while every dark option letter is faintly blue
    (e.g. 60,67,83 — channels differ). Black (0,0,0) is equal-channel too but
    fails the brightness floor.
    """
    r, g, b = rgb
    return r == g == b and r > 120


def assign_answers(
    markers: list[tuple[int, int]], greys: list[tuple[int, str]]
) -> dict[int, list[str]]:
    """Bucket each grey letter under the most recent preceding question marker.

    Args:
        markers: ``(order, question_number)`` for every gradable question, where
            ``order`` is the global reading-order position of the marker.
        greys: ``(order, letter)`` for every correct (grey) option letter.

    Returns:
        ``{question_number: [letters in reading order]}`` for questions that had
        at least one grey letter. Multi-answer questions get multiple letters.
        A grey letter before the first marker is dropped (it belongs to no
        gradable question — e.g. a stray glyph).
    """
    markers = sorted(markers)
    result: dict[int, list[str]] = {}
    for order, letter in sorted(greys):
        preceding = [qnum for mo, qnum in markers if mo <= order]
        if not preceding:
            continue
        result.setdefault(preceding[-1], []).append(letter)
    return result


def _fill_color(tp_raw: object, i: int) -> tuple[int, int, int]:
    r = ctypes.c_uint()
    g = ctypes.c_uint()
    b = ctypes.c_uint()
    a = ctypes.c_uint()
    import pypdfium2.raw as pdfium_c

    pdfium_c.FPDFText_GetFillColor(
        tp_raw, i, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)
    )
    return (r.value, g.value, b.value)


def _is_standalone(chars: list[str], i: int) -> bool:
    """True if char i is not flanked by letters (a real option letter, not a
    letter inside a word like the 'e' in 'Responses')."""
    prev_alpha = i > 0 and chars[i - 1].isalpha()
    next_alpha = i + 1 < len(chars) and chars[i + 1].isalpha()
    return not prev_alpha and not next_alpha


def extract_correct_answers(path: Path) -> dict[int, list[str]]:
    """Read `{question_number: [correct letters]}` from a populated export.

    Returns an empty dict for a questions-only export (no grey letters) — the
    renderer then simply omits answer lines.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "The Top Hat PDF backend requires pypdfium2. "
            "Install with: pip install pagespeak[tophat]"
        ) from e

    pdf = pdfium.PdfDocument(str(path))
    markers: list[tuple[int, int]] = []
    greys: list[tuple[int, str]] = []
    for pno in range(len(pdf)):
        tp = pdf[pno].get_textpage()
        n = tp.count_chars()
        chars = [tp.get_text_range(i, 1) for i in range(n)]
        full = "".join(chars)
        base = pno * _PAGE_STRIDE
        for m in _MARKER_FIND.finditer(full):
            markers.append((base + m.start(), int(m.group(1))))
        for i, ch in enumerate(chars):
            if (
                ch in _OPTION_LETTERS
                and _is_standalone(chars, i)
                and is_answer_color(_fill_color(tp.raw, i))
            ):
                greys.append((base + i, ch))
    return assign_answers(markers, greys)
