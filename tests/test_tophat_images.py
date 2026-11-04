"""Tests for `backends/_tophat_images.py`: figure→question binding, and
`extract_question_images` on a generated PDF."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.backends import _tophat_images as ti


def test_a_figure_is_pulled_out_for_its_question(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    fpdf = pytest.importorskip("fpdf")
    from PIL import Image

    figure = tmp_path / "figure.png"
    Image.new("RGB", (200, 160), (30, 90, 160)).save(figure)
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.text(72, 72, "Question 1")
    pdf.image(str(figure), x=72, y=100, w=200, h=160)
    path = tmp_path / "quiz.pdf"
    pdf.output(str(path))

    assert ti.extract_question_images(path, tmp_path / "images") == {1: ["images/q1_1.png"]}
    with Image.open(tmp_path / "images" / "q1_1.png") as png:
        assert (png.size, png.getpixel((100, 80))) == ((200, 160), (30, 90, 160))


def test_a_figure_drawn_inside_a_form_is_pulled_out(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    from PIL import Image

    from tests.fixtures.pdf_pages import raw_pdf, text_at

    pdf = raw_pdf(
        tmp_path / "quiz.pdf",
        text_at(72, 720, "Question 1") + b"q 1 0 0 1 72 300 cm /Fm1 Do Q\n",
        forms={"Fm1": b"q 200 0 0 160 0 0 cm /Im1 Do Q"},
        images={"Im1": (200, 160, bytes([30, 90, 160]) * (200 * 160))},
    )
    assert ti.extract_question_images(pdf, tmp_path / "images") == {1: ["images/q1_1.png"]}
    with Image.open(tmp_path / "images" / "q1_1.png") as png:
        assert (png.size, png.getpixel((100, 80))) == ((200, 160), (30, 90, 160))


def test_bind_image_to_marker_on_same_page() -> None:
    # one marker + one figure on page 0 → figure belongs to that question
    # (the figure's own top is form-local garbage and must be ignored)
    markers = [(0, 365.0, 1)]
    images = [(0, 2769.0)]
    assert ti.bind_images_to_questions(markers, images) == {1: [0]}


def test_bind_image_on_later_page_to_latest_marker() -> None:
    # a figure on a marker-less page binds to the last marker on an earlier page
    markers = [(6, 678.0, 10), (6, 451.0, 11), (8, 662.0, 12)]
    images = [(7, 2875.0)]  # page 7, between Q11 (page 6) and Q12 (page 8)
    assert ti.bind_images_to_questions(markers, images) == {11: [0]}


def test_bind_uses_lowest_marker_within_a_page() -> None:
    # two markers on page 6 (Q10 above Q11); a later-page image binds to Q11
    markers = [(6, 678.0, 10), (6, 451.0, 11)]
    images = [(7, 100.0)]
    assert ti.bind_images_to_questions(markers, images) == {11: [0]}


def test_bind_drops_image_on_page_before_any_marker() -> None:
    markers = [(1, 500.0, 2)]
    images = [(0, 900.0)]  # page 0, before the first marker's page
    assert ti.bind_images_to_questions(markers, images) == {}


def test_bind_multiple_images_one_question_extraction_order() -> None:
    markers = [(0, 900.0, 3)]
    images = [(0, 300.0), (0, 600.0)]  # both on Q3's page; kept in extraction order
    assert ti.bind_images_to_questions(markers, images) == {3: [0, 1]}


def test_bind_images_to_different_questions() -> None:
    markers = [(0, 900.0, 1), (1, 900.0, 2)]
    images = [(0, 500.0), (1, 500.0)]
    assert ti.bind_images_to_questions(markers, images) == {1: [0], 2: [1]}
