"""Tests for services._pdf_lines — the PDF's own text lines, read independently of any build."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._pdf_lines import read_outline, read_pages
from tests.fixtures.pdf_pages import PAGE_HEIGHT, Page, body_lines, make_pdf, raw_pdf, text_at

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")


def test_lines_come_back_with_their_page_and_position(tmp_path: Path) -> None:
    pdf = make_pdf(
        tmp_path / "a.pdf",
        [Page(lines=body_lines(["The tower has four floors.", "Light leaves the upper lamp."]))],
    )
    page = read_pages(pdf, [1])[1]
    assert page.box == (0, 0, 612, PAGE_HEIGHT)
    (first, second) = page.lines
    assert first.text == "The tower has four floors."
    assert first.page == 1
    assert first.box[1] < PAGE_HEIGHT - 100 < first.box[3]  # baseline 100pt from the top
    assert second.box[3] < first.box[1]
    assert round(first.size) == 10


def test_type_set_at_size_one_and_scaled_reads_at_its_printed_size(tmp_path: Path) -> None:
    content = b"BT /F1 1 Tf 10 0 0 10 72 650 Tm (Scaled to ten points) Tj ET\n"
    (line,) = read_pages(raw_pdf(tmp_path / "a.pdf", content), [1])[1].lines
    assert round(line.size, 3) == 10.0


def test_columns_on_one_baseline_are_separate_lines(tmp_path: Path) -> None:
    page = Page(lines=[(72, 100, 10, "Left column text"), (320, 100, 10, "Right column text")])
    lines = read_pages(make_pdf(tmp_path / "a.pdf", [page]), [1])[1].lines
    assert [ln.text for ln in lines] == ["Left column text", "Right column text"]


def test_a_hyphen_at_the_end_of_a_line_is_marked_and_kept(tmp_path: Path) -> None:
    page = Page(lines=body_lines(["The breakwater is a bar-", "rier that shields the boats."]))
    first, second = read_pages(make_pdf(tmp_path / "a.pdf", [page]), [1])[1].lines
    assert first.hyphenated and not second.hyphenated
    assert first.text == "The breakwater is a bar-"


def test_lines_outside_the_crop_box_are_not_read(tmp_path: Path) -> None:
    content = text_at(150, 600, "Inside the crop box") + text_at(20, 400, "Outside crop slug text")
    page = read_pages(raw_pdf(tmp_path / "a.pdf", content, crop="100 100 512 692"), [1])[1]
    assert page.box == (100, 100, 512, 692)
    assert [ln.text for ln in page.lines] == ["Inside the crop box"]


def test_a_turned_page_says_how_far(tmp_path: Path) -> None:
    pdf = raw_pdf(tmp_path / "a.pdf", text_at(72, 700, "A line on a turned page"), rotate=90)
    assert read_pages(pdf, [1])[1].rotation == 90


def test_only_the_asked_pages_are_read(tmp_path: Path) -> None:
    pdf = make_pdf(
        tmp_path / "a.pdf", [Page(lines=body_lines([f"Page {n} text"])) for n in (1, 2, 3)]
    )
    assert sorted(read_pages(pdf, [1, 3])) == [1, 3]


def test_sideways_text_is_left_out(tmp_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    pdf.text(72, 100, "Upright line")
    with pdf.rotation(90, 300, 400):
        pdf.text(300, 400, "Sideways label")
    path = tmp_path / "a.pdf"
    pdf.output(str(path))
    assert [ln.text for ln in read_pages(path, [1])[1].lines] == ["Upright line"]


def test_the_outline_reads_with_levels_and_pages(tmp_path: Path) -> None:
    pages = [Page(bookmark=(0, "Chapter 1 Towers")), Page(bookmark=(1, "1.1 Lamps"))]
    outline = read_outline(make_pdf(tmp_path / "a.pdf", pages))
    assert [(e.level, e.title, e.page) for e in outline] == [
        (0, "Chapter 1 Towers", 1),
        (1, "1.1 Lamps", 2),
    ]


class _FakeRaw:
    """pdfium's text calls over (char, x, baseline[, size]) in drawing order —
    for shapes fpdf cannot draw. Each glyph advances 5pt. Out-parameters arrive
    as `ctypes.byref()` objects, which the type stubs do not let through to `._obj`."""

    def __init__(
        self, chars: list[tuple[str, float, float]] | list[tuple[str, float, float, float]]
    ) -> None:
        self.chars = [(c[0], c[1], c[2], c[3] if len(c) > 3 else 10.0) for c in chars]

    def FPDFText_CountChars(self, tp: object) -> int:  # noqa: N802 — pdfium's names
        return len(self.chars)

    def FPDFText_GetUnicode(self, tp: object, i: int) -> int:  # noqa: N802
        return ord(self.chars[i][0])

    def FPDFText_GetCharAngle(self, tp: object, i: int) -> float:  # noqa: N802
        return 0.0

    def FPDFText_HasUnicodeMapError(self, tp: object, i: int) -> int:  # noqa: N802
        return int(self.chars[i][0] == "\x1f")  # stands in for an unmapped glyph

    def FPDFText_GetCharOrigin(self, tp: object, i: int, x: object, y: object) -> None:  # noqa: N802
        x._obj.value, y._obj.value = self.chars[i][1], self.chars[i][2]  # type: ignore[attr-defined]

    def FPDFText_GetCharBox(
        self, tp: object, i: int, left: object, right: object, bottom: object, top: object
    ) -> None:  # noqa: N802
        _, x, base, size = self.chars[i]
        left._obj.value, right._obj.value = x, x + 5  # type: ignore[attr-defined]
        bottom._obj.value, top._obj.value = base, base + 0.7 * size  # type: ignore[attr-defined]

    def FPDFText_GetLooseCharBox(self, tp: object, i: int, rect: object) -> None:  # noqa: N802
        _, x, base, size = self.chars[i]
        rect._obj.left, rect._obj.right = x, x + 5  # type: ignore[attr-defined]
        rect._obj.bottom, rect._obj.top = base - 0.2 * size, base + 0.8 * size  # type: ignore[attr-defined]

    def FPDFText_GetFontInfo(
        self, tp: object, i: int, buf: object, size: int, flags: object
    ) -> int:  # noqa: N802
        return 0

    def FPDFText_GetFontSize(self, tp: object, i: int) -> float:  # noqa: N802
        return self.chars[i][3]

    def FPDFText_GetMatrix(self, tp: object, i: int, matrix: object) -> int:  # noqa: N802
        matrix._obj.a = matrix._obj.d = 1.0  # type: ignore[attr-defined]
        return 1

    def FS_RECTF(self) -> object:  # noqa: N802
        import pypdfium2.raw as raw

        return raw.FS_RECTF()

    def FS_MATRIX(self) -> object:  # noqa: N802
        import pypdfium2.raw as raw

        return raw.FS_MATRIX()


def test_both_halves_of_an_ff_ligature_are_kept() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    word = [
        ("e", 10.0, 100.0),
        ("f", 15.0, 100.0),
        ("f", 15.0, 100.0),
        ("o", 20.0, 100.0),
        ("r", 25.0, 100.0),
    ]
    (line,) = _page_lines(_FakeRaw(word), None, 1)
    assert line.text == "effor"


def test_a_word_struck_twice_a_fraction_apart_reads_once() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    word = [("a", 10.0, 100.0), ("b", 15.0, 100.0), ("a", 10.3, 100.0), ("b", 15.3, 100.0)]
    (line,) = _page_lines(_FakeRaw(word), None, 1)
    assert line.text == "ab"


def test_a_glyph_with_no_unicode_is_marked() -> None:
    from pagespeak.services._pdf_lines import UNMAPPED, _page_lines

    word = [("d", 10.0, 100.0), ("i", 15.0, 100.0), ("\x1f", 20.0, 100.0), ("e", 25.0, 100.0)]
    (line,) = _page_lines(_FakeRaw(word), None, 1)
    assert line.text == f"di{UNMAPPED}e"


def test_stand_in_letters_read_as_their_symbols() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    word = [("A", 10.0, 100.0), ("S", 16.0, 100.0), ("B", 22.0, 100.0)]
    (line,) = _page_lines(_FakeRaw(word), None, 1, {"": {"S": "→"}})
    assert line.text == "A→B"


def test_a_superscript_drawn_out_of_order_stays_in_its_line() -> None:
    """Some PDFs draw a raised `+` and the words after it in a separate run."""
    from pagespeak.services._pdf_lines import _page_lines

    def word(
        text: str, x: float, base: float = 100.0, size: float = 10.0
    ) -> list[tuple[str, float, float, float]]:
        return [(ch, x + 5 * k, base, size) for k, ch in enumerate(text)]

    drawn = (
        word("rays(L", 10) + word("beacons)", 73) + word("+", 40, 103.0, 6.0) + word(",also", 45)
    )
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "rays(L+,also beacons)"


def test_text_printed_over_other_text_stays_its_own_line() -> None:
    """A watermark drawn across a label on the same baseline must not interleave with it."""
    from pagespeak.services._pdf_lines import _page_lines

    label = [(ch, 100.0 + 5 * k, 100.0, 10.0) for k, ch in enumerate("lantern")]
    mark = [(ch, 80.0 + 5 * k, 100.4, 10.0) for k, ch in enumerate("SAMPLECOPYONLY")]
    texts = sorted(line.text for line in _page_lines(_FakeRaw(label + mark), None, 1))
    assert texts == ["SAMPLECOPYONLY", "lantern"]


def test_a_tightly_set_line_keeps_its_word_spaces() -> None:
    """When justification squeezes a word gap below what geometry shows, the stream's space still counts."""
    from pagespeak.services._pdf_lines import _page_lines

    drawn = [
        ("a", 10.0, 100.0),
        ("b", 15.0, 100.0),
        (" ", 20.0, 100.0),
        ("c", 20.5, 100.0),
        ("d", 25.5, 100.0),
    ]
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "ab cd"


