"""Tests for backends._layout_pages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.backends._layout_pages import read_page


def test_a_page_record_holds_size_box_lines_and_geometry(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    rec = read_page(doc, 2)
    assert (
        rec["page"] == 2
        and rec["size"] == [612.0, 792.0]
        and rec["box"] == [0.0, 0.0, 612.0, 792.0]
    )
    assert set(rec) == {
        "page",
        "size",
        "box",
        "lines",
        "images",
        "fills",
        "rules",
        "art",
        "strokes",
        "slim",
    }
    assert any(ln["text"] == "INTRODUCTION" for ln in rec["lines"])
    assert json.loads(json.dumps(rec)) == rec  # a record survives a JSON round trip unchanged


def test_read_page_passes_the_acute_switch_down_to_the_lines(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Times", "", 11)
    pdf.text(72, 200, "re\u00b4cord")
    pdf.output(str(tmp_path / "a.pdf"))
    doc = pdfium.PdfDocument(str(tmp_path / "a.pdf"))
    assert [ln["text"] for ln in read_page(doc, 0)["lines"]] == ["re\u00b4cord"]
    assert [ln["text"] for ln in read_page(doc, 0, acute_as_prime=True)["lines"]] == [
        "re\u2032cord"
    ]
