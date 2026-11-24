"""Tests for backends._layout_page."""

from __future__ import annotations

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout_page import (
    classify,
    flow_chart,
    furniture,
    is_opener,
    margin,
    merge_tracked,
)
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import grid_rules, line, record

PROF = profile_from_mapping(profile_mapping())


def test_furniture_is_the_running_head_page_number_and_furniture_faces() -> None:
    assert furniture(line("A Small Book", 72, 752), False, PROF)  # above head_y
    assert furniture(line("3", 560, 22), False, PROF)  # page number outside the inner margins
    assert not furniture(line("3", 300, 22), False, PROF)  # a number in the text column
    assert furniture(line("draft", 72, 400, font="Courier"), False, PROF)
    assert not furniture(line("body text", 72, 400), False, PROF)


def test_an_opener_is_found_by_its_line_and_drops_its_display_type() -> None:
    rec = record([line("PART", 72, 732, font="Helvetica-Bold")])
    assert is_opener(rec, PROF)
    assert not is_opener(record([line("PART", 72, 500, font="Helvetica-Bold")]), PROF)
    big = line("1", 72, 600, h=50)
    big["y1"] = big["y0"] + 60
    assert furniture(big, True, PROF) and not furniture(big, False, PROF)


def test_margin_is_the_lower_quartile_of_long_lines() -> None:
    long = "x" * 50
    assert (
        margin([line(long, 72, 500), line(long, 90, 480), line(long, 72, 460), line(long, 72, 440)])
        == 72
    )
    assert margin([line("short", 300, 500)]) == 90


def test_a_letter_spaced_head_is_joined() -> None:
    out = merge_tracked([line("PLANT", 72, 500, h=9, x1=110), line("CELLS", 120, 500, h=9)])
    assert [ln["text"] for ln in out] == ["PLANT CELLS"]


def test_classify_takes_tables_and_figures_out_and_leaves_text() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    lines = [
        line("TERM", 80, 425),
        line("MEANING", 230, 425),
        line("cell", 80, 405),
        line("life", 230, 405),
        line("PLATE 1-1. A picture.", 72, 200),
        line("Body text below.", 72, 150),
        line("A Small Book", 72, 752),
    ]
    items, floats = classify(record(lines, rules=rules, images=[[72, 220, 272, 320]]), PROF)
    assert [it["line"]["text"] for it in items if it["kind"] == "text"] == ["Body text below."]
    kinds = sorted(f["kind"] for f in floats)
    assert kinds == ["figure", "table"]
    fig = next(f for f in floats if f["kind"] == "figure")
    assert fig["caption"]["text"] == "PLATE 1-1. A picture." and fig["box"][:2] == [72, 220]


def test_a_flow_chart_page_is_one_figure_under_its_lead_in() -> None:
    lines = [
        line("Follow the chart.", 72, 600),
        line("Start", 100, 420, font="Helvetica"),
        line("PLATE 1-1. The route.", 72, 300),
    ]
    rules = grid_rules([90, 200], [400, 440])
    items, (fig,) = flow_chart(record(lines, rules=rules), PROF)
    assert [it["line"]["text"] for it in items] == ["Follow the chart."]
    assert fig["caption"]["text"] == "PLATE 1-1. The route."
    assert [ln["text"] for ln in fig["labels"]] == ["Start"] and fig["box"][3] == fig["top"]


@pytest.mark.parametrize("keep", ["caption", "chart"])
def test_a_flow_chart_page_without_its_caption_or_chart_is_refused(keep: str) -> None:
    lines = [line("PLATE 1-1. The route.", 72, 300)] if keep == "caption" else []
    rules = grid_rules([90, 200], [400, 440]) if keep == "chart" else []
    with pytest.raises(InvalidInputError, match=r"pages\.flow_charts: page 2 "):
        flow_chart(record(lines, rules=rules), PROF)


def test_an_opener_drops_display_type_by_its_face_as_well_as_its_height() -> None:
    title = line("First Things", 72, 600, font="Helvetica-Light", h=31)
    assert furniture(title, True, PROF) and not furniture(title, False, PROF)
    assert not furniture(line("First Things", 72, 600, font="Helvetica-Light", h=29), True, PROF)
    assert not furniture(line("First Things", 72, 600, font="Helvetica-Bold", h=31), True, PROF)


def _blanks(lines, strokes, **extra) -> list[float]:
    rec = record(lines, **extra)
    rec["strokes"] = strokes
    items, _ = classify(rec, PROF)
    return [it["top"] for it in items if it["kind"] == "blank"]


def test_a_long_drawn_line_is_a_blank_to_write_on() -> None:
    assert _blanks([line("Name:", 72, 420)], [[120, 400, 300, 400.5]]) == [400]
    assert _blanks([], [[120, 400, 180, 400.5]]) == []  # too short to write on
    assert _blanks([], [[120, 400, 300, 403]]) == []  # a bar, not a line
    assert _blanks([], [[120, 745, 300, 745.5]]) == []  # in the running head


def test_a_line_drawn_under_text_or_beside_a_figure_is_no_blank() -> None:
    underlined = line("An underlined heading", 120, 403)
    assert _blanks([underlined], [[120, 400, 300, 400.5]]) == []
    assert _blanks([], [[72, 318, 272, 318.5]], images=[[72, 320, 272, 420]]) == []


def test_a_chapter_opener_has_no_blanks() -> None:
    opener = line("PART", 72, 732, font="Helvetica-Bold")
    assert _blanks([opener], [[120, 400, 300, 400.5]]) == []


def test_a_line_set_sideways_beside_a_table_is_its_lead_in() -> None:
    rules = grid_rules([72, 222, 372], [400, 420, 440])
    cells = [line("TERM", 80, 425), line("MEANING", 230, 425), line("cell", 80, 405)]
    beside = line("Fill in each row.", 55, 420, vertical=True, up=True, x1=70)
    far = line("Not beside it.", 20, 420, vertical=True, up=True, x1=30)
    items, floats = classify(record([*cells, beside, far], rules=rules), PROF)
    (t,) = [f["table"] for f in floats if f["kind"] == "table"]
    assert t["lead"] == [beside]
    assert [it["line"]["text"] for it in items if it["kind"] == "text"] == ["Not beside it."]
