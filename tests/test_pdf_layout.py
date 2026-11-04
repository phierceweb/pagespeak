"""Tests for services._pdf_layout — which parts of a PDF page are layout, not drawing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.pdf_pages import PAGE_HEIGHT, Page, make_pdf, raw_pdf, text_at

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")


def _layout(tmp_path: Path, page: Page) -> list[tuple[float, float, float, float]]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    from pagespeak.services._pdf_layout import layout_boxes

    pdf = pdfium.PdfDocument(str(make_pdf(tmp_path / "a.pdf", [page])))
    return layout_boxes(pdf[0], raw)


def _covers(boxes: list[tuple[float, float, float, float]], x: float, y: float) -> bool:
    return any(b[0] - 2 <= x <= b[2] + 2 and b[1] - 2 <= y <= b[3] + 2 for b in boxes)


def _raw_layout(path: Path) -> list[tuple[float, float, float, float]]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    from pagespeak.services._pdf_layout import layout_boxes

    return layout_boxes(pdfium.PdfDocument(str(path))[0], raw)


def test_layout_inside_a_form_is_placed_where_the_form_is_drawn(tmp_path: Path) -> None:
    form = b"1 w 0 10 m 400 10 l S\n" + text_at(0, 20, "Form label", size=10)
    content = b"q 1 0 0 1 100 300 cm /Fm1 Do Q\n"
    boxes = _raw_layout(raw_pdf(tmp_path / "a.pdf", content, forms={"Fm1": form}))
    assert _covers(boxes, 300, 310) and _covers(boxes, 120, 323)
    assert not _covers(boxes, 200, 10)


def test_a_slanted_stroked_bar_is_a_separator(tmp_path: Path) -> None:
    boxes = _layout(tmp_path, Page(rules=[(100, 300, 300, 294)]))
    assert _covers(boxes, 200, PAGE_HEIGHT - 297)


def test_a_run_of_type_is_layout_but_display_type_is_not(tmp_path: Path) -> None:
    content = text_at(72, 600, "Big", size=40) + text_at(300, 500, "One run")
    boxes = _raw_layout(raw_pdf(tmp_path / "a.pdf", content))
    assert _covers(boxes, 320, 503)
    assert not any(b[3] - b[1] > 24 for b in boxes)


def test_a_drawing_is_not_layout(tmp_path: Path) -> None:
    assert _layout(tmp_path, Page(drawings=[(200, 300, 120, 90)])) == []


def test_a_rule_is_layout(tmp_path: Path) -> None:
    boxes = _layout(tmp_path, Page(rules=[(72, 400, 500, 400)]))
    assert _covers(boxes, 300, PAGE_HEIGHT - 400)


def test_a_wide_rounded_corner_is_covered_where_it_bows_in(tmp_path: Path) -> None:
    boxes = _layout(tmp_path, Page(panels=[(80, 200, 400, 300)], panel_radius=30))
    # The arc's middle sits about 9pt in from the box's corner, off both straight edges.
    assert _covers(boxes, 80 + 9, PAGE_HEIGHT - 200 - 9)


def test_a_hairline_frame_filled_as_a_ring_is_layout_but_its_inside_is_not(tmp_path: Path) -> None:
    boxes = _layout(tmp_path, Page(frames=[(80, 200, 300, 300)]))
    assert _covers(boxes, 80.2, PAGE_HEIGHT - 350)  # its left side
    assert not _covers(boxes, 230, PAGE_HEIGHT - 350)  # the middle of what it frames


def test_a_small_solid_shape_with_level_edges_is_a_drawing(tmp_path: Path) -> None:
    """An L-shaped block in a drawing is not a frame, though its edges are all level and upright."""
    ell = [(200, 300), (230, 300), (230, 320), (215, 320), (215, 340), (200, 340)]
    assert _layout(tmp_path, Page(polygons=[ell])) == []
