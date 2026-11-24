"""Tests for backends._layout_pictures."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.backends._layout_pictures import (
    PageSource,
    figure_crop,
    figure_turn,
    picture,
    render_box,
    text_ceiling,
)
from pagespeak.backends._layout_profile import profile_from_mapping
from pagespeak.backends._layout_text import Doc
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line, record

PROF = profile_from_mapping(profile_mapping())


def test_a_picture_is_named_from_its_label_and_never_twice_the_same() -> None:
    d = Doc()
    assert picture(d, 7, [10, 20, 30, 40], "PLATE 1-1") == [
        "![PLATE 1-1](images/p0007-plate-1-1.jpeg)"
    ]
    assert (
        picture(d, 7, [10, 20, 30, 40], "PLATE 1-1", alt="the alt")[0]
        == "![the alt](images/p0007-plate-1-1-1.jpeg)"
    )
    assert d.crops[0] == (
        7,
        [7, 17, 33, 43],
        "p0007-plate-1-1.jpeg",
        0,
    )  # 3pt of padding all round


def test_a_figure_crop_runs_over_its_labels_and_stops_short_of_its_caption() -> None:
    cap = line("PLATE 1-1. A thing.", 72, 290)
    label = line(
        "tip", 280, 280, font="Helvetica", x1=300
    )  # set below the caption: the crop reaches over it
    f = {"box": [72, 300, 272, 420], "labels": [label], "caption": cap, "page": 2}
    src = PageSource(None, {2: record([cap, label])})
    box = figure_crop(f, src, PROF)
    assert box[2] == 300 and box[1] >= cap["y1"] + 4 and box[3] <= PROF.head_y


def test_a_figure_with_a_sideways_caption_turns_upright() -> None:
    assert (
        figure_turn({"caption": line("PLATE 1", 0, 0, vertical=True, up=True), "labels": []}) == -90
    )
    assert figure_turn({"caption": line("PLATE 1", 0, 0), "labels": []}) == 0


def test_a_cell_crop_stops_under_the_cell_name_over_its_drawing() -> None:
    name = line("deltoid", 80, 470)
    assert text_ceiling([72, 400, 222, 480], [name]) == name["y0"] - 1
    assert text_ceiling([72, 400, 222, 480], [line("far", 300, 470)]) is None


def test_a_box_is_one_quoted_paragraph() -> None:
    d = Doc()
    render_box(d, {"lines": [line("Boxed text", 80, 500), line("runs on.", 80, 489)]}, PROF)
    assert d.out == ["> Boxed text runs on.", ""]


def test_ink_reads_the_drawn_share_of_a_rendered_box(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium

    from pagespeak.backends._layout_pages import read_page
    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    src = PageSource(doc, {2: read_page(doc, 2)})
    assert src.ink(2, [80, 250, 260, 330]) > 0.9  # the grey picture, text painted out
    assert src.ink(2, [400, 100, 500, 150]) < 0.01  # empty page
    assert (
        src.ink_box(2, [80, 250, 260, 330]) is not None
        and src.ink_box(2, [400, 100, 500, 150]) is None
    )
