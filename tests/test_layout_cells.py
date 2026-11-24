"""Tests for backends._layout_cells."""

from __future__ import annotations

from pagespeak.backends._layout_cells import cell_items, header_text, rotate
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line

PROF = profile_from_mapping(profile_mapping())


def texts(lines, pitch=None):
    return [t for t, _ in cell_items(lines, PROF, pitch)]


def test_wrapped_lines_join_and_bullets_start_items() -> None:
    lines = [
        line("• first item that", 80, 500),
        line("wraps on", 88, 489),
        line("• second", 80, 478),
    ]
    assert texts(lines) == ["• first item that wraps on", "• second"]


def test_a_line_a_step_below_the_table_pitch_starts_an_item() -> None:
    lines = [line("ulna", 80, 500), line("radius", 80, 484)]
    assert texts(lines, pitch=11) == ["ulna", "radius"] and texts(lines) == ["ulna radius"]


def test_a_bare_bullet_is_a_blank_to_fill_and_a_pipe_is_escaped() -> None:
    assert texts([line("•", 80, 500)]) == ["• ____"]
    assert texts([line("a | b", 80, 500)]) == ["a \\| b"]


def test_header_text_sets_reference_lines_in_parentheses() -> None:
    assert (
        header_text([line("BONES", 80, 500), line("PLATE 4", 80, 489)], PROF) == "BONES (PLATE 4)"
    )


def test_a_sideways_table_turns_so_its_rows_read_with_the_text() -> None:
    t = {
        "cells": [[0, 0, 10, 10, 0, 0, 0, 0], [0, 10, 10, 20, 1, 1, 0, 0]],
        "rows": 2,
        "cols": 1,
        "held": [
            [line("A", 0, 0, vertical=True, up=True)],
            [line("B", 0, 10, vertical=True, up=True)],
        ],
    }
    turned = rotate(t)
    assert (turned["rows"], turned["cols"]) == (1, 2)
    assert [c[4:] for c in turned["cells"]] == [[0, 0, 1, 1], [0, 0, 0, 0]]


def test_a_fill_in_line_set_a_step_down_stays_with_the_line_above_it() -> None:
    blank = [line("humerus", 80, 500), line("______", 80, 484)]
    assert texts(blank, pitch=11) == ["humerus ______"]
    drawn = [line("humerus", 80, 500), line("x", 80, 484, drawn=True)]
    assert texts(drawn, pitch=11) == ["humerus x"]


def test_a_table_read_top_to_bottom_turns_the_other_way() -> None:
    t = {
        "cells": [[0, 0, 10, 10, 0, 0, 0, 0], [10, 0, 20, 10, 0, 0, 1, 1]],
        "rows": 1,
        "cols": 2,
        "held": [
            [line("A", 0, 0, vertical=True, up=False)],
            [line("B", 10, 0, vertical=True, up=False)],
        ],
    }
    turned = rotate(t)
    assert (turned["rows"], turned["cols"]) == (2, 1)
    assert [c[4:] for c in turned["cells"]] == [[1, 1, 0, 0], [0, 0, 0, 0]]


def test_sideways_lines_in_a_cell_read_in_the_order_they_are_set() -> None:
    up = [
        line("second", 20, 0, vertical=True, up=True),
        line("first", 10, 0, vertical=True, up=True),
    ]
    assert texts(up) == ["first second"]
    down = [dict(ln, up=False) for ln in up]
    assert texts(down) == ["second first"]


def test_one_sideways_line_does_not_turn_a_cell_of_level_lines() -> None:
    lines = [
        line("first", 80, 500),
        line("second", 80, 489),
        line("side", 60, 495, vertical=True, up=True),
    ]
    assert texts(lines) == ["first side second"]  # read down the cell, not left to right


def test_a_bold_or_italic_label_starts_an_item_and_a_plain_one_runs_on() -> None:
    labelled = line("Origin: scapula", 80, 489)
    labelled["runs"] = [["Times-Bold", "Origin:"], ["Times-Roman", " scapula"]]
    assert texts([line("deltoid", 80, 500), labelled]) == ["deltoid", "Origin: scapula"]
    assert texts([line("deltoid", 80, 500), line("Origin: scapula", 80, 489)]) == [
        "deltoid Origin: scapula"
    ]


def test_a_mark_and_its_text_set_apart_on_one_line_are_one_item() -> None:
    assert texts([line("•", 80, 500, x1=84), line("atlas", 95, 500)]) == ["• atlas"]
    assert texts([line("2.", 80, 500, x1=88), line("axis", 95, 500)]) == ["2. axis"]
    assert texts([line("2.", 80, 500, x1=88)]) == ["2. ____"]


def test_an_art_credit_in_a_cell_is_left_out() -> None:
    assert texts([line("deltoid", 80, 500), line("Photo: A. Reader", 80, 489)]) == ["deltoid"]
