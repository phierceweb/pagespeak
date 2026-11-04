"""Marker's text layer, keeping only the text inside each page's visible box.

pdftext, which Marker reads a PDF's text layer with, places every character
relative to the box pdfium reports for the page (its CropBox, within the
MediaBox) but keeps the characters that lie outside it. A page cut from a
two-page spread by its CropBox still holds the facing page's text, and pdftext
joins it to this page's line when the two share a baseline and font: the page's
title arrives glued to the facing page's. `clipped_to_page_box` drops each word
whose middle lies outside its page's box (a word the box's edge runs through goes
whole to one page, however pdftext split it into spans; a character of a script
written without spaces goes by its own middle) before Marker builds the page or
reads its tables, and rebuilds a span that lost one from the characters left.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import marker.providers.pdf as _marker_pdf
import pdftext.extraction as _pdftext
from pdftext.postprocessing import handle_hyphens, postprocess_text
from pw_foundation.log import get_logger

from ._marker_ignoretext import _as_bool

logger = get_logger(__name__)

# Named like Marker's own provider keys (`PdfProvider_pdftext_workers`).
CONFIG_KEY = "PdfProvider_clip_to_page_box"


def centre_inside(bbox: Sequence[float], box: Sequence[float]) -> bool:
    """True when the bbox's centre lies in the box: its near edges count, its far
    edges belong to the next page, so a centre on a cut lands on one page."""
    x = (bbox[0] + bbox[2]) / 2
    y = (bbox[1] + bbox[3]) / 2
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def page_box(page: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """The page's visible box in pdftext's coordinates. pdftext rounds the page's
    size up and measures from the rounded size, which moves the true edges off
    (0, 0, width, height) by the rounding, on sides that depend on /Rotate."""
    x0, y0, x1, y1 = page["bbox"]
    w, h = abs(x1 - x0), abs(y1 - y0)
    dw, dh = math.ceil(w) - w, math.ceil(h) - h
    boxes = {90: (0.0, 0.0, h, w), 180: (dw, 0.0, w + dw, h), 270: (dh, dw, h + dh, w + dw)}
    return boxes.get(int(page.get("rotation", 0)) % 360, (0.0, dh, w, h + dh))


def _merged(bboxes: Sequence[Sequence[float]]) -> list[float]:
    return [
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    ]


def _rebuild(span: dict[str, Any], chars: list[dict[str, Any]]) -> None:
    """The span's text, box and character range rebuilt from these characters, as
    pdftext builds them; its line grouping and flags stay as pdftext set them."""
    span["chars"] = chars
    raw = "".join(c["char"] for c in chars)
    span["text"] = handle_hyphens(postprocess_text(raw), keep_hyphens=True)
    span["bbox"] = _merged([c["bbox"] for c in chars])
    span["char_start_idx"] = chars[0]["char_idx"]
    span["char_end_idx"] = chars[-1]["char_idx"]


def _on_page(chars: list[dict[str, Any]], box: Sequence[float]) -> list[dict[str, Any]]:
    """A line's characters this page shows: each word whole where its middle lies in
    the box, so a word the gutter runs through goes to one page; a space, and a
    wide (CJK) character, which needs no space around it, by its own middle."""
    out: list[dict[str, Any]] = []
    word: list[dict[str, Any]] = []

    def end_word() -> None:
        if word and centre_inside(_merged([c["bbox"] for c in word]), box):
            out.extend(word)
        word.clear()

    for c in chars:
        if c["char"].isspace() or unicodedata.east_asian_width(c["char"][:1] or " ") in "WF":
            end_word()
            if centre_inside(c["bbox"], box):
                out.append(c)
        else:
            word.append(c)
    end_word()
    return out


def clip_pages(pages: list[dict[str, Any]], *, keep_chars: bool) -> tuple[int, int]:
    """Drop what lies outside each page's box (`_on_page`) from pdftext's
    `dictionary_output`, read with `keep_chars=True`, in place. Without `keep_chars`
    the characters are then removed, as pdftext removes them. Returns (characters
    dropped, pages touched)."""
    dropped = touched = 0
    for page in pages:
        box = page_box(page)
        on_page = dropped
        blocks = []
        for block in page["blocks"]:
            lines = []
            for line in block["lines"]:
                kept = {
                    id(c) for c in _on_page([c for s in line["spans"] for c in s["chars"]], box)
                }
                spans = []
                for span in line["spans"]:
                    chars = span["chars"]
                    inside = [c for c in chars if id(c) in kept]
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


def _clipping(read: Any, what: str) -> Any:
    def clipped(*args: Any, **kwargs: Any) -> Any:
        pages = read(*args, **{**kwargs, "keep_chars": True})
        dropped, touched = clip_pages(pages, keep_chars=bool(kwargs.get("keep_chars")))
        if dropped:
            logger.info(
                "marker_text_outside_page_box_dropped read=%s chars=%d pages=%d",
                what,
                dropped,
                touched,
            )
        return pages

    return clipped


@contextmanager
def clipped_to_page_box(config: Mapping[str, object]) -> Iterator[None]:
    """Clip the text Marker reads during the call, unless `config` turns it off.

    Marker's `PdfProvider` reads pdftext through `marker.providers.pdf.dictionary_output`;
    its table processor reads a page again through `pdftext.extraction.table_output`,
    which calls `pdftext.extraction.dictionary_output`.
    """
    if not _as_bool(config.get(CONFIG_KEY, True)):
        yield
        return
    read, table_read = _marker_pdf.dictionary_output, _pdftext.dictionary_output
    _marker_pdf.dictionary_output = _clipping(read, "page")
    _pdftext.dictionary_output = _clipping(table_read, "tables")
    try:
        yield
    finally:
        _marker_pdf.dictionary_output = read
        _pdftext.dictionary_output = table_read
