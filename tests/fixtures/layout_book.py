"""A small book for the layout backend's tests, built with fpdf2, and the profile that reads it.

Positions are PDF points from the page's top-left (fpdf's convention); pdfium reports
them from the bottom-left, so a baseline at `top` reads back at ``792 - top``. Headings
are Helvetica Bold, body text Times, so the profile can tell them apart by face.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PARAGRAPH = (
    "This chapter opens the book and says what it covers in plain words.",
    "It runs on to a second line of the same paragraph here.",
)
TABLE_ROWS = (("TERM", "MEANING"), ("cell", "a unit of life"), ("tissue", "cells working together"))
# The second chapter page (0-based page 3; a profile reads it with `pages.last: 3`).
SPAN_TITLE = "CHART 1-1. Bones of the arm"
SPAN_HEADER = ("BONE", "PART", "ROLE")
SPAN_ROWS = (
    ("humerus", "head", "joins the scapula"),
    ("", "shaft", "holds the muscles"),  # the bone's cell runs down both rows
    ("ulna", "olecranon", "forms the elbow"),
)


def profile_mapping(origin: tuple[float, float] = (0, 0)) -> dict[str, Any]:
    """The profile for `make_book`; with `origin`, for the book made at that crop-box corner."""
    ox, oy = origin
    return {
        "version": 1,
        "bands": {
            "head_y": 740 + oy,
            "table_rules_below": 740 + oy,
            "floor_y": 40 + oy,
            "page_number_below": 48 + oy,
            "page_number_inner": [100 + ox, 500 + ox],
        },
        "fonts": {
            "furniture": ["Courier"],
            "body": "Times",
            "heading": "Helvetica",
            "label_head_min_cap": 9,
            "headings": [
                {"level": 2, "caps": True, "min_cap": 8, "max_len": 70},
                {
                    "level": 3,
                    "font_suffix": "-Oblique",
                    "min_cap": 8,
                    "max_len": 50,
                    "no_period": True,
                },
            ],
        },
        "patterns": {
            "page_number": "[0-9]{1,3}",
            "figure_caption": r"^PLATE \d+-\d+\.?",
            "table_title": r"^CHART \d+-\d+",
            "reference_line": r"^(CHART|PLATE)\s",
            "reference_run": r"(PLATES?|CHARTS?)\s[\d,;\s-]+",
            "credit": "^Photo:",
            "cell_credit": "©©",
            "cell_credit_fragment": "©©",
            "label_credit": "©©",
            "label_credit_exact": [],
            "note_prefix": r"^REMARK:\s*",
            "list_mark": r"^(•|\d{1,2}\.|[a-z]\.)$",
            "checkbox": "☐",
            "instruction": "^Skip this instruction:",
            "key_entry": r"^\d+\.(\s|$)",
            "stops_heading": r"## .*\bROUTE\b",
            "stops_exclude": "REVIEW",
            "item_heading": "## (CHART |PLATE )",
            "aside_heading": "SUMMARY",
        },
        "pages": {"first": 0, "last": 2, "skip": [1], "flow_charts": []},
        "document": {
            "opener": {
                "text": "PART",
                "above": 700 + oy,
                "font_contains": "Bold",
                "heading": "Part {n}: {title}",
                "titles": ["First Things"],
                "drop_taller_than": 36,
                "drop_font_suffix": "-Light",
                "drop_min_cap": 30,
                "picture_label": "Part {n} picture",
            },
            "title_block": {
                "heading": "A Small Book",
                "cover_page": 0,
                "keep": "^Second Edition",
                "lines": [{"page": 1, "pattern": "^ISBN"}],
            },
        },
    }


def write_profile(path: Path, mapping: dict[str, Any] | None = None) -> Path:
    import yaml

    path.write_text(
        yaml.safe_dump(mapping or profile_mapping(), allow_unicode=True), encoding="utf-8"
    )
    return path


def reboxed(
    path: Path, *, crop: tuple[float, float, float, float] | None = None, rotation: int = 0
) -> Path:
    """The PDF saved again with a crop box and a rotation set on every page."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    for page in doc:
        if crop is not None:
            page.set_cropbox(*crop)
        if rotation:
            page.set_rotation(rotation)
    out = path.with_name(f"{path.stem}-reboxed.pdf")
    doc.save(str(out))
    return out


def _table(pdf: Any, ox: float) -> None:
    left, top, widths, step = 72.0 + ox, 320.0, (150.0, 150.0), 20.0
    pdf.set_line_width(0.5)
    xs = [left, left + widths[0], left + widths[0] + widths[1]]
    for r in range(len(TABLE_ROWS) + 1):
        pdf.line(xs[0], top + r * step, xs[-1], top + r * step)
    for x in xs:
        pdf.line(x, top, x, top + len(TABLE_ROWS) * step)
    for r, row in enumerate(TABLE_ROWS):
        pdf.set_font("Helvetica" if r == 0 else "Times", "B" if r == 0 else "", 10)
        for c, text in enumerate(row):
            pdf.text(xs[c] + 6, top + r * step + 14, text)


def _picture(pdf: Any, tmp: Path, ox: float) -> None:
    from PIL import Image

    img = tmp / "grey.png"
    Image.new("L", (100, 50), 120).save(img)
    pdf.image(str(img), x=72 + ox, y=450, w=200, h=100)
    pdf.set_font("Times", "", 10)
    pdf.text(72 + ox, 570, "PLATE 1-1. A grey picture.")


