"""Tests for backends._layout_text."""

from __future__ import annotations

from pagespeak.backends._layout_profile import profile_from_mapping
from pagespeak.backends._layout_text import (
    Doc,
    clean,
    emit_text,
    heading_level,
    join,
    styled,
    text_lines,
)
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line

PROF = profile_from_mapping(profile_mapping())


def test_clean_drops_checkboxes_soft_hyphens_and_space_before_punctuation() -> None:
    assert clean("☐ a ,b ( c ) \xad", "☐") == "a,b (c)"


def test_styled_marks_bold_and_italic_runs() -> None:
    ln = line("x", 0, 0)
    ln["runs"] = [["Times-Bold", "bold "], ["Times-Italic", "italic"], ["Times-Roman", " plain"]]
    assert styled(ln, "☐") == "**bold** *italic* plain"


def test_join_runs_straight_on_after_a_soft_hyphen_or_dash() -> None:
    assert (
        join("struc", "ture", soft=True) == "structure"
        and join("a –", "b") == "a –b"
        and join("a", "b") == "a b"
    )


def test_heading_level_follows_the_profile_rules() -> None:
    assert heading_level(line("INTRODUCTION", 72, 600, font="Helvetica-Bold", h=10), PROF) == 2
    assert (
        heading_level(line("Introduction", 72, 600, font="Helvetica-Bold", h=10), PROF) is None
    )  # the rule needs capitals
    assert (
        heading_level(line("INTRODUCTION", 72, 600, font="Times-Bold", h=10), PROF) is None
    )  # not the heading face
    assert heading_level(line("SMALL", 72, 600, font="Helvetica", h=6), PROF) is None


def run(lines):
    d = Doc()
    attached, rest = text_lines([{"kind": "text", "line": ln} for ln in lines], PROF)
    for ln in sorted(rest, key=lambda ln: -ln["base"]):
        emit_text(d, ln, attached.get(id(ln)), 2, PROF)
    d.end_list()
    return "\n".join(d.out).strip()


def test_lines_a_step_apart_join_into_one_paragraph_and_a_gap_starts_another() -> None:
    lines = [line("One line,", 72, 600), line("its next.", 72, 586), line("New one.", 72, 540)]
    assert run(lines) == "One line, its next.\n\nNew one."


def test_list_marks_start_items_and_indents_nest_them() -> None:
    lines = [
        line("1.", 72, 600),
        line("First.", 90, 600),
        line("•", 89, 586),
        line("Sub.", 105, 586),
    ]
    assert run(lines) == "1. First.\n  - Sub."


def test_a_head_set_on_two_lines_is_one_heading() -> None:
    lines = [
        line("PLANT", 72, 600, font="Helvetica-Bold", h=10),
        line("CELLS", 72, 585, font="Helvetica-Bold", h=10),
    ]
    assert run(lines) == "## PLANT CELLS"


def _rules(*rules: dict) -> object:
    m = profile_mapping()
    m["fonts"]["headings"] = list(rules)
    return profile_from_mapping(m)


CAPS = {"level": 2, "caps": True, "min_cap": 9, "max_len": 20}
SLANT = {"level": 3, "font_suffix": "-Oblique", "min_cap": 8, "max_len": 30, "no_period": True}


def _head(text: str, font: str = "Helvetica-Bold", h: float = 10, **extra: object) -> dict:
    return line(text, 72, 600, font=font, h=h, **extra)


def test_each_check_of_a_heading_rule_can_refuse_a_line() -> None:
    prof = _rules(CAPS, SLANT)
    assert heading_level(_head("CELLS"), prof) == 2
    assert heading_level(_head("Cells"), prof) is None  # capitals wanted
    assert heading_level(_head("CELLS", h=8.9), prof) is None  # too short a cap height
    assert heading_level(_head("CELLS OF THE BODY AND"), prof) is None  # 21 characters: too long
    assert (
        heading_level(_head("CELLS OF THE BODY AN"), prof) is None
    )  # the limit itself is too long
    assert heading_level(_head("CELLS OF THE BODY A"), prof) == 2
    slant = "Helvetica-Oblique"
    assert heading_level(_head("Cells", slant, 8), prof) == 3
    assert heading_level(_head("Cells", slant, 7.9), prof) is None
    assert heading_level(_head("Cells.", slant), prof) is None  # a sentence, not a head
    assert heading_level(_head("Cells", "Helvetica"), prof) is None  # not the rule's face
    assert heading_level(_head("C" * 30, slant, 8), prof) is None and (
        heading_level(_head("c" * 29, slant, 8), prof) == 3
    )
    assert heading_level(_head("CELLS", vertical=True), prof) is None
    assert heading_level(_head("12.3"), prof) is None  # no letters


def test_the_first_heading_rule_that_matches_wins() -> None:
    both = _head("CELLS", "Helvetica-Oblique")
    assert heading_level(both, _rules(CAPS, SLANT)) == 2
    assert heading_level(both, _rules(SLANT, CAPS)) == 3
    falls_through = _head("CELLS", "Helvetica-Oblique", 8.5)  # too short for the capitals rule
    assert heading_level(falls_through, _rules(CAPS, SLANT)) == 3


def pages_of(*pages: tuple[float, list]) -> str:
    """Lines emitted page after page; each page gives its left margin and its lines."""
    d = Doc()
    for pg, (page_margin, lines) in enumerate(pages):
        d.margin = page_margin
        attached, rest = text_lines([{"kind": "text", "line": ln} for ln in lines], PROF)
        for ln in sorted(rest, key=lambda ln: -ln["base"]):
            emit_text(d, ln, attached.get(id(ln)), pg, PROF)
    d.end_list()
    return "\n".join(d.out).strip()


def test_an_item_runs_on_over_a_page_break_at_its_text_indent() -> None:
    first = (72, [line("1.", 72, 100), line("A step that starts here and", 90, 100)])
    # the facing page is set 8pt further in: the item's text indent is measured from its margin
    carried = (80, [line("ends on the next page.", 98, 700), line("A new paragraph.", 80, 660)])
    assert pages_of(first, carried) == (
        "1. A step that starts here and ends on the next page.\n\nA new paragraph."
    )


def test_a_line_at_the_margin_of_the_next_page_does_not_join_the_item_before_it() -> None:
    first = (72, [line("1.", 72, 100), line("A whole step.", 90, 100)])
    after = (72, [line("Text at the margin.", 72, 700)])
    out = [ln for ln in pages_of(first, after).splitlines() if ln]
    assert out == ["1. A whole step.", "Text at the margin."]


def test_an_item_takes_its_wrapped_line_and_ends_at_a_gap() -> None:
    lines = [
        line("1.", 72, 600),
        line("First line of the step", 90, 600),
        line("and its second.", 90, 588),
        line("A paragraph after the list.", 72, 550),
    ]
    assert run(lines) == "1. First line of the step and its second.\n\nA paragraph after the list."


def test_a_paragraph_takes_an_indented_first_line_and_not_a_line_set_far_in() -> None:
    para = [line("An indented first line", 82, 600), line("and its next.", 72, 586)]
    assert run(para) == "An indented first line and its next."
    apart = [line("A paragraph.", 72, 600), line("A line set far in.", 100, 586)]
    assert run(apart) == "A paragraph.\n\nA line set far in."


def test_a_checkbox_set_in_the_line_itself_starts_an_item() -> None:
    assert run([line("☐ a thing to find", 72, 600), line("☐ another", 72, 586)]) == (
        "- a thing to find\n- another"
    )
