"""Tests for services._verify_lines — every PDF line arrives, and consecutive lines stay joined."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pagespeak.services._pdf_lines import PdfLine, PdfPage
from pagespeak.services._source_map import LeftOut, MapPicture, SourceMap
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_lines import _inner, check_line_coverage, check_line_joins

BODY = [
    "The lighthouse is a tall tower that guides passing ships",
    "through the narrow channels of the harbour by a rotating beam",
    "and a horn. On rocky coasts the lighthouse stands at the end",
    "of the long pier, between the two breakwaters, beside",
    "the old quay, and its lamp is ringed by three distinct lenses.",
]


def _page(texts: list[str], number: int = 1, *, top: float = 700.0, x: float = 72.0) -> PdfPage:
    lines = []
    for i, text in enumerate(texts):
        base = top - 12 * i
        hyphen = text.endswith("-")
        lines.append(
            PdfLine(number, text, (x, base - 2, 400.0, base + 8), 10.0, "Body", hyphen, base)
        )
    return PdfPage(number, (0.0, 0.0, 612.0, 792.0), lines)


def _map(**kw: object) -> SourceMap:
    fields: dict[str, object] = {
        "pdf": Path("book.pdf"),
        "sha256": None,
        "pages": ((1, 1),),
        "body": (50.0, 750.0),
        "pictures": (),
        "left_out": (),
        "left_out_text": (),
    }
    fields.update(kw)
    return SourceMap(**fields)  # type: ignore[arg-type]  # test-built from a dict


def _doc(tmp_path: Path, master: str) -> VerifyDoc:
    (tmp_path / "book.md").write_text(master, encoding="utf-8")
    return VerifyDoc(tmp_path, tmp_path / "book.md")


def test_every_line_present_passes(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Lighthouse\n\n" + " ".join(BODY) + "\n")
    assert check_line_coverage(doc, {1: _page(BODY)}, _map()).findings == ()


def test_a_lost_line_is_named_with_its_page(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Lighthouse\n\n" + " ".join(BODY[:2] + BODY[3:]) + "\n")
    (finding,) = check_line_coverage(doc, {1: _page(BODY)}, _map()).findings
    assert finding.where == "PDF p1"
    assert "and a horn. On rocky coasts" in finding.message
    assert finding.blocking


def test_text_set_upright_on_a_turned_page_is_noted_as_unchecked(tmp_path: Path) -> None:
    page = _page(BODY)
    turned = PdfPage(1, page.box, page.lines, ((300.0, 100.0, 312.0, 400.0),), 90)
    doc = _doc(tmp_path, "# Lighthouse\n\n" + " ".join(BODY) + "\n")
    findings = check_line_coverage(doc, {1: turned}, _map()).findings
    assert [(f.key, f.blocking) for f in findings] == [("line_coverage:turned:p1", False)]


def test_a_page_that_shows_nothing_is_noted_as_unchecked(tmp_path: Path) -> None:
    blank = PdfPage(1, (0.0, 0.0, 0.0, 0.0), [])
    findings = check_line_coverage(_doc(tmp_path, "# Lighthouse\n"), {1: blank}, _map()).findings
    assert [(f.key, f.blocking) for f in findings] == [("line_coverage:blank:p1", False)]


def test_a_line_printed_twice_needs_two_copies_in_the_output(tmp_path: Path) -> None:
    repeated = "Press the OK button to save the changes and return to the menu."
    filler = [f"Filler row holds the words alpha{w} beta{w} gamma{w} delta{w}" for w in range(40)]
    pages = {1: _page([repeated, *BODY]), 2: _page(filler, 2), 3: _page([repeated], 3)}
    master = repeated + " " + " ".join(BODY + filler) + "\n"
    (finding,) = check_line_coverage(_doc(tmp_path, master), pages, _map(pages=((1, 3),))).findings
    assert finding.where == "PDF p3"


def test_a_title_repeated_over_the_next_page_shares_one_copy(tmp_path: Path) -> None:
    title = "TABLE 9. Stones the keepers laid in the tower wall, ten in all"
    pages = {1: _page([title, *BODY[:3]]), 2: _page([title, *BODY[3:]], 2)}
    master = f"### {title}\n\n" + " ".join(BODY) + "\n"
    smap = _map(pages=((1, 2),))
    assert check_line_coverage(_doc(tmp_path, master), pages, smap).findings == ()


def test_a_line_sharing_words_with_another_still_finds_its_own_copy(tmp_path: Path) -> None:
    cell = "beams between the lamp and the outer lens"
    body = "of beams between the lamp and the outer lens. Each ring of the frame"
    pages = {1: _page([cell, body])}
    master = f"| Prism | {cell} |\n\nThe keeper sets the passage {body} holds glass.\n"
    assert check_line_coverage(_doc(tmp_path, master), pages, _map()).findings == ()


def test_words_lost_around_a_sentence_end_lose_both_lines(tmp_path: Path) -> None:
    lines = [
        "Early in the spring of that year the keepers met in the old lamp room",
        "to discuss the terms of a contract that had been drafted over the winter by",
        "the two harbour boards, and after a long debate they signed it at midnight.",
        "The next morning the news spread quickly along the quay and far beyond.",
        "Fishermen who had waited for months loaded their boats before the dawn.",
    ]
    master = (
        " ".join(lines[:2])
        + " the two harbour boards, and after a long debate they\n\n"
        + "spread quickly along the quay and far beyond. "
        + lines[4]
        + "\n"
    )
    findings = check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings
    assert [f.message for f in findings] == [
        f"PDF line not in the output: {lines[2]}",
        f"PDF line not in the output: {lines[3]}",
    ]


@pytest.mark.parametrize("lost_first", [False, True])
def test_a_line_one_word_off_another_does_not_take_its_copy(
    tmp_path: Path, lost_first: bool
) -> None:
    left = "Turn the brass dial to the left until the lamp catches and burns"
    right = "Turn the brass dial to the right until the lamp catches and burns"
    lines = [BODY[0], right, left, BODY[1]] if lost_first else [BODY[0], left, right, BODY[1]]
    master = " ".join([BODY[0], left, BODY[1]]) + "\n"
    findings = check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings
    assert [f.message for f in findings] == [f"PDF line not in the output: {right}"]


def test_a_lost_line_is_not_placed_on_a_like_sentence_far_away(tmp_path: Path) -> None:
    lost = "At night the keeper climbs down the long stair to the quay"
    filler = " ".join(
        f"Rows hold the words alpha{w} beta{w} gamma{w} delta{w}." for w in range(300)
    )
    master = f"{BODY[0]} {BODY[1]}\n\n{filler}\n\n{lost.replace('quay', 'boat')}\n"
    pages = {1: _page([BODY[0], lost, BODY[1]])}
    findings = check_line_coverage(_doc(tmp_path, master), pages, _map()).findings
    assert [f.message for f in findings] == [f"PDF line not in the output: {lost}"]


@pytest.mark.parametrize("cut", [slice(2, None), slice(1, -1)], ids=["first_two", "first_and_last"])
def test_a_line_that_lost_two_words_at_its_ends_is_lost(tmp_path: Path, cut: slice) -> None:
    line = "Dawn came slowly as the keeper climbs down the long stair to the quay"
    master = f"{BODY[0]} {' '.join(line.split()[cut])} {BODY[1]}\n"
    pages = {1: _page([BODY[0], line, BODY[1]])}
    findings = check_line_coverage(_doc(tmp_path, master), pages, _map()).findings
    assert [f.message for f in findings] == [f"PDF line not in the output: {line}"]


def test_a_line_after_a_hyphen_may_still_differ_by_one_word(tmp_path: Path) -> None:
    lines = [
        "Inside every tall lighthouse on the rocky coast the outer struc-",
        "ture of the lamp room is thin and bright, lettlng the beam pass outward.",
    ]
    master = (
        "Inside every tall lighthouse on the rocky coast the outer structure of the lamp "
        "room is thin and bright, letting the beam pass outward.\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_a_line_continuing_a_hyphen_split_word_is_found_past_a_line_between(
    tmp_path: Path,
) -> None:
    """The reader may put a label between a hyphenated line and the line that ends its word."""
    lines = [
        "Inside every tall lighthouse on the rocky coast the outer struc-",
        "Gallery",
        "ture of the lamp room is thin and bright, lettlng the beam pass outward.",
    ]
    master = (
        "Inside every tall lighthouse on the rocky coast the outer structure of the lamp "
        "room is thin and bright, letting the beam pass outward.\n\nGallery\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_a_label_set_before_the_end_of_a_split_word_is_not_required(tmp_path: Path) -> None:
    lines = [
        "Inside every tall lighthouse on the rocky coast the outer struc-",
        "Gallery ture of the lamp room is thin and bright, lettlng the beam pass outward.",
    ]
    master = (
        "Inside every tall lighthouse on the rocky coast the outer structure of the lamp "
        "room is thin and bright, letting the beam pass outward.\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_one_corrected_word_mid_line_does_not_lose_a_short_line(tmp_path: Path) -> None:
    lines = ["and the mill grinds lt into fine flour", *BODY]
    master = "and the mill grinds it into fine flour " + " ".join(BODY) + "\n"
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_text_inside_pictures_and_left_out_areas_is_not_required(tmp_path: Path) -> None:
    lines = [
        *BODY,
        "Label inside the drawing of the lamp room window",
        "Visit the online quiz bank today please now",
    ]
    page = _page(lines)
    picture_y = page.lines[5].base
    smap = _map(
        pictures=(MapPicture("p1.png", 1, (60.0, picture_y - 5, 500.0, picture_y + 10)),),
        left_out_text=((re.compile("^Visit"), "ads"),),
    )
    doc = _doc(tmp_path, "# Lighthouse\n\n" + " ".join(BODY) + "\n")
    assert check_line_coverage(doc, {1: page}, smap).findings == ()
    boxed = _map(
        left_out=(LeftOut(1, (0.0, 0.0, 612.0, picture_y + 10), "art"),),
        left_out_text=smap.left_out_text,
    )
    assert check_line_coverage(doc, {1: page}, boxed).findings == ()


def test_running_heads_outside_the_body_band_are_not_required(tmp_path: Path) -> None:
    page = _page(["CHAPTER ONE THE HARBOUR LIGHT AND ITS PARTS"], top=780.0)
    assert check_line_coverage(_doc(tmp_path, "# Lighthouse\n"), {1: page}, _map()).findings == ()


def test_a_word_hyphenated_across_lines_counts_as_joined(tmp_path: Path) -> None:
    # "iz" spoils the letters around the join, so only the hyphen rule can join it
    lines = [
        "The outermost layer of the tower wall iz the weather-",
        "board, a thin cladding of painted planks and timber",
    ]
    doc = _doc(
        tmp_path,
        "The outermost layer of the tower wall is the weatherboard, a thin cladding of painted planks and timber\n",
    )
    page = _page(lines)
    assert check_line_coverage(doc, {1: page}, _map()).findings == ()
    assert check_line_joins(doc, {1: page}, _map()).findings == ()
    assert _inner(lines[0], True)[-1] == "the"


def test_text_inserted_between_two_lines_of_a_sentence_blocks(tmp_path: Path) -> None:
    master = (
        "# Lighthouse\n\n"
        + " ".join(BODY[:2])
        + "\n\n> Figure 1.1 A lighthouse\n\n"
        + " ".join(BODY[2:])
        + "\n"
    )
    (finding,) = check_line_joins(_doc(tmp_path, master), {1: _page(BODY)}, _map()).findings
    assert finding.where == "PDF p1"
    assert "a rotating beam" in finding.message
    assert finding.blocking


def test_a_join_whose_words_recur_elsewhere_in_the_book_is_still_broken(tmp_path: Path) -> None:
    lines = [
        "Inside every lighthouse the outer structure of the",
        "lamp room is thin and bright, letting the beam pass outward.",
    ]
    master = (
        f"{lines[0]}\n\n> Figure 1.1 A lighthouse seen from the gallery\n\n{lines[1]}\n\n"
        "Later chapters return to the role of the lamp room.\n"
    )
    (finding,) = check_line_joins(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings
    assert "structure of the | lamp room" in finding.message


def test_a_hyphen_join_whose_words_recur_elsewhere_is_still_broken(tmp_path: Path) -> None:
    lines = [
        "Inside every tall lighthouse on the rocky coast the outer struc-",
        "ture of the lamp room is thin and bright, letting the beam pass outward.",
    ]
    master = (
        f"{lines[0]}\n\n> Figure 1.1 A lighthouse seen from the gallery\n\n{lines[1]}\n\n"
        "Later chapters return to an outer structure of the tower.\n"
    )
    (finding,) = check_line_joins(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings
    assert "outer struc- | ture of the lamp" in finding.message


def test_a_sentence_end_may_be_followed_by_a_float(tmp_path: Path) -> None:
    lines = [
        "The tower wall is made of three distinct layers of stone.",
        "Light leaves the lamp through two large lenses, the outer",
    ]
    master = (
        "The tower wall is made of three distinct layers of stone.\n\n"
        "> Figure 1.1 A lighthouse on the rocks\n\n"
        "Light leaves the lamp through two large lenses, the outer\n"
    )
    assert check_line_joins(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_a_line_spaced_differently_by_the_reader_still_counts(tmp_path: Path) -> None:
    lines = ["Tachometry (t a k-om e tr e; tachos = speed, metron = measure) is the", *BODY]
    master = (
        "# Lighthouse\n\nTachometry (tāk-omĕtrē; tachos = speed, metron = measure) is the "
        + " ".join(BODY)
        + "\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_one_word_the_reader_could_not_spell_does_not_lose_the_line(tmp_path: Path) -> None:
    lines = ["The gearbox holds the di�erential and its housing at the rear axle", *BODY]
    master = (
        "The gearbox holds the differential and its housing at the rear axle "
        + " ".join(BODY)
        + "\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_one_word_the_build_corrected_does_not_lose_the_line(tmp_path: Path) -> None:
    lines = ["parts in the main assembly line alone. lt typically is replaced early", *BODY]
    master = (
        "parts in the main assembly line alone. It typically is replaced early "
        + " ".join(BODY)
        + "\n"
    )
    assert check_line_coverage(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_a_printed_page_reference_is_not_required() -> None:
    assert _inner("Rate of Fluid Transport Through Pipes, p. 130", False) == [
        "rate",
        "of",
        "fluid",
        "transport",
        "through",
        "pipes",
    ]


def test_a_label_split_from_its_panel_letter_still_joins(tmp_path: Path) -> None:
    lines = [
        "the beam grows dim as fog rolls in. The fall is shown in Figure 7.2b, and",
        "the height of each bar gives the lamp's reach in sea miles at dusk",
    ]
    master = (
        "the beam grows dim as fog rolls in. The fall is shown in **Figure 7.2** b, and "
        "the height of each bar gives the lamp's reach in sea miles at dusk\n"
    )
    assert check_line_joins(_doc(tmp_path, master), {1: _page(lines)}, _map()).findings == ()


def test_a_line_that_is_two_table_cells_is_read_cell_by_cell(tmp_path: Path) -> None:
    """Each cell's first line sits on one baseline; the output keeps each cell's words together."""
    text = "front door key garden shed"
    cells = ("front door key", "garden shed")
    line = PdfLine(1, text, (72.0, 600.0, 500.0, 610.0), 10.0, "Body", False, 600.0, cells)
    master = tmp_path / "book.md"
    master.write_text("| front door key for the old brass lock | garden shed |\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, master)
    smap = SourceMap(tmp_path / "a.pdf", None, ((1, 1),), None, (), (), ())
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [line])
    assert check_line_coverage(doc, {1: page}, smap).findings == ()
    joined = PdfLine(1, text, (72.0, 600.0, 500.0, 610.0), 10.0, "Body", False, 600.0)
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [joined])
    assert len(check_line_coverage(doc, {1: page}, smap).findings) == 1


def test_a_table_row_of_short_cells_lost_whole_is_lost(tmp_path: Path) -> None:
    text = "Lamp oil two gallons every night"
    cells = ("Lamp oil", "two gallons", "every night")
    row = PdfLine(1, text, (72.0, 674.0, 400.0, 684.0), 10.0, "Body", False, 676.0, cells)
    body = _page(BODY[:2])
    page = PdfPage(1, body.box, [body.lines[0], row, body.lines[1]])
    findings = check_line_coverage(_doc(tmp_path, f"{BODY[0]} {BODY[1]}\n"), {1: page}, _map())
    assert [f.message for f in findings.findings] == [f"PDF line not in the output: {text}"]


def test_a_short_line_with_a_word_the_output_set_inline_is_found(tmp_path: Path) -> None:
    """A label printed over an arrow lands between the words in the output."""
    line = PdfLine(
        1,
        "red paint + blue paint → purple paint",
        (72.0, 600.0, 400.0, 610.0),
        10.0,
        "Body",
        False,
        600.0,
    )
    master = tmp_path / "book.md"
    master.write_text("red paint + blue paint → (MIX) purple paint\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, master)
    smap = SourceMap(tmp_path / "a.pdf", None, ((1, 1),), None, (), (), ())
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [line])
    assert check_line_coverage(doc, {1: page}, smap).findings == ()


def test_a_row_that_carries_on_past_a_badge_is_not_a_broken_join(tmp_path: Path) -> None:
    """The reader cuts a line at a step-number badge; the line below follows the row's end, not the cut."""

    def line(text: str, x0: float, x1: float, base: float) -> PdfLine:
        return PdfLine(1, text, (x0, base - 2, x1, base + 8), 10.0, "Body", False, base)

    first = line("so the old mill grinds the harvested grain into fine flour", 72.0, 400.0, 600.0)
    rest = line(", which can then", 420.0, 500.0, 600.0)
    second = line("be baked into bread or sold at the market by the farmers", 72.0, 500.0, 588.0)
    master = tmp_path / "book.md"
    master.write_text(
        "so the old mill grinds the harvested grain into fine flour , which can then "
        "be baked into bread or sold at the market by the farmers\n",
        encoding="utf-8",
    )
    doc = VerifyDoc(tmp_path, master)
    smap = SourceMap(tmp_path / "a.pdf", None, ((1, 1),), None, (), (), ())
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [first, rest, second])
    assert check_line_joins(doc, {1: page}, smap).findings == ()