def _span_table(pdf: Any, ox: float) -> None:
    """A title row across the table, a header row, a first-column cell spanning two rows."""
    xs = [72.0 + ox, 192.0 + ox, 312.0 + ox, 492.0 + ox]
    ys = [200.0 + 20 * r for r in range(6)]
    pdf.set_line_width(0.5)
    for r, y in enumerate(ys):
        pdf.line(xs[1] if r == 3 else xs[0], y, xs[-1], y)  # no rule under the spanning cell
    for c, x in enumerate(xs):
        pdf.line(
            x, ys[1] if c in (1, 2) else ys[0], x, ys[-1]
        )  # the title row has no inner borders
    pdf.set_font("Helvetica", "B", 10)
    pdf.text(xs[0] + 6, ys[0] + 14, SPAN_TITLE)
    for c, text in enumerate(SPAN_HEADER):
        pdf.text(xs[c] + 6, ys[1] + 14, text)
    pdf.set_font("Times", "", 10)
    for r, row in enumerate(SPAN_ROWS):
        for c, text in enumerate(row):
            pdf.text(xs[c] + 6, ys[2 + r] + 14, text)


def _sideways_picture(pdf: Any, tmp: Path, ox: float) -> None:
    """A picture whose caption is set sideways beside it, reading bottom to top."""
    pdf.image(str(tmp / "grey.png"), x=72 + ox, y=400, w=100, h=200)
    pdf.set_font("Times", "", 10)
    with pdf.rotation(90, x=190 + ox, y=600):
        pdf.text(190 + ox, 600, "PLATE 1-2. A picture set sideways.")


def _second_page(pdf: Any, tmp: Path, ox: float) -> None:
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.text(72 + ox, 120, "STRUCTURES")
    pdf.set_font("Helvetica", "I", 12)
    pdf.text(72 + ox, 150, "Bones of the arm")
    pdf.set_font("Times", "", 11)
    pdf.text(72 + ox, 175, "The arm has three long bones.")
    _span_table(pdf, ox)
    _sideways_picture(pdf, tmp, ox)


def _drawing_table(pdf: Any, tmp: Path, ox: float) -> None:
    """A third chapter page (0-based page 4): a titled table whose second column holds a drawing per row."""
    pdf.add_page()
    xs = [72.0 + ox, 222.0 + ox, 372.0 + ox]
    ys = [200.0, 220.0, 240.0, 300.0, 360.0]
    pdf.set_line_width(0.5)
    for y in ys:
        pdf.line(xs[0], y, xs[-1], y)
    for c, x in enumerate(xs):
        pdf.line(x, ys[1] if c == 1 else ys[0], x, ys[-1])
    pdf.set_font("Helvetica", "B", 10)
    pdf.text(xs[0] + 6, ys[0] + 14, "CHART 1-2. Bones to colour")
    pdf.text(xs[0] + 6, ys[1] + 14, "BONE")
    pdf.text(xs[1] + 6, ys[1] + 14, "DRAWING")
    pdf.set_font("Times", "", 10)
    for r, name in enumerate(("humerus", "ulna")):
        pdf.text(xs[0] + 6, ys[2 + r] + 14, name)
        pdf.image(str(tmp / "grey.png"), x=xs[1] + 30, y=ys[2 + r] + 10, w=80, h=40)


def make_book(path: Path, *, origin: tuple[float, float] = (0, 0)) -> Path:
    """Cover, copyright (skipped but read for the ISBN), and three chapter pages.

    With `origin`, the same pages sit in a crop box whose bottom-left corner is there, and
    everything reads back shifted by it.
    """
    import pytest

    FPDF = pytest.importorskip("fpdf").FPDF  # noqa: N806  (a missing dev extra skips the test)
    ox, oy = origin
    pdf = FPDF(unit="pt", format=(612 + ox, 792 + oy))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.text(72 + ox, 200, "A Small Book")
    pdf.set_font("Helvetica", "", 12)
    pdf.text(72 + ox, 240, "Second Edition")
    pdf.add_page()
    pdf.set_font("Times", "", 10)
    pdf.text(72 + ox, 700, "ISBN 978-0-00-000000-0")
    pdf.add_page()
    pdf.set_font("Times", "", 9)
    pdf.text(72 + ox, 40, "A Small Book")  # running head
    pdf.text(560 + ox, 770, "3")  # page number
    pdf.set_font("Helvetica", "B", 12)
    pdf.text(72 + ox, 60, "PART")
    pdf.set_font("Helvetica", "B", 14)
    pdf.text(72 + ox, 160, "INTRODUCTION")
    pdf.set_font("Times", "", 11)
    for i, line in enumerate(PARAGRAPH):
        pdf.text(72 + ox, 200 + i * 14, line)
    for i, step in enumerate(("First step to take.", "Second step to take.")):
        pdf.text(72 + ox, 260 + i * 14, f"{i + 1}.")
        pdf.text(90 + ox, 260 + i * 14, step)
    _table(pdf, ox)
    _picture(pdf, path.parent, ox)
    _second_page(pdf, path.parent, ox)
    _drawing_table(pdf, path.parent, ox)
    pdf.output(str(path))
    if origin != (0, 0):
        return reboxed(path, crop=(ox, oy, 612 + ox, 792 + oy))
    return path
