"""Tests for backends._layout_table_md."""

from __future__ import annotations

from pagespeak.backends._layout_pictures import PageSource
from pagespeak.backends._layout_profile import profile_from_mapping
from pagespeak.backends._layout_table_md import render_table
from pagespeak.backends._layout_text import Doc
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import ruled, table

PROF = profile_from_mapping(profile_mapping())


def md(f) -> str:
    d = Doc()
    render_table(d, f, 2, PageSource(None, {}), PROF)
    return "\n".join(d.out).strip()


def test_a_table_with_a_header_is_a_pipe_table() -> None:
    out = md(table([["TERM", "MEANING"], ["cell", "life"]]))
    assert out == "| TERM | MEANING |\n|---|---|\n| cell | life |"


def test_a_titled_table_gets_its_title_as_a_heading() -> None:
    out = md(table([["NAME", "ROLE"], ["ulna", "forearm"]], title="CHART 2-1. Bones"))
    assert out.splitlines()[0] == "## CHART 2-1. Bones"


def test_a_column_of_terms_with_empty_answer_cells_is_a_list() -> None:
    out = md(table([["TERM", "NOTES"], ["cell", ""], ["tissue", ""]]))
    assert out == "*Columns:* TERM · NOTES\n\n- cell\n- tissue"


def test_a_grid_of_numbered_blanks_is_one_answer_line() -> None:
    assert md(table([["1.", "2."], ["3.", "4."]])) == "1. ______ 2. ______ 3. ______ 4. ______"


def pages(*floats, between: str | None = None) -> str:
    """The tables rendered one after another, as they come on following pages."""
    d = Doc()
    for i, f in enumerate(floats):
        if i and between:
            d.block([between])
        render_table(d, f, 2 + i, PageSource(None, {}), PROF)
    return "\n".join(d.out).strip()


BONES = table([["NAME", "ROLE"], ["ulna", "forearm"]], title="CHART 2-1. Bones")
MORE_BONES = table([["NAME", "ROLE"], ["tibia", "leg"]], title="CHART 2-1. Bones")


def test_a_titled_table_continued_on_the_next_page_is_one_table() -> None:
    assert pages(BONES, MORE_BONES) == (
        "## CHART 2-1. Bones\n\n| NAME | ROLE |\n|---|---|\n| ulna | forearm |\n| tibia | leg |"
    )


def test_text_between_the_parts_of_a_table_makes_the_second_part_a_table_of_its_own() -> None:
    part = "## CHART 2-1. Bones\n\n| NAME | ROLE |\n|---|---|\n"
    assert pages(BONES, MORE_BONES, between="A paragraph.") == (
        part + "| ulna | forearm |\n\nA paragraph.\n\n" + part + "| tibia | leg |"
    )


def test_a_table_with_another_title_starts_a_new_table() -> None:
    other = table([["NAME", "ROLE"], ["tibia", "leg"]], title="CHART 2-2. Legs")
    assert pages(BONES, other) == (
        "## CHART 2-1. Bones\n\n| NAME | ROLE |\n|---|---|\n| ulna | forearm |\n\n"
        "## CHART 2-2. Legs\n\n| NAME | ROLE |\n|---|---|\n| tibia | leg |"
    )


def test_a_headless_table_straight_after_one_of_its_shape_runs_on() -> None:
    first, second = table([["ulna", "forearm"]]), table([["tibia", "leg"]])
    assert pages(first, second) == "|   |   |\n|---|---|\n| ulna | forearm |\n| tibia | leg |"
    three = table([["a", "b", "c"]])  # another shape: a table of its own
    assert pages(first, three) == (
        "|   |   |\n|---|---|\n| ulna | forearm |\n\n|   |   |   |\n|---|---|---|\n| a | b | c |"
    )


def test_a_fill_in_list_nests_a_mixed_case_group_under_the_capitals_group() -> None:
    rows = [
        ["TERM", "NOTES"],
        ["UPPER LIMB", ""],
        ["humerus", ""],
        ["ulna", ""],
        ["Forearm muscles", ""],
        ["flexor", ""],
    ]
    assert md(ruled(rows, merged=((1, 0, 1, 1), (4, 0, 4, 1)))) == (
        "*Columns:* TERM · NOTES\n\n"
        "- **UPPER LIMB**\n  - humerus\n  - ulna\n  - **Forearm muscles**\n    - flexor"
    )


def test_a_headless_box_of_sorted_terms_is_a_list_read_down_its_columns() -> None:
    rows = [["BONES", "", ""], ["atlas", "femur", "tibia"], ["axis", "fibula", "ulna"]]
    assert md(ruled(rows, merged=((0, 0, 0, 2),))) == (
        "- **BONES**\n  - atlas\n  - axis\n  - femur\n  - fibula\n  - tibia\n  - ulna"
    )


def test_a_note_row_above_the_header_is_set_before_the_table() -> None:
    rows = [["REMARK: Learn these.", ""], ["NAME", "ROLE"], ["ulna", "forearm"]]
    assert md(ruled(rows, merged=((0, 0, 0, 1),))) == (
        "*Note:* Learn these.\n\n| NAME | ROLE |\n|---|---|\n| ulna | forearm |"
    )


def test_a_section_row_and_a_repeated_header_in_a_pipe_table() -> None:
    rows = [["NAME", "ROLE"], ["ARM", ""], ["ulna", "forearm"], ["Name", "Role"]]
    assert md(ruled(rows, merged=((1, 0, 1, 1),))) == (
        "| NAME | ROLE |\n|---|---|\n| **ARM** | |\n| ulna | forearm |"
    )


def test_a_single_column_is_a_list() -> None:
    assert md(ruled([["Bones to find"], ["• atlas"], ["axis"]])) == (
        "- Bones to find\n- atlas\n- axis"
    )
