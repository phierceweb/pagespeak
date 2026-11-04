"""Tests for services._pdf_ink — ink on a page once its text, rules and flat boxes are painted out."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._pdf_ink import ink_blobs
from pagespeak.services._pdf_lines import read_pages
from tests.fixtures.pdf_pages import (
    PAGE_HEIGHT,
    Page,
    body_lines,
    disc,
    make_pdf,
    raw_pdf,
    text_at,
)

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")


def _blobs(
    tmp_path: Path, page: Page, painted: list[tuple[float, float, float, float]] | None = None
) -> list:
    pdf = make_pdf(tmp_path / "a.pdf", [page])
    pages = read_pages(pdf, [1])
    return ink_blobs(pdf, pages, {1: painted or []}, min_dark=15)[1]


_DISC_PICTURE = (268.0, 368.0, 332.0, 432.0)


def _raw_blobs(
    pdf: Path, pictures: list[tuple[float, float, float, float]]
) -> list[tuple[int, ...]]:
    pages = read_pages(pdf, [1])
    found = ink_blobs(pdf, pages, {1: []}, min_dark=150, pictures={1: pictures})[1]
    return [tuple(round(v) for v in b.box) for b in found]


@pytest.mark.parametrize("turned", [90, 180, 270])
def test_ink_on_a_turned_page_is_where_its_boxes_say(tmp_path: Path, turned: int) -> None:
    pdf = raw_pdf(tmp_path / "a.pdf", disc(300, 400, 30), rotate=turned)
    assert _raw_blobs(pdf, [_DISC_PICTURE]) == []
    assert len(_raw_blobs(pdf, [])) == 1


def test_a_crop_box_past_the_media_box_keeps_ink_in_place(tmp_path: Path) -> None:
    pdf = raw_pdf(tmp_path / "a.pdf", disc(300, 400, 30), crop="-50 -50 662 842")
    assert _raw_blobs(pdf, [_DISC_PICTURE]) == []


def test_a_page_whose_crop_box_misses_its_media_box_has_no_ink(tmp_path: Path) -> None:
    pdf = raw_pdf(tmp_path / "a.pdf", disc(300, 400, 30), crop="700 800 900 1000")
    assert _raw_blobs(pdf, []) == []


def test_annotations_are_not_ink(tmp_path: Path) -> None:
    square = b"<< /Type /Annot /Subtype /Square /Rect [300 300 450 400] /C [0 0 0] /BS << /W 2 >> /F 4 >>"
    pdf = raw_pdf(tmp_path / "a.pdf", text_at(72, 700, "See the note"), annots=(square,))
    assert _raw_blobs(pdf, []) == []


def test_a_drawing_is_ink(tmp_path: Path) -> None:
    (blob,) = _blobs(tmp_path, Page(drawings=[(200, 300, 120, 90)]))
    x0, y0, x1, y1 = blob.box
    assert 190 <= x0 <= 205 and 315 <= x1 <= 330
    assert PAGE_HEIGHT - 395 <= y0 <= PAGE_HEIGHT - 385
    assert blob.dark > 5000


def test_text_rules_and_flat_boxes_are_not_ink(tmp_path: Path) -> None:
    page = Page(
        lines=body_lines(["Body text that is long enough to carry real ink on the page."] * 4),
        rules=[(72, 400, 500, 400), (72, 420, 72, 520)],
        boxes=[(300, 450, 200, 60)],
        panels=[(80, 560, 300, 120)],
    )
    assert _blobs(tmp_path, page) == []


def test_painted_areas_hide_their_ink(tmp_path: Path) -> None:
    page = Page(drawings=[(200, 300, 120, 90)])
    box = (190.0, PAGE_HEIGHT - 400, 330.0, PAGE_HEIGHT - 290)
    assert _blobs(tmp_path, page, painted=[box]) == []


def test_a_hairline_frame_drawn_as_a_filled_ring_is_not_ink(tmp_path: Path) -> None:
    assert _blobs(tmp_path, Page(frames=[(80, 200, 300, 300)])) == []


def test_a_panel_with_wide_rounded_corners_is_not_ink(tmp_path: Path) -> None:
    assert _blobs(tmp_path, Page(panels=[(80, 200, 400, 300)], panel_radius=30)) == []


def test_a_small_drawing_carries_its_whole_shape_even_where_a_picture_covers_part(
    tmp_path: Path,
) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", [Page(drawings=[(200, 300, 40, 30)])])
    pages = read_pages(pdf, [1])
    covered = (220.0, PAGE_HEIGHT - 340, 300.0, PAGE_HEIGHT - 290)  # its right half
    (blob,) = ink_blobs(pdf, pages, {1: []}, min_dark=15, pictures={1: [covered]})[1]
    assert blob.box[2] <= 226  # only the left half is ink outside the picture…
    assert blob.shape is not None and 38 <= blob.shape.width <= 42  # …but the shape is whole


def test_a_small_drawing_in_the_margins_comes_back_as_a_margin_blob(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", [Page(drawings=[(480, 750, 30, 24)])])
    foot = (0.0, 0.0, 612.0, 50.0)
    (blob,) = ink_blobs(pdf, read_pages(pdf, [1]), {1: []}, min_dark=15, margins={1: [foot]})[1]
    assert blob.margin and blob.shape is not None


def test_sideways_text_is_not_ink(tmp_path: Path) -> None:
    """A large word set sideways is text, not a drawing, though the line reader skips it."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Helvetica", size=36)  # too thick a run to pass as layout type
    with pdf.rotation(90, 300, 400):
        pdf.text(200, 400, "SIDEWAYS")
    path = tmp_path / "a.pdf"
    pdf.output(str(path))
    pages = read_pages(path, [1])
    assert pages[1].lines == [] and pages[1].sideways
    assert ink_blobs(path, pages, {1: []}, min_dark=15)[1] == []
