"""Tests for backends._layout_lines."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pagespeak.backends._layout_lines import _finish, _group, _vertical, page_lines


def ch(
    c: str,
    x0: float,
    *,
    base: float = 100.0,
    height: float = 7.0,
    font: str = "Times-Roman",
    angle: float = 0.0,
) -> tuple:
    return (c, font, x0, x0 + 5, base, base + height, base, 11.0, angle, x0)


def word(text: str, x0: float, **kw) -> list[tuple]:
    return [ch(c, x0 + 5 * i, **kw) for i, c in enumerate(text)]


def lines(chars: list[tuple]) -> list[dict]:
    return [ln for ln in (_finish(ln) for ln in _group(chars)) if ln is not None]


def test_letters_on_one_baseline_make_one_line_with_a_space_at_a_gap() -> None:
    # "b" ends at x 20: a 4pt gap is wider than kerning (3.15 for 7pt type) and narrower than a gutter (7)
    out = lines(word("ab", 10) + word("cd", 24))
    assert [ln["text"] for ln in out] == ["ab cd"]
    assert [ln["text"] for ln in lines(word("ab", 10) + word("cd", 22))] == ["abcd"]


def test_a_gutter_wide_gap_starts_a_new_line() -> None:
    assert [ln["text"] for ln in lines(word("ab", 10) + word("cd", 100))] == ["ab", "cd"]


def test_a_new_baseline_starts_a_new_line() -> None:
    assert [ln["text"] for ln in lines(word("ab", 10) + word("cd", 10, base=80))] == ["ab", "cd"]


def test_a_small_raised_digit_is_a_superscript() -> None:
    out = lines(word("cm", 10) + [ch("2", 20, base=103, height=4)])
    assert out[0]["text"] == "cm²"


def test_a_line_carries_cap_height_size_and_main_font() -> None:
    out = lines(word("AB", 10, height=8) + word("cd", 25, font="Times-Bold"))
    assert out[0]["h"] == 8 and out[0]["size"] == 11.0
    assert out[0]["font"] == "Times-Roman" and len(out[0]["runs"]) == 2


def test_an_ff_ligature_code_is_expanded() -> None:
    out = lines(word("e", 10) + [ch("\x0b", 15)] + word("ort", 20))
    assert out[0]["text"] == "effort"


def test_text_set_at_a_right_angle_reads_as_one_line() -> None:
    up = [
        ("S", "Times-Roman", 50, 57, y, y + 5, 0, 11.0, -math.pi / 2, 50) for y in (100, 106, 112)
    ]
    out = _vertical([(*c[:4], c[4], c[5], c[6], c[7], c[8], 50) for c in up])
    assert len(out) == 1 and out[0]["vertical"] and out[0]["text"] == "SSS"


def test_page_lines_on_a_generated_page(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from tests.fixtures.layout_book import PARAGRAPH, make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    page = doc[2]
    texts = [ln["text"] for ln in page_lines(page, page.get_textpage())]
    assert PARAGRAPH[0] in texts and PARAGRAPH[1] in texts
    head = next(ln for ln in page_lines(page, page.get_textpage()) if ln["text"] == "INTRODUCTION")
    assert head["font"].startswith("Helvetica") and head["h"] > 8


def test_text_set_sideways_on_a_generated_page_reads_as_one_upward_line(tmp_path) -> None:
    import pytest

    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page
    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    (side,) = [ln for ln in read_page(doc, 3)["lines"] if ln.get("vertical")]
    assert side["text"] == "PLATE 1-2. A picture set sideways." and side["up"] is True
    assert side["y1"] - side["y0"] > 100 > side["x1"] - side["x0"]  # it runs up the page


def _chars(text: str, x: float = 10.0, *, step: float = 5.0) -> list[tuple]:
    """Characters set one after another from `x`; a break mark takes no room."""
    out = []
    for c in text:
        width = 0.0 if c in "\x00\x02" else step
        out.append((c, "Times-Roman", x, x + width, 100.0, 107.0, 100.0, 11.0, 0.0, x))
        x += width
    return out


def test_a_word_break_mark_is_a_space_and_a_hyphen_mark_flags_the_line() -> None:
    from pagespeak.backends._layout_lines import _finish, _group

    (broken,) = [_finish(ln) for ln in _group(_chars("ab\x00cd"))]
    assert broken["text"] == "ab cd" and broken["soft_hyphen"] is False
    (hyphened,) = [_finish(ln) for ln in _group(_chars("struc\x02"))]
    assert hyphened["text"] == "struc" and hyphened["soft_hyphen"] is True


def test_the_two_letters_of_a_ligature_drawn_in_one_box_stay_in_their_word() -> None:
    from pagespeak.backends._layout_lines import _finish, _group

    chars = _chars("of") + [("f", "Times-Roman", 15.0, 20.0, 100.0, 107.0, 100.0, 11.0, 0.0, 15.0)]
    chars += _chars("ice", 20.0)
    (word,) = [_finish(ln) for ln in _group(chars)]
    assert word["text"] == "office"


def test_the_whole_text_layer_is_read_whatever_the_crop_box(tmp_path) -> None:
    import pytest

    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page

    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Times", "", 11)
    pdf.text(150, 60, "Above the box.")
    pdf.text(380, 200, "Mostly outside, this line runs far past the edge.")
    pdf.text(150, 300, "Inside the box, every word of this line shows on the page.")
    pdf.text(470, 350, "Wholly to the right.")
    pdf.text(20, 400, "To the left.")
    pdf.text(150, 760, "Below the box.")
    with pdf.rotation(90, x=560, y=600):
        pdf.text(560, 600, "Sideways, outside.")
    pdf.output(str(tmp_path / "a.pdf"))
    doc = pdfium.PdfDocument(str(tmp_path / "a.pdf"))
    doc[0].set_cropbox(100, 100, 450, 700)  # every line above but one lies partly or wholly outside
    doc.save(str(tmp_path / "b.pdf"))
    lines = read_page(pdfium.PdfDocument(str(tmp_path / "b.pdf")), 0)["lines"]
    assert [ln["text"] for ln in lines] == [
        "Above the box.",
        "Mostly outside, this line runs far past the edge.",
        "Inside the box, every word of this line shows on the page.",
        "Wholly to the right.",
        "To the left.",
        "Below the box.",
        "Sideways, outside.",
    ]
    assert lines[-1]["vertical"] is True
