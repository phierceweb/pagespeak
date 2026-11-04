"""Tests for services._pdf_glyphs — the glyphs a reader sees on a PDF page."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")


def _read(path: Path) -> str:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    from pagespeak.services._pdf_glyphs import clipped_text, page_glyphs

    page = pdfium.PdfDocument(str(path))[0]
    tp = page.get_textpage()
    return "".join(g.ch for g in page_glyphs(raw, tp.raw, None, clipped_text(page, raw, tp.raw)))


def test_text_a_clip_path_hides_is_not_read(tmp_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    pdf.text(72, 100, "Body")
    with pdf.rect_clip(x=300, y=300, w=200, h=100):
        pdf.text(320, 350, "Shown")
        pdf.text(72, 500, "Hidden")
    path = tmp_path / "a.pdf"
    pdf.output(str(path))
    assert _read(path) == "BodyShown"


def test_a_turned_glyph_advances_right_to_left(tmp_path: Path) -> None:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    from pagespeak.services._pdf_glyphs import page_glyphs
    from tests.fixtures.pdf_pages import raw_pdf

    pdf = raw_pdf(tmp_path / "a.pdf", b"BT /F1 10 Tf -1 0 0 -1 300 600 Tm (Upside) Tj ET\n")
    page = pdfium.PdfDocument(str(pdf))[0]
    tp = page.get_textpage()
    glyphs = page_glyphs(raw, tp.raw)
    assert [g.ch for g in glyphs] == list("Upside")
    assert all(g.left > g.right for g in glyphs)
    assert glyphs[0].left == pytest.approx(300.0, abs=0.01)


def test_a_hidden_label_over_body_text_takes_none_of_its_letters(tmp_path: Path) -> None:
    """A label drawn outside its clip, across a line of the page that shares its
    letters, hides only its own glyphs."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    pdf.text(72, 400, "This space is open")
    with pdf.rect_clip(x=300, y=100, w=200, h=100):
        pdf.text(88, 398, "space")
    path = tmp_path / "a.pdf"
    pdf.output(str(path))
    assert _read(path) == "Thisspaceisopen"
