"""Tests for services._verify_titles — printed figure and table titles against the output."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._pdf_lines import PdfLine, PdfPage
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_titles import check_printed_titles


def _pages(*per_page: list[str]) -> dict[int, PdfPage]:
    out = {}
    for number, texts in enumerate(per_page, 1):
        lines = [
            PdfLine(
                number,
                t,
                (72.0, 700.0 - 14 * i, 300.0, 710.0 - 14 * i),
                10.0,
                "Body",
                False,
                702.0 - 14 * i,
            )
            for i, t in enumerate(texts)
        ]
        out[number] = PdfPage(number, (0.0, 0.0, 612.0, 792.0), lines)
    return out


def _doc(tmp_path: Path, master: str) -> VerifyDoc:
    (tmp_path / "book.md").write_text(master, encoding="utf-8")
    return VerifyDoc(tmp_path, tmp_path / "book.md")


def _keys(doc: VerifyDoc, pages: dict[int, PdfPage]) -> list[str]:
    return [f.key for f in check_printed_titles(doc, pages, keep=lambda line: True).findings]


def test_titles_that_arrive_once_with_their_picture_pass(tmp_path: Path) -> None:
    pages = _pages(["Intro text.", "Figure 1.1 The tower"], ["Table 1.2 Lamps", "More text."])
    master = "# One\n\n![a tower](images/a.png)\n\n**Figure 1.1** The tower\n\n## Table 1.2 Lamps\n\n| A | B |\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_title_missing_from_the_output_blocks(tmp_path: Path) -> None:
    pages = _pages(["Figure 1.1 The tower"], ["Figure 2.1 The harbour"])
    master = (
        "![x](images/a.png)\n\nFigure 1.1 The tower\n\n![Figure 2.1 The harbour](images/b.png)\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:missing:Figure 2.1"]


def test_a_lost_caption_is_missing_though_the_text_mentions_its_figure(tmp_path: Path) -> None:
    pages = _pages(
        ["The harbour at night is shown in Figure 2.1 below.", "Figure 2.1 The harbour at night"]
    )
    master = "The harbour at night is shown in Figure 2.1 below.\n\n![x](images/a.png)\n"
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:missing:Figure 2.1"]


def test_a_caption_run_into_a_paragraph_still_arrives(tmp_path: Path) -> None:
    pages = _pages(["Figure 2.1 The harbour at night"])
    master = "![x](images/a.png)\n\nThe lights went out. Figure 2.1 The harbour at night\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_caption_whose_label_is_a_link_is_a_title(tmp_path: Path) -> None:
    pages = _pages(["Figure 3.2 The lamp room"])
    master = "![x](images/a.png)\n\n[Figure 3.2](#figure-3-2) The lamp room\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_prose_naming_a_short_title_does_not_bring_its_caption(tmp_path: Path) -> None:
    pages = _pages(["Table 3 Results"], ["Table 4 Stones"])
    master = "As Table 3 results show, the lamp burned all night. Its log is Table 4 Stones.\n"
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:missing:Table 3"]


def test_a_figure_caption_run_into_a_paragraph_needs_a_picture_near_it(tmp_path: Path) -> None:
    pages = _pages(["Figure 2.1 The harbour at night"])
    master = (
        "The lights went out. Figure 2.1 The harbour at night\n\n"
        + "Body line.\n\n" * 30
        + "![far away](images/a.png)\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:picture:Figure 2.1"]


def test_a_bare_figure_label_named_in_a_table_needs_no_picture(tmp_path: Path) -> None:
    pages = _pages(["FIGURE 7.1B"])
    assert _keys(_doc(tmp_path, "| prism lens | see FIGURE 7.1B |\n"), pages) == []


def test_a_label_printed_bare_arrives_wherever_the_output_names_it(tmp_path: Path) -> None:
    pages = _pages(["TABLE 7.1B"])
    master = "| prism lens | bends the beam | TABLE 7.1B |\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_title_set_off_by_a_spaced_dash_is_a_title(tmp_path: Path) -> None:
    pages = _pages(["Figure 1.1 – The tower"], ["Table 1.2 - Lamps"])
    assert _keys(_doc(tmp_path, "Nothing here.\n"), pages) == [
        "printed_titles:missing:Figure 1.1",
        "printed_titles:missing:Table 1.2",
    ]


def test_a_list_of_figures_with_spaced_leaders_holds_no_titles(tmp_path: Path) -> None:
    pages = _pages(["Figure 1.1 The tower . . . . . . . 12"])
    assert _keys(_doc(tmp_path, "Nothing here.\n"), pages) == []


def test_a_list_of_figures_in_the_output_does_not_bring_its_captions(tmp_path: Path) -> None:
    pages = _pages(
        ["Figure 3.2 The lamp room . . . . . . . 5", "Table 2.1 Stones of the tower . . . . 7"],
        ["Figure 3.2 The lamp room"],
        ["Table 2.1 Stones of the tower"],
    )
    master = (
        "# Figures\n\nFigure 3.2 The lamp room . . . . . . . 5\n\n"
        "# Tables\n\n| Table | Title | Page |\n|---|---|---|\n| Table 2.1 | Stones of the tower | 7 |\n\n"
        "# Chapter 3\n\nThe keeper climbs to the lamp.\n\n![x](images/a.png)\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == [
        "printed_titles:missing:Figure 3.2",
        "printed_titles:missing:Table 2.1",
    ]


def test_a_list_of_figures_set_as_a_table_is_not_a_second_copy(tmp_path: Path) -> None:
    pages = _pages(["Figure 3.2 The lamp room . . . . . . . 5"], ["Figure 3.2 The lamp room"])
    master = (
        "| Figure | Page |\n|---|---|\n| Figure 3.2 The lamp room | 5 |\n\n"
        + "Body line.\n\n" * 30
        + "![x](images/a.png)\n\nFigure 3.2 The lamp room\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_caption_ending_in_a_number_after_its_sentence_still_arrives(tmp_path: Path) -> None:
    pages = _pages(["Figure 5.1 The tower. Its lamp was lit in 1890."])
    master = "![x](images/a.png)\n\nFigure 5.1 The tower. Its lamp was lit in 1890.\n"
    assert _keys(_doc(tmp_path, master), pages) == []


@pytest.mark.parametrize(
    "title",
    ["Figure 2.7 The north light, 1827", "Table 4.1 Results for trial 3", "Figure 6 Stage 2"],
)
def test_a_caption_ending_in_a_bare_number_is_a_title(tmp_path: Path, title: str) -> None:
    pages = _pages([title])
    assert _keys(_doc(tmp_path, f"![x](images/a.png)\n\n{title}\n"), pages) == []


def test_a_list_of_figures_without_leaders_holds_no_titles_on_either_side(tmp_path: Path) -> None:
    pages = _pages(
        ["Figure 1.1 The tower 10", "Figure 2.1 The lamp 20"],
        [],
        ["Table 1.1 Stones of the wall 12"],
        [],
        ["Figure 1.1 The tower"],
        ["Table 1.1 Stones of the wall"],
        ["Figure 2.1 The lamp"],
    )
    master = (
        "# Figures\n\nFigure 1.1 The tower 10\n\nFigure 2.1 The lamp 20\n\n"
        "# Tables\n\nTable 1.1 Stones of the wall 12\n\n"
        + "Body line.\n\n"
        * 30
        + "# Chapter 1\n\n![a](images/a.png)\n\nFigure 1.1 The tower\n\n"
        "Table 1.1 Stones of the wall\n\n# Chapter 2\n\n![b](images/b.png)\n\nFigure 2.1 The lamp\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_list_of_figures_without_leaders_does_not_bring_its_captions(tmp_path: Path) -> None:
    pages = _pages(
        ["Figure 3.2 The lamp room . . . . 5", "Figure 3.3 The stair . . . . 6"],
        ["Figure 3.2 The lamp room"],
        ["Figure 3.3 The stair"],
    )
    master = (
        "# Figures\n\nFigure 3.2 The lamp room 5\n\nFigure 3.3 The stair 6\n\n"
        "# Chapter 3\n\n![x](images/a.png)\n"
    )
    assert _keys(_doc(tmp_path, master), pages) == [
        "printed_titles:missing:Figure 3.2",
        "printed_titles:missing:Figure 3.3",
    ]


def test_a_title_starting_more_lines_than_the_pdf_has_blocks(tmp_path: Path) -> None:
    pages = _pages(["Table 3.1 Stones"])
    master = "## Table 3.1 Stones\n\n| a |\n\nTable 3.1 Stones\n"
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:repeated:Table 3.1"]


def test_a_figure_caption_with_no_picture_near_it_blocks(tmp_path: Path) -> None:
    pages = _pages(["Figure 4.2 Vector art"])
    master = "Figure 4.2 Vector art\n\n" + "Body line.\n\n" * 30 + "![far away](images/a.png)\n"
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:picture:Figure 4.2"]


def test_a_title_far_from_its_page_blocks(tmp_path: Path) -> None:
    pages = _pages(
        ["Table 1.1 A"], ["Table 2.1 B"], ["Table 3.1 C"], ["Table 4.1 D"], ["Table 5.1 E"]
    )
    master = "Table 1.1 A\n\nTable 2.1 B\n\nTable 5.1 E\n\nTable 3.1 C\n\nTable 4.1 D\n"
    assert _keys(_doc(tmp_path, master), pages) == ["printed_titles:order:Table 5.1"]


def test_body_text_that_starts_with_a_reference_is_not_a_title(tmp_path: Path) -> None:
    pages = _pages(["Figure 1.1 shows the tower, and", "Figure 1.1, the tower, again"])
    assert _keys(_doc(tmp_path, "Nothing here.\n"), pages) == []


def test_lines_the_caller_rejects_are_ignored(tmp_path: Path) -> None:
    pages = _pages(["Figure 9.9 Running head"])
    doc = _doc(tmp_path, "Nothing here.\n")
    assert check_printed_titles(doc, pages, keep=lambda line: False).findings == ()


def test_references_wrapped_to_a_line_start_are_not_titles(tmp_path: Path) -> None:
    pages = _pages(
        ["figure 3.2b). Rotation occurs when", "Figure 4.1a–c, and its parts", "Figure 3.1) shows"]
    )
    assert _keys(_doc(tmp_path, "Nothing here.\n"), pages) == []


def test_a_title_about_something_continued_is_still_a_title(tmp_path: Path) -> None:
    pages = _pages(["Figure 3.1 Continued fractions of a root"])
    assert _keys(_doc(tmp_path, "Nothing here.\n"), pages) == ["printed_titles:missing:Figure 3.1"]


def test_a_continued_title_is_not_a_second_copy(tmp_path: Path) -> None:
    pages = _pages(["Table 4.3 Fastener Types"], ["Rows of the table."])
    master = "**Table 4.3 Fastener Types**\n\n| a |\n\n**Table 4.3 Fastener Types (continued)**\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_a_mermaid_transcription_stands_with_its_picture(tmp_path: Path) -> None:
    pages = _pages(["Figure 21.10 Signal flow"])
    mermaid = "```mermaid\n" + "  A --> B\n" * 30 + "```\n"
    master = f"![signals](images/a.png)\n\n{mermaid}\n**Figure 21.10** Signal flow\n"
    assert _keys(_doc(tmp_path, master), pages) == []


def test_without_a_source_map_a_bare_missing_label_is_a_note(tmp_path: Path) -> None:
    pages = _pages(["Figure 1", "Figure 2 Wiring diagram"])
    doc = _doc(tmp_path, "Nothing here.\n")
    findings = check_printed_titles(doc, pages, keep=lambda line: True, strict=False).findings
    assert [(f.key, f.blocking) for f in findings] == [
        ("printed_titles:missing:Figure 1", False),
        ("printed_titles:missing:Figure 2", True),
    ]
