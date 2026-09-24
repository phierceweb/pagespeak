"""Audit check `text_coverage`: did the source PDF's own text reach the markdown?

A backend can drop body text and still exit 0 — Docling absorbs prose set
inside figure regions — and no heading or image check sees it. The PDF's
embedded text layer is free ground truth: the share of its distinct words
(two or more characters) found in the converted file. Distinct words, not
raw tokens, so vertically-set labels (one character per run) and repeated
page furniture don't skew the ratio. Below `PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT`
is worth a read; the pages whose words mostly never arrived say where to look.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from pf_core.utils.env import resolve_int

from ._audit_checks import AuditFinding

MIN_TEXT_COVERAGE_PCT_DEFAULT = 90
_MIN_TEXT_COVERAGE_PCT_ENV_VAR = "PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT"
MIN_LAYER_WORDS = 100  # fewer distinct words: a scanned or near-empty text layer
_PAGE_LOW = 0.5
_PAGE_MIN_WORDS = 30
_MAX_PAGES_SHOWN = 10

_NOISE_RE = re.compile(r"[^a-z0-9]+")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]*>")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def min_text_coverage_pct() -> int:
    n: int = resolve_int(
        None, _MIN_TEXT_COVERAGE_PCT_ENV_VAR, default=MIN_TEXT_COVERAGE_PCT_DEFAULT
    )
    return n


def _words(text: str) -> set[str]:
    return {w for w in _NOISE_RE.sub(" ", text.lower()).split() if len(w) > 1}


def markdown_words(md: str) -> set[str]:
    """Distinct words of the visible text: alt kept, image and link targets and tags dropped."""
    text = html.unescape(md)
    text = _IMAGE_RE.sub(lambda m: m.group(0)[2 : m.group(0).index("]")], text)
    text = _TAG_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    return _words(text)


def pdf_page_words(pdf: Path) -> list[set[str]] | None:
    """Distinct words per page of the PDF's text layer; None when the file
    cannot be opened as a PDF. Needs pypdfium2."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(pdf))
    except Exception:  # pdfium raises a bare PdfiumError for a damaged or locked file
        return None
    try:
        pages: list[set[str]] = []
        for i in range(len(doc)):
            try:
                pages.append(_words(doc[i].get_textpage().get_text_bounded()))
            except Exception:  # pdfium raises a bare PdfiumError on a damaged page
                pages.append(set())
        return pages
    finally:
        doc.close()


@dataclass(frozen=True)
class CoverageResult:
    coverage: float | None  # None: the text layer is too thin to judge
    layer_words: int
    low_pages: list[int]  # 1-based


def measure_coverage(md: str, page_words: list[set[str]]) -> CoverageResult:
    layer = set().union(*page_words) if page_words else set()
    if len(layer) < MIN_LAYER_WORDS:
        return CoverageResult(None, len(layer), [])
    found = markdown_words(md)
    low = [
        number
        for number, words in enumerate(page_words, 1)
        if len(words) >= _PAGE_MIN_WORDS and len(words & found) / len(words) < _PAGE_LOW
    ]
    return CoverageResult(len(layer & found) / len(layer), len(layer), low)


def check_text_coverage(md_path: Path, pdf: Path) -> list[AuditFinding]:
    page_words = pdf_page_words(pdf)
    if page_words is None:
        return [
            AuditFinding(
                check="text_coverage",
                severity="warning",
                line=1,
                message=f"{pdf.name} could not be read as a PDF, so coverage was not measured",
            )
        ]
    result = measure_coverage(md_path.read_text(encoding="utf-8", errors="replace"), page_words)
    threshold = min_text_coverage_pct()
    if result.coverage is None or 100 * result.coverage >= threshold:
        return []
    pages = ", ".join(str(n) for n in result.low_pages[:_MAX_PAGES_SHOWN])
    more = len(result.low_pages) - _MAX_PAGES_SHOWN
    where = f"; pages mostly missing: {pages}" if pages else ""
    if more > 0:
        where += f" (+{more} more)"
    return [
        AuditFinding(
            check="text_coverage",
            severity="warning",
            line=1,
            message=(
                f"{result.coverage:.3f} of {pdf.name}'s {result.layer_words} distinct "
                f"text-layer words reached this file (read it below {threshold}%){where}"
            ),
        )
    ]