def test_a_big_heading_in_the_next_column_is_its_own_line() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    body = [(ch, 100.0 + 5 * k, 100.0, 10.0) for k, ch in enumerate("bodytext")]
    heading = [(ch, 152.0 + 5 * k, 100.0, 16.0) for k, ch in enumerate("Heading")]
    texts = [line.text for line in _page_lines(_FakeRaw(body + heading), None, 1)]
    assert texts == ["bodytext", "Heading"]


def test_a_subscript_between_words_does_not_split_the_line() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    drawn = [
        ("o", 10.0, 100.0),
        ("f", 15.0, 100.0),
        ("H", 24.0, 100.0),
        ("2", 29.0, 98.0, 6.5),
        ("i", 37.0, 100.0),
        ("s", 42.0, 100.0),
    ]
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "of H2 is"


def test_a_word_with_a_script_stays_on_its_line() -> None:
    """`X` with a raised `+` set at the start of a line belongs to that line, not between lines."""
    from pagespeak.services._pdf_lines import _page_lines

    drawn = [
        ("X", 10.0, 100.0),
        ("+", 15.0, 103.6, 6.0),
        ("r", 22.0, 100.0),
        ("a", 27.0, 100.0),
        ("y", 32.0, 100.0),
    ]
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "X+ ray"
    assert line.base == 100.0


