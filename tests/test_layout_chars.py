"""Tests for backends._layout_chars."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.backends._layout_chars import deduped, folded, hidden_chars, page_chars


def ch(
    c: str, x0: float, *, y0: float = 100.0, width: float = 5.0, font: str = "Times-Roman"
) -> tuple:
    return (c, font, x0, x0 + width, y0, y0 + 7, y0, 11.0, 0.0, x0)


def test_a_glyph_drawn_twice_is_kept_once() -> None:
    chars = [ch("A", 10), ch("A", 10.3), ch("B", 20)]
    assert [c[0] for c in deduped(chars)] == ["A", "B"]


def test_the_two_halves_of_a_ligature_are_not_a_copy() -> None:
    chars = [ch("f", 10), ch("f", 10)]
    assert len(deduped(chars)) == 2


def test_a_spacing_accent_folds_into_the_letter_under_it() -> None:
    out = folded([ch("e", 10), ch("¨", 10.5, width=3)])
    assert [c[0] for c in out] == ["ë"]


def test_an_accent_before_its_letter_folds_forward() -> None:
    out = folded([ch("˜", 10.5, width=3), ch("n", 10)])
    assert [c[0] for c in out] == ["ñ"]


def test_a_combining_mark_joins_the_letter_before() -> None:
    assert [c[0] for c in folded([ch("a", 10), ch("̈", 12, width=0.1)])] == ["ä"]


def test_a_combining_acute_joins_its_letter_and_a_spacing_acute_is_left_as_printed() -> None:
    assert [c[0] for c in folded([ch("e", 10), ch("\u0301", 12, width=0.1)])] == ["é"]
    apostrophe = [ch("n", 10), ch("´", 14.5, width=2), ch("t", 15.5)]  # set over the next letter
    assert [c[0] for c in folded(apostrophe)] == ["n", "´", "t"]
    assert [c[0] for c in folded([ch("e", 10), ch("´", 10.5, width=3)])] == ["e", "´"]


@pytest.mark.parametrize("mark", ["\u0301", "´", "΄", "ʹ", "ˊ"])
def test_where_the_profile_says_so_an_acute_is_a_stress_prime_after_its_syllable(mark: str) -> None:
    chars = [ch("a", 10), ch(" ", 15, width=2), ch(mark, 17, width=2), ch("b", 20)]
    assert [c[0] for c in folded(chars, acute_as_prime=True)] == ["a", "′", "b"]


def test_thin_and_no_break_spaces_are_word_spaces() -> None:
    assert [c[0] for c in folded([ch("a", 10), ch("\xa0", 15), ch("b", 20)])] == ["a", " ", "b"]


def test_a_zero_width_space_marks_a_word_break() -> None:
    assert folded([ch(" ", 10, width=0.2)])[0][0] == "\x00"


def test_hidden_letters_are_found_in_order_inside_their_box() -> None:
    chars = [ch("X", 10), ch("Y", 16), ch("Z", 200)]
    assert hidden_chars(chars, [("XY", (5.0, 90.0, 30.0, 120.0))]) == {0, 1}


def test_a_hidden_copy_of_drawn_letters_is_left_to_deduplication() -> None:
    chars = [ch("X", 10), ch("X", 10.2)]
    assert hidden_chars(chars, [("X", (5.0, 90.0, 30.0, 120.0))]) == set()


def test_page_chars_read_a_generated_page(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    chars = list(page_chars(doc[0].get_textpage()))
    text = "".join(c[0] for c in chars)
    assert "A Small Book" in text
    assert all(len(c) == 10 for c in chars)
    assert any(c[1].startswith("Helvetica") for c in chars)


def test_text_drawn_outside_its_clipping_path_is_not_read(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page

    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Times", "", 11)
    pdf.text(72, 100, "Shown on the page")
    with pdf.rect_clip(x=300, y=300, w=50, h=50):
        pdf.text(
            72, 200, "Clipped away"
        )  # set outside the clip: in the text layer, not on the page
        pdf.text(305, 330, "In")
    pdf.output(str(tmp_path / "clip.pdf"))
    lines = read_page(pdfium.PdfDocument(str(tmp_path / "clip.pdf")), 0)["lines"]
    assert sorted(ln["text"] for ln in lines) == ["In", "Shown on the page"]


def _clipped_text(tmp_path: Path, at: tuple[float, float], clip: tuple, crop: tuple | None) -> list:
    """The lines read from a page holding one text object set at `at` inside the clip rectangle `clip`."""
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page

    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Times", "", 11)
    with pdf.rect_clip(x=clip[0], y=clip[1], w=clip[2], h=clip[3]):
        pdf.text(at[0], at[1], "Set in a clip")
    pdf.output(str(tmp_path / "clip.pdf"))
    doc = pdfium.PdfDocument(str(tmp_path / "clip.pdf"))
    if crop is not None:
        doc[0].set_cropbox(*crop)
        doc.save(str(tmp_path / "cropped.pdf"))
        doc = pdfium.PdfDocument(str(tmp_path / "cropped.pdf"))
    return [ln["text"] for ln in read_page(doc, 0)["lines"]]


def test_text_shown_through_its_clipping_path_is_read(tmp_path: Path) -> None:
    assert _clipped_text(tmp_path, (72, 100), (60, 80, 300, 60), None) == ["Set in a clip"]


def test_text_clipped_away_is_hidden_on_the_page_and_read_outside_the_crop_box(
    tmp_path: Path,
) -> None:
    low, elsewhere = (72, 750), (300, 300, 50, 50)  # set near the sheet's foot, clipped away
    assert _clipped_text(tmp_path, low, elsewhere, None) == []
    # below the crop box nothing is judged hidden: the whole text layer there is read
    assert _clipped_text(tmp_path, low, elsewhere, (0, 100, 612, 792)) == ["Set in a clip"]
