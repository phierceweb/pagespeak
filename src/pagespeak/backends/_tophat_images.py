"""Extract embedded figures from a Top Hat quiz PDF and bind them to questions.

Some Top Hat questions ARE a figure — a diagram is the whole question (e.g. a
multi-stage process cascade), with no text stem and no answer toggle. The
text-only path drops these entirely. This module pulls the embedded image
bitmaps out of the PDF (via `pypdfium2`, recursing into form XObjects where Top
Hat nests them), writes them to the output `images/` dir, and binds each to the
question whose marker most recently precedes it in reading order.

The renderer then references the image so the normal vision pass captions it —
turning a lost figure-question into a captioned (and, for diagrams, Mermaid'd)
RAG-usable block. Returns ``{question_number: [relative image paths]}``.
"""

from __future__ import annotations

import ctypes
import re
from pathlib import Path

# Any question marker, for binding figures by reading position. Matches both
# Top Hat styles: a bare/`Question N` marker, OR a gradable marker where the
# number precedes "(Show|Hide) Correct Answer" (the "Topic 2 Hide Correct
# Answer" style with no "Question" word). Group 1 or 2 holds the number.
_MARKER_ANY = re.compile(
    r"\bQuestion\s+(\d+)\b|(\d+)\s+(?:Show|Hide)\s*Correct\s*Answer",
    re.IGNORECASE | re.DOTALL,
)
# Skip UI chrome (the chat-bubble icon, small logos). Real figures are large.
_MIN_DIM_PX = 120


def _char_top(tp_raw: object, i: int) -> float:
    left = ctypes.c_double()
    right = ctypes.c_double()
    bottom = ctypes.c_double()
    top = ctypes.c_double()
    import pypdfium2.raw as pdfium_c

    pdfium_c.FPDFText_GetCharBox(
        tp_raw, i, ctypes.byref(left), ctypes.byref(right), ctypes.byref(bottom), ctypes.byref(top)
    )
    return top.value


def bind_images_to_questions(
    markers: list[tuple[int, float, int]],
    images: list[tuple[int, float]],
) -> dict[int, list[int]]:
    """Bind each image to the question whose marker last precedes it, **by page**.

    Binding is page-level, not y-level: Top Hat nests figures in form XObjects
    whose `get_pos()` returns *form-local* coordinates (a top far outside the
    page box), so an image's y is not comparable to the page's text y. A figure
    therefore binds to the last marker on its page or an earlier page — which is
    its question, since a figure sits between its own marker and the next
    question's. Marker y (page-local char-top, reliable) only orders markers
    *within* a page.

    Args:
        markers: ``(page, char_top, question_number)`` for every marker.
        images: ``(page, _)`` for every kept figure (the second field is the
            unreliable form-local top and is ignored for binding).

    Returns:
        ``{question_number: [image indices into `images`, extraction order]}``.
        An image on a page before any marker is dropped (belongs to no question).
    """
    # Markers in reading order: page ascending, then higher-on-page (larger top).
    ordered_markers = sorted(markers, key=lambda m: (m[0], -m[1]))
    result: dict[int, list[int]] = {}
    for k, (img_page, _ignored_top) in enumerate(images):
        preceding = [q for (mp, _mt, q) in ordered_markers if mp <= img_page]
        if not preceding:
            continue
        result.setdefault(preceding[-1], []).append(k)
    return result


def extract_question_images(path: Path, images_dir: Path) -> dict[int, list[str]]:
    """Extract figures from `path` into `images_dir`, keyed by question number.

    Returns ``{question_number: ["images/q<N>_<seq>.png", …]}``. Images smaller
    than `_MIN_DIM_PX` on either side (UI chrome) are skipped. Returns an empty
    dict if the PDF has no embedded figures.
    """
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "The Top Hat PDF backend requires pypdfium2. "
            "Install with: pip install pagespeak[tophat]"
        ) from e

    pdf = pdfium.PdfDocument(str(path))
    markers: list[tuple[int, float, int]] = []
    figures: list[tuple[int, float]] = []
    bitmaps: list[object] = []
    for pno in range(len(pdf)):
        page = pdf[pno]
        tp = page.get_textpage()
        n = tp.count_chars()
        full = "".join(tp.get_text_range(i, 1) for i in range(n))
        for m in _MARKER_ANY.finditer(full):
            number = int(m.group(1) or m.group(2))
            markers.append((pno, _char_top(tp.raw, m.start()), number))
        for obj in page.get_objects(max_depth=6):
            if obj.type != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                continue
            pil = obj.get_bitmap(render=False).to_pil()
            if pil.width < _MIN_DIM_PX or pil.height < _MIN_DIM_PX:
                continue
            figures.append((pno, obj.get_pos()[3]))  # pos = (left, bottom, right, top)
            bitmaps.append(pil)

    if not figures:
        return {}
    bound = bind_images_to_questions(markers, figures)
    images_dir.mkdir(parents=True, exist_ok=True)
    result: dict[int, list[str]] = {}
    for qnum, idxs in bound.items():
        for seq, k in enumerate(idxs, 1):
            fname = f"q{qnum}_{seq}.png"
            bitmaps[k].save(images_dir / fname)  # type: ignore[attr-defined]
            result.setdefault(qnum, []).append(f"images/{fname}")
    return result
