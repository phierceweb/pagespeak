"""Tests for backends._layout_tables."""

from __future__ import annotations

from pagespeak.backends._layout_tables import components, find_tables, grid
from tests.fixtures.layout_lines import grid_rules, line, record


def test_touching_rules_form_one_set_and_apart_rules_another() -> None:
    rules = grid_rules([0, 50, 100], [0, 20, 40]) + grid_rules([300, 350], [300, 320])
    assert sorted(len(c) for c in components(rules)) == [4, 6]


def test_a_full_grid_has_one_cell_per_slot() -> None:
    (comp,) = components(grid_rules([0, 50, 100], [0, 20, 40]))
    cells = grid(comp)
    assert len(cells) == 4
    assert cells[0][:4] == [0.0, 20.0, 50.0, 40.0] and cells[0][4:] == [
        0,
        0,
        0,
        0,
    ]  # rows count from the top


def test_a_missing_rule_merges_the_cells_it_would_part() -> None:
    rules = [r for r in grid_rules([0, 50, 100], [0, 20, 40]) if not (r[0] > 49 and r[2] < 51)]
    rules += [[49.75, 0, 50.25, 20]]  # the middle border drawn in the lower row only
    (comp,) = components(rules)
    cells = grid(comp)
    assert len(cells) == 3 and [c[4:] for c in cells][0] == [0, 0, 0, 1]


def test_find_tables_puts_each_line_in_its_cell() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    lines = [
        line("TERM", 80, 425),
        line("MEANING", 230, 425),
        line("cell", 80, 405),
        line("life", 230, 405),
    ]
    (t,) = find_tables(record(lines, rules=rules), rules_below=700)
    assert t["kind"] == "table" and (t["rows"], t["cols"]) == (2, 2)
    assert [[ln["text"] for ln in h] for h in t["held"]] == [
        ["TERM"],
        ["MEANING"],
        ["cell"],
        ["life"],
    ]


def test_rules_above_the_band_and_bare_frames_are_not_tables() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    lines = [line("TERM", 80, 425), line("cell", 80, 405)]
    assert find_tables(record(lines, rules=rules), rules_below=399) == []
    assert find_tables(record([], rules=rules), rules_below=700) == []


def test_a_missing_rule_under_a_cell_merges_it_with_the_cell_below() -> None:
    rules = [r for r in grid_rules([0, 50, 100], [0, 20, 40]) if not (19 < r[1] < 21)]
    rules += [[50, 19.75, 100, 20.25]]  # the middle rule drawn under the right column only
    (comp,) = components(rules)
    cells = grid(comp)
    assert [c[4:] for c in cells] == [[0, 1, 0, 0], [0, 0, 1, 1], [1, 1, 1, 1]]
    assert cells[0][:4] == [0.0, 0.0, 50.0, 40.0]


def test_a_generated_table_gives_its_title_row_and_its_spanning_cell(tmp_path) -> None:
    import pytest

    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page
    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    (t,) = find_tables(read_page(doc, 3), rules_below=740)
    spans = {
        " ".join(ln["text"] for ln in held): c[4:]
        for c, held in zip(t["cells"], t["held"], strict=True)
    }
    assert (t["rows"], t["cols"]) == (5, 3)
    assert spans["CHART 1-1. Bones of the arm"] == [0, 0, 0, 2]  # across every column
    assert spans["humerus"] == [2, 3, 0, 0]  # down two rows
    assert spans["head"] == [2, 2, 1, 1] and spans["shaft"] == [3, 3, 1, 1]


def test_a_writing_line_drawn_in_a_cell_is_a_blank_in_it() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    lines = [line("TERM", 80, 425), line("MEANING", 230, 425), line("cell", 80, 405)]
    rec = record(lines, rules=rules)
    rec["strokes"] = [[240, 404, 360, 404.5]]
    (t,) = find_tables(rec, rules_below=700)
    assert [[ln["text"] for ln in h] for h in t["held"]] == [
        ["TERM"],
        ["MEANING"],
        ["cell"],
        ["____________"],
    ]
    assert t["held"][3][0]["drawn"] is True


def test_an_underline_or_a_stroke_on_a_cell_border_is_no_blank() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    lines = [line("TERM", 80, 425), line("MEANING", 230, 425), line("cell", 80, 405)]
    rec = record(lines, rules=rules)
    rec["strokes"] = [
        [80, 401.5, 110, 402],  # under the word "cell"
        [223, 404, 371, 404.5],  # from border to border: a rule of the grid
        [240, 404, 250, 404.5],  # too short
    ]
    (t,) = find_tables(rec, rules_below=700)
    assert [len(h) for h in t["held"]] == [1, 1, 1, 0]