def test_table_cells_on_one_baseline_are_marked_as_cells() -> None:
    """A gap far wider than the line's own word spaces parts two cells, though it is narrower than a column gutter."""
    from pagespeak.services._pdf_lines import _page_lines

    def word(text: str, x: float) -> list[tuple[str, float, float]]:
        return [(ch, x + 5 * k, 100.0) for k, ch in enumerate(text)]

    drawn = word("front", 10) + word("door", 37.5) + word("garden", 65) + word("shed", 97.5)
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "front door garden shed"
    assert line.cells == ("front door", "garden shed")


def test_an_accent_set_as_its_own_glyph_is_dropped() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    word = [("e", 10.0, 100.0), ("́", 10.5, 100.0), ("t", 15.0, 100.0)]
    (line,) = _page_lines(_FakeRaw(word), None, 1)
    assert line.text == "et"


def test_a_gap_under_half_an_em_parts_no_cells() -> None:
    """Wide against the line's tiny word spaces, but narrower than half the type size."""
    from pagespeak.services._pdf_lines import _page_lines

    starts = {
        "a": 10.0,
        "b": 15.0,
        "c": 21.9,
        "d": 26.9,
        "e": 33.8,
        "f": 38.8,
        "g": 48.7,
        "h": 53.7,
    }
    (line,) = _page_lines(_FakeRaw([(ch, x, 100.0) for ch, x in starts.items()]), None, 1)
    assert line.text == "ab cd ef gh" and line.cells == ()


def test_a_long_small_run_off_the_baseline_is_not_a_script() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    body = [(ch, 10.0 + 5 * k, 100.0) for k, ch in enumerate("word")]
    raised = [(ch, 32.0 + 5 * k, 103.0, 6.0) for k, ch in enumerate("abcdefg")]
    texts = sorted(line.text for line in _page_lines(_FakeRaw(body + raised), None, 1))
    assert texts == ["abcdefg", "word"]


def test_an_evenly_spaced_line_has_no_cells() -> None:
    from pagespeak.services._pdf_lines import _page_lines

    drawn = [(ch, 10.0 + 7.5 * k, 100.0) for k, ch in enumerate("abcd")]
    (line,) = _page_lines(_FakeRaw(drawn), None, 1)
    assert line.text == "a b c d" and line.cells == ()
