"""Marker's text layer, keeping only the text inside each page's visible box.

pdftext, which Marker reads a PDF's text layer with, places every character
relative to the box pdfium reports for the page (its CropBox, within the
MediaBox) but keeps the characters that lie outside it. A page cut from a
two-page spread by its CropBox still holds the facing page's text, and pdftext
joins it to this page's line when the two share a baseline and font: the page's
title arrives glued to the facing page's. `clipped_to_page_box` drops each
character whose centre lies outside its page's box before Marker builds the page,
and rebuilds a span that lost one from the characters left.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import marker.providers.pdf as _marker_pdf
from pdftext.postprocessing import handle_hyphens, postprocess_text
from pw_foundation.log import get_logger

from ._marker_ignoretext import _as_bool

logger = get_logger(__name__)

# Named like Marker's own provider keys (`PdfProvider_pdftext_workers`).
CONFIG_KEY = "PdfProvider_clip_to_page_box"


def centre_inside(bbox: Sequence[float], box: Sequence[float]) -> bool:
    """True when the bbox's centre lies in the box, edges included."""
    x = (bbox[0] + bbox[2]) / 2
    y = (bbox[1] + bbox[3]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _merged(bboxes: Sequence[Sequence[float]]) -> list[float]:
    return [
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    ]


def _rebuild(span: dict[str, Any], chars: list[dict[str, Any]]) -> None:
    """The span as pdftext would have built it from these characters."""
    span["chars"] = chars
    raw = "".join(c["char"] for c in chars)
    span["text"] = handle_hyphens(postprocess_text(raw), keep_hyphens=True)
    span["bbox"] = _merged([c["bbox"] for c in chars])
    span["char_start_idx"] = chars[0]["char_idx"]
    span["char_end_idx"] = chars[-1]["char_idx"]


def clip_pages(pages: list[dict[str, Any]], *, keep_chars: bool) -> tuple[int, int]:
    """Drop the characters outside each page's box from pdftext's `dictionary_output`,
    read with `keep_chars=True`, in place. Without `keep_chars` the characters are
    then removed, as pdftext removes them. Returns (characters dropped, pages touched)."""
    dropped = touched = 0
    for page in pages:
        box = (0, 0, page["width"], page["height"])
        on_page = dropped
        blocks = []
        for block in page["blocks"]:
            lines = []
            for line in block["lines"]:
                spans = []
                for span in line["spans"]:
                    chars = span["chars"]
                    inside = [c for c in chars if centre_inside(c["bbox"], box)]
                    if len(inside) < len(chars):
                        dropped += len(chars) - len(inside)
                        if not inside:
                            continue
                        _rebuild(span, inside)
                    if not keep_chars:
                        del span["chars"]
                    spans.append(span)
                if spans:
                    line["spans"] = spans
                    lines.append(line)
            if lines:
                block["lines"] = lines
                blocks.append(block)
        page["blocks"] = blocks
        if dropped > on_page:
            touched += 1
            for block in blocks:
                for line in block["lines"]:
                    line["bbox"] = _merged([s["bbox"] for s in line["spans"]])
                block["bbox"] = _merged([line["bbox"] for line in block["lines"]])
    return dropped, touched


@contextmanager
def clipped_to_page_box(config: Mapping[str, object]) -> Iterator[None]:
    """Clip the text Marker reads during the call, unless `config` turns it off.

    Marker's `PdfProvider` reads pdftext through `marker.providers.pdf.dictionary_output`.
    """
    if not _as_bool(config.get(CONFIG_KEY, True)):
        yield
        return
    read = _marker_pdf.dictionary_output

    def clipped(*args: Any, **kwargs: Any) -> Any:
        pages = read(*args, **{**kwargs, "keep_chars": True})
        dropped, touched = clip_pages(pages, keep_chars=bool(kwargs.get("keep_chars")))
        if dropped:
            logger.info("marker_text_outside_page_box_dropped chars=%d pages=%d", dropped, touched)
        return pages

    _marker_pdf.dictionary_output = clipped
    try:
        yield
    finally:
        _marker_pdf.dictionary_output = read
