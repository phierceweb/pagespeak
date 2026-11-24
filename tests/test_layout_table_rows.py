"""Tests for backends._layout_table_rows."""

from __future__ import annotations

from pagespeak.backends._layout_profile import profile_from_mapping
from pagespeak.backends._layout_table_rows import body_rows, head, key_column, prepare
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line, ruled, table

PROF = profile_from_mapping(profile_mapping())


def rows_of(f):
    tb = prepare(f, PROF)
    head(tb, PROF)
    key_column(tb)
    return tb, body_rows(tb, PROF)


def test_the_capitals_row_is_the_header_and_the_rest_are_rows() -> None:
    tb, rows = rows_of(table([["TERM", "MEANING"], ["cell", "life"], ["tissue", "cells"]]))
    assert tb["names"] == ["TERM", "MEANING"] and tb["title"] is None
    assert rows == [("row", ["cell", "life"], 0), ("row", ["tissue", "cells"], 0)]


def test_a_title_row_spanning_the_table_is_its_title() -> None:
    tb, rows = rows_of(table([["NAME", "ROLE"], ["ulna", "forearm"]], title="CHART 2-1. Bones"))
    assert tb["title"] == "CHART 2-1. Bones" and tb["names"] == ["NAME", "ROLE"]
    assert rows == [("row", ["ulna", "forearm"], 0)]


def test_without_a_capitals_row_there_is_no_header() -> None:
    tb, rows = rows_of(table([["cell", "life"], ["tissue", "cells"]]))
    assert tb["header"] is None and tb["names"] == ["", ""] and len(rows) == 2


def test_a_key_cell_spanning_two_rows_is_named_on_each(tmp_path) -> None:
    import pytest

    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page
    from pagespeak.backends._layout_tables import find_tables
    from tests.fixtures.layout_book import SPAN_HEADER, SPAN_TITLE, make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    (t,) = find_tables(read_page(doc, 3), rules_below=740)
    tb, rows = rows_of({"table": t})
    assert tb["title"] == SPAN_TITLE and tb["names"] == list(SPAN_HEADER)
    assert rows == [
        ("row", ["humerus", "head", "joins the scapula"], 0),
        ("row", ["humerus", "shaft", "holds the muscles"], 0),
        ("row", ["ulna", "olecranon", "forms the elbow"], 0),
    ]


def test_sub_rows_under_a_spanning_key_show_a_shaded_empty_cell_as_a_dash() -> None:
    rows = [["BONE", "PART", "ROLE"], ["humerus", "head", "joins"], ["", "shaft", ""]]
    _, out = rows_of(ruled(rows, merged=((1, 0, 2, 0),), shaded=((2, 2),)))
    assert out == [
        ("row", ["humerus", "head", "joins"], 0),
        ("row", ["humerus", "shaft", "—"], 0),
    ]
    _, plain = rows_of(ruled(rows, merged=((1, 0, 2, 0),)))
    assert plain[1] == ("row", ["humerus", "shaft", ""], 0)  # an unshaded empty cell stays empty


def test_a_shaded_empty_cell_in_a_plain_row_is_a_dash() -> None:
    rows = [["BONE", "ROLE"], ["ulna", ""], ["tibia", ""]]
    _, out = rows_of(ruled(rows, shaded=((1, 1),)))
    assert out == [("row", ["ulna", "—"], 0), ("row", ["tibia", ""], 0)]


def test_a_column_of_sideways_labels_gives_a_section_row_once_per_group() -> None:
    rows = [["", "BONE", "ROLE"], ["", "humerus", "upper arm"], ["", "ulna", "forearm"]]
    arm = line("ARM", 100, 460, vertical=True, up=True)
    tb, out = rows_of(ruled(rows, merged=((1, 0, 2, 0),), extra=(arm,)))
    assert tb["group_cols"] == [0] and tb["names"] == ["BONE", "ROLE"]
    assert out == [
        ("section", "ARM"),
        ("row", ["humerus", "upper arm"], 0),
        ("row", ["ulna", "forearm"], 0),
    ]


def test_a_row_across_the_whole_table_is_a_section() -> None:
    rows = [["NAME", "ROLE"], ["ARM", ""], ["ulna", "forearm"]]
    _, out = rows_of(ruled(rows, merged=((1, 0, 1, 1),)))
    assert out == [("section", "ARM"), ("row", ["ulna", "forearm"], 0)]


def test_ticked_terms_take_a_level_from_their_indent() -> None:
    rows = [["TERM", "NOTES"], ["", ""], ["", ""]]
    ticks = (line("☐ arm", 80, 466), line("☐ forearm", 97, 446))
    _, out = rows_of(ruled(rows, extra=ticks))
    assert out == [("row", ["arm", ""], 0), ("row", ["forearm", ""], 1)]


def test_several_terms_ticked_in_one_cell_are_a_row_each() -> None:
    rows = [["TERM", "NOTES"], ["", ""]]
    ticks = (line("☐ arm", 80, 446), line("☐ hand", 97, 432))
    _, out = rows_of(ruled(rows, extra=ticks, row_h=40))
    assert out == [("row", ["arm", ""], 0), ("row", ["hand", ""], 1)]
