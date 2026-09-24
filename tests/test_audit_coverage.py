"""Tests for services._audit_coverage — did the PDF's own text reach the markdown?"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from pagespeak.services._audit_coverage import (
    MIN_TEXT_COVERAGE_PCT_DEFAULT,
    check_text_coverage,
    markdown_words,
    measure_coverage,
    min_text_coverage_pct,
)


def _page(start: int, n: int = 60) -> str:
    return " ".join(f"word{i:04d}" for i in range(start, start + n))


def test_markdown_words_ignore_image_targets_tags_and_link_targets() -> None:
    md = '![alt text](images/hidden.png) <span id="p">kept</span> [label](other.md)'
    assert markdown_words(md) == {"alt", "text", "kept", "label"}


def test_coverage_names_the_pages_that_went_missing() -> None:
    pages = [set(_page(0).split()), set(_page(100).split())]
    result = measure_coverage(_page(0), pages)
    assert result.coverage == pytest.approx(0.5)
    assert result.low_pages == [2]


def test_a_thin_text_layer_is_not_assessable() -> None:
    """Under ~100 distinct words the PDF is scanned or near-empty; coverage means nothing."""
    result = measure_coverage("", [set(_page(0, 40).split())])
    assert result.coverage is None


def _make_text_pdf(path: Path, pages: list[str]) -> None:
    pdfium = pytest.importorskip("pypdfium2")
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument.new()
    raw.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    for text in pages:
        page = doc.new_page(612, 792)
        words = text.split()
        for row in range(0, len(words), 6):  # six words a line keeps text on the page
            obj = raw.FPDFPageObj_NewTextObj(doc.raw, b"Helvetica", ctypes.c_float(10))
            line = " ".join(words[row : row + 6]) + "\x00"
            buf = ctypes.create_string_buffer(line.encode("utf-16-le"))
            raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
            raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 40, 740 - 2 * row)
            raw.FPDFPage_InsertObject(page.raw, obj)
        raw.FPDFPage_GenerateContent(page.raw)
    doc.save(str(path))


def test_check_text_coverage_reads_the_pdf_text_layer(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_text_pdf(pdf, [_page(0), _page(100)])
    md = tmp_path / "doc.raw.md"
    md.write_text(f"# Doc\n\n{_page(0)}\n", encoding="utf-8")

    findings = check_text_coverage(md, pdf)
    assert [f.check for f in findings] == ["text_coverage"]
    assert "0.500" in findings[0].message
    assert "pages mostly missing: 2" in findings[0].message

    md.write_text(f"# Doc\n\n{_page(0)}\n\n{_page(100)}\n", encoding="utf-8")
    assert check_text_coverage(md, pdf) == []


def test_an_unreadable_source_is_reported_not_raised(tmp_path: Path) -> None:
    """One damaged or encrypted PDF must not stop the audit of a whole corpus."""
    pytest.importorskip("pypdfium2")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"not a pdf")
    md = tmp_path / "doc.raw.md"
    md.write_text("# Doc\n", encoding="utf-8")

    findings = check_text_coverage(md, pdf)
    assert [f.check for f in findings] == ["text_coverage"]
    assert "could not be read" in findings[0].message


def test_threshold_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_text_pdf(pdf, [_page(0), _page(100)])
    md = tmp_path / "doc.raw.md"
    md.write_text(f"# Doc\n\n{_page(0)}\n", encoding="utf-8")

    assert min_text_coverage_pct() == MIN_TEXT_COVERAGE_PCT_DEFAULT
    assert "below 90%" in check_text_coverage(md, pdf)[0].message
    monkeypatch.setenv("PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT", "40")
    assert check_text_coverage(md, pdf) == []
    monkeypatch.setenv("PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT", "not-a-number")
    assert min_text_coverage_pct() == MIN_TEXT_COVERAGE_PCT_DEFAULT
