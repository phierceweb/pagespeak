"""Tests for backends._layout_geometry."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.backends._layout_geometry import _rect, page_geometry, regions


def test_tiles_join_into_one_picture_area() -> None:
    tiles = [(100 + 2 * i, 100, 102 + 2 * i, 102) for i in range(20)]
    assert regions(tiles, (612, 792)) == [[100, 100, 140, 102]]


def test_far_apart_tiles_stay_apart() -> None:
    assert len(regions([(10, 10, 20, 20), (300, 300, 310, 310)], (612, 792))) == 2


def test_rect_reads_a_closed_axis_aligned_rectangle_only() -> None:
    assert _rect([(0, 0), (10, 0), (10, 5), (0, 5), (0, 0)]) == (0, 0, 10, 5)
    assert _rect([(0, 0), (10, 3), (10, 5), (0, 5)]) is None


def test_a_generated_page_gives_its_rules_and_picture(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from tests.fixtures.layout_book import TABLE_ROWS, make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    geo = page_geometry(doc[2])
    horizontal = [r for r in geo.rules if r[3] - r[1] < 2.5]
    vertical = [r for r in geo.rules if r[2] - r[0] < 2.5]
    assert len(horizontal) == len(TABLE_ROWS) + 1 and len(vertical) == 3
    assert geo.strokes == geo.rules  # every rule here is a drawn line
    assert geo.images == [[72.0, 242.0, 272.0, 342.0]]  # 200 x 100 at top 450, read from the bottom


def test_tiles_on_a_page_whose_corner_is_not_the_origin_are_all_kept() -> None:
    tiles = [(900 + 2 * i, 850, 902 + 2 * i, 852) for i in range(20)]
    assert regions(tiles, (612, 792), origin=(400, 100)) == [[900, 850, 940, 852]]
    assert regions(tiles, (612, 792)) == []  # past a page that starts at the origin


@pytest.mark.parametrize(("rotation", "origin"), [(0, (400, 100)), (90, (0, 0)), (90, (400, 100))])
def test_a_shifted_or_rotated_page_box_gives_the_same_picture_area(
    tmp_path: Path, rotation: int, origin: tuple[float, float]
) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from tests.fixtures.layout_book import make_book, reboxed

    pdf = make_book(tmp_path / "b.pdf", origin=origin)
    doc = pdfium.PdfDocument(str(reboxed(pdf, rotation=rotation)))
    ox, oy = origin
    assert page_geometry(doc[2]).images == [[72.0 + ox, 242.0 + oy, 272.0 + ox, 342.0 + oy]]


def _drawn_page(tmp_path: Path, draw) -> object:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    draw(pdf)
    pdf.output(str(tmp_path / "drawn.pdf"))
    return pdfium.PdfDocument(str(tmp_path / "drawn.pdf"))[0]


def test_a_filled_rectangle_is_a_fill_with_its_colour_and_a_white_one_is_not(
    tmp_path: Path,
) -> None:
    def draw(pdf) -> None:
        pdf.set_fill_color(200, 210, 220)
        pdf.rect(100, 100, 200, 50, style="F")
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(100, 300, 200, 50, style="F")

    geo = page_geometry(_drawn_page(tmp_path, draw))
    assert geo.fills == [[100.0, 642.0, 300.0, 692.0, [200, 210, 220]]]
    assert geo.strokes == []
    assert sorted(r for r in geo.rules if r[1] >= 642) == [  # the tinted rectangle's four edges
        [100.0, 642.0, 100.5, 692.0],
        [100.0, 642.0, 300.0, 642.5],
        [100.0, 691.5, 300.0, 692.0],
        [299.5, 642.0, 300.0, 692.0],
    ]


def test_a_stroked_rectangle_gives_its_four_edges_as_rules(tmp_path: Path) -> None:
    geo = page_geometry(_drawn_page(tmp_path, lambda pdf: pdf.rect(100, 100, 200, 50, style="D")))
    assert sorted(geo.rules) == [
        [100.0, 642.0, 100.5, 692.0],
        [100.0, 642.0, 300.0, 642.5],
        [100.0, 691.5, 300.0, 692.0],
        [299.5, 642.0, 300.0, 692.0],
    ]
    assert geo.fills == [] and geo.strokes == []  # an edge of a box is not a line to write on


def test_a_drawn_line_is_a_rule_and_a_stroke(tmp_path: Path) -> None:
    geo = page_geometry(_drawn_page(tmp_path, lambda pdf: pdf.line(100, 100, 300, 100)))
    assert geo.rules == [[100.0, 692.0, 300.0, 692.0]] and geo.strokes == geo.rules
