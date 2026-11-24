"""Tests for backends._layout_figure_text."""

from __future__ import annotations

from pagespeak.backends._layout_figure_text import join_keys, label_text
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line

PROF = profile_from_mapping(profile_mapping())


def test_a_key_letter_and_its_subscript_join_the_name_beside_it() -> None:
    out = join_keys(
        [line("a", 100, 400, x1=104), line("2", 104.5, 398, x1=107), line("aorta", 110, 400)]
    )
    assert [ln["text"] for ln in out] == ["a₂ aorta"]


def test_labels_read_in_rows_then_numbers_in_order() -> None:
    lines = [
        line("12.", 100, 300),
        line("femur", 100, 400),
        line("3.", 140, 300),
        line("tibia", 160, 400),
    ]
    assert label_text(lines, PROF) == ["femur", "tibia", "3.", "12."]


def test_a_number_set_apart_from_its_name_joins_it() -> None:
    assert label_text([line("4.", 100, 300, x1=108), line("ulna", 112, 300)], PROF) == ["4. ulna"]


def test_a_label_on_two_lines_is_one_label() -> None:
    lines = [line("long", 100, 400, font="Helvetica"), line("name", 100, 390, font="Helvetica")]
    assert label_text(lines, PROF) == ["long name"]


def test_marks_on_the_art_are_not_labels() -> None:
    assert label_text([line("a b", 100, 400), line("**", 150, 400)], PROF) == []


def test_a_credit_line_among_the_labels_is_left_out() -> None:
    from pagespeak.backends._layout_figure_text import label_text
    from pagespeak.backends._layout_profile import profile_from_mapping
    from tests.fixtures.layout_book import profile_mapping
    from tests.fixtures.layout_lines import line

    prof = profile_from_mapping(profile_mapping())
    labels = [line("femur", 100, 400), line("Photo: A. Reader", 100, 300)]
    assert label_text(labels, prof) == ["femur"]
