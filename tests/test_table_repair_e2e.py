"""Real, un-mocked end-to-end test for the Docling table-splice.

Generates a bordered 3-column table PDF (fpdf2), then runs the REAL
`locate_page_in_pdf` (pypdfium2 text search) + REAL `docling_page_md` (Docling
single-page ingest) to repair a Marker-collapse-shaped `raw.md` — closing the
gap that the unit tests (which mock both I/O calls) leave open.

Gated on the `pdf-docling` extra (Docling) and the dev `fpdf2` fixture
generator; skipped cleanly when either is absent (so a minimal install does not
error at collection). Slow (~real Docling model load + convert) — a Tier-3
real-backend smoke, not a fast unit test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docling")
pytest.importorskip("fpdf")

from pagespeak.services._table_repair import (  # noqa: E402
    find_collapsed_cells,
    locate_pages_in_pdf,
    repair_tables_in_markdown,
)

_HEADERS = ["Profile Type", "Database", "Extension"]
_ROWS = [
    ["Data Pump Export Profile", "Oracle", ".nbakora"],
    ["Data View Profile", "Redis", ".ndvredis"],
    ["ER Diagram File", "PostgreSQL", ".ned"],
]


@pytest.fixture(scope="module")
def table_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A one-page PDF holding a real bordered 3-column table."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "Connection Profile Types")
    pdf.ln(16)
    pdf.set_font("Helvetica", size=10)
    widths = (70, 55, 40)
    for header, w in zip(_HEADERS, widths, strict=True):
        pdf.cell(w, 9, header, border=1)
    pdf.ln()
    for row in _ROWS:
        for val, w in zip(row, widths, strict=True):
            pdf.cell(w, 9, val, border=1)
        pdf.ln()
    out = tmp_path_factory.mktemp("repair_e2e") / "profiles.pdf"
    pdf.output(str(out))
    return out


def _collapsed_raw_md() -> str:
    """Marker-collapse shape: the whole table jammed into one `<br>`-joined
    mega-cell, repeated enough to clear the 30-`<br>` threshold."""
    segs: list[str] = []
    for row in [_HEADERS, *_ROWS] * 6:
        segs.extend(row)
    blob = "<br>".join(segs)
    return f"# Profiles\n\n| {blob} |  |  |\n| --- | --- | --- |\n|  |  |  |\n\nEnd.\n"


def test_locate_pages_in_pdf_finds_the_table_page(table_pdf: Path) -> None:
    """Real pypdfium2 text search locates the page(s) holding the table text."""
    assert locate_pages_in_pdf("Data Pump Export Profile", str(table_pdf)) == [0]


def test_real_docling_splice_repairs_collapsed_table(table_pdf: Path) -> None:
    """Full real path: Docling re-reads the page, the grid matches the collapsed
    mega-cell by content, and it is spliced in — no `<br>` blob left, the table
    values present as a clean grid, surrounding prose intact."""
    raw = _collapsed_raw_md()
    assert find_collapsed_cells(raw)  # precondition: it really is collapsed
    repaired, records = repair_tables_in_markdown(raw, str(table_pdf))
    assert records and records[0].status == "repaired", records
    assert "<br>" not in repaired
    assert "Data Pump Export Profile" in repaired
    assert "Oracle" in repaired and ".nbakora" in repaired
    assert "# Profiles" in repaired and "End." in repaired  # surrounding preserved
