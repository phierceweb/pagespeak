"""Tests for backends._layout_figures."""

from __future__ import annotations

from pagespeak.backends._layout_figures import page_figures, picture_groups
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line, record

PROF = profile_from_mapping(profile_mapping())


def figures(lines, images):
    return page_figures(record(lines, images=images), lines, set(), [], PROF)


def test_a_picture_takes_the_caption_below_it() -> None:
    (fig,) = figures([line("PLATE 2-1. Bones.", 72, 300)], [[72, 320, 272, 420]])
    assert fig["caption"]["text"] == "PLATE 2-1. Bones." and fig["box"] == [72, 320, 272, 420]


def test_one_area_holding_two_figures_is_cut_at_the_inner_caption() -> None:
    caps = [line("PLATE 2-1. Upper.", 72, 450), line("PLATE 2-2. Lower.", 72, 250)]
    figs = figures(caps, [[72, 270, 272, 600]])
    assert sorted(f["caption"]["text"] for f in figs) == [
        "PLATE 2-1. Upper.",
        "PLATE 2-2. Lower.",
    ]
    upper = next(f for f in figs if f["caption"]["text"].endswith("Upper."))
    assert upper["box"][1] > 450  # the cut runs above the inner caption


def test_a_caption_running_onto_a_second_line_is_joined() -> None:
    caps = [line("PLATE 2-1. A long", 72, 300), line("caption.", 72, 290)]
    (fig,) = figures(caps, [[72, 320, 272, 420]])
    assert fig["caption"]["text"] == "PLATE 2-1. A long caption."


def _left_as_text(lines, rules=(), images=()):
    """What `page_figures` leaves for the page's text, with the figures it found."""
    used: set[int] = set()
    figs = page_figures(
        record(lines, rules=list(rules), images=list(images)), lines, used, [], PROF
    )
    return [ln["text"] for ln in lines if id(ln) not in used], figs


def test_a_caption_with_nothing_drawn_is_no_figure_and_stays_text() -> None:
    lines = [
        line("A paragraph of running text.", 72, 600),
        line("Its second line.", 72, 586),
        line("PLATE 2-1. Nothing drawn.", 72, 500),
    ]
    assert _left_as_text(lines) == ([ln["text"] for ln in lines], [])


def test_a_line_drawn_above_a_caption_is_no_chart() -> None:
    lines = [
        line("DIVIDER", 72, 640, font="Helvetica-Bold", h=10),
        line("Text above the divider line.", 72, 600),
        line("PLATE 2-2. Under a line.", 72, 500),
    ]
    divider = [[72, 550, 540, 550.5]]
    assert _left_as_text(lines, rules=divider) == ([ln["text"] for ln in lines], [])


def test_running_text_that_starts_like_a_caption_keeps_its_next_line() -> None:
    lines = [
        line("The leg is drawn in the next chapter, where", 72, 600),
        line("PLATE 2-1 shows the bones of the leg in detail.", 72, 586),
        line("The thigh bone is the longest of them.", 72, 572),
    ]
    assert _left_as_text(lines) == ([ln["text"] for ln in lines], [])
    pic = [72, 300, 272, 400]  # a picture elsewhere on the page changes nothing for those lines
    text, (fig,) = _left_as_text(lines, images=[pic])
    assert text == [ln["text"] for ln in lines] and fig["caption"] is None


def test_a_bound_caption_and_the_line_it_runs_onto_leave_the_text() -> None:
    lines = [
        line("Body above.", 72, 600),
        line("PLATE 2-1. A long", 72, 300),
        line("caption.", 72, 290),
    ]
    text, (fig,) = _left_as_text(lines, images=[[72, 320, 272, 420]])
    assert text == ["Body above."] and fig["caption"]["text"] == "PLATE 2-1. A long caption."


def test_a_picture_outside_the_body_band_is_no_figure() -> None:
    assert figures([], [[72, 5, 272, PROF.floor_y - 5]]) == []  # wholly below the floor
    assert figures([], [[72, 745, 272, 785]]) == []  # wholly above the running head's line
    (fig,) = figures([], [[72, 30, 272, 130]])  # across the floor: still a figure
    assert fig["box"] == [72, 30, 272, 130]


def _bound(caps, images, frames=()):
    """Each figure's caption text (None: no caption) and its box; an unbound caption makes no figure."""
    lines = list(caps)
    figs = page_figures(record(lines, images=images), lines, set(), list(frames), PROF)
    return {(f["caption"] or {}).get("text"): f["box"] for f in figs}


def test_a_picture_takes_only_a_caption_set_below_it() -> None:
    pic = [72, 320, 272, 420]
    assert _bound([line("PLATE 2-1. Above.", 72, 440)], [pic]) == {None: pic}
    assert _bound([line("PLATE 2-1. Just under.", 72, 300)], [pic]) == {
        "PLATE 2-1. Just under.": pic
    }


def test_a_picture_takes_the_nearest_caption_below_it() -> None:
    pic = [72, 320, 272, 420]
    caps = [line("PLATE 2-1. Near.", 72, 300), line("PLATE 2-2. Far.", 72, 100)]
    assert _bound(caps, [pic]) == {"PLATE 2-1. Near.": pic}


def test_a_table_set_between_a_picture_and_a_caption_keeps_them_apart() -> None:
    pic, cap = [72, 320, 272, 420], line("PLATE 2-1. Under a table.", 72, 200)
    assert _bound([cap], [pic]) == {"PLATE 2-1. Under a table.": pic}
    between = [72, 240, 372, 300]
    assert _bound([cap], [pic], frames=[between]) == {None: pic}
    below = [72, 120, 372, 180]  # a table under the caption parts nothing
    assert _bound([cap], [pic], frames=[below]) == {"PLATE 2-1. Under a table.": pic}


def test_a_caption_far_to_one_side_of_a_picture_is_not_its_caption() -> None:
    pic = [72, 320, 272, 420]
    near = line("PLATE 2-1. A little right.", 300, 300)  # starts within 40pt of the picture's edge
    far = line("PLATE 2-1. Far right.", 320, 300)
    left = line("PLATE 2-1.", 400, 300, x1=440)
    assert _bound([near], [pic]) == {"PLATE 2-1. A little right.": pic}
    assert _bound([far], [pic]) == {None: pic}
    assert _bound([left], [[490, 320, 560, 420]]) == {None: [490, 320, 560, 420]}


def test_pictures_with_no_caption_are_grouped() -> None:
    assert picture_groups([[0, 0, 10, 10], [15, 0, 25, 10], [200, 200, 210, 210]], gap=12) == [
        [200, 200, 210, 210],
        [0, 0, 25, 10],
    ]
    (fig,) = figures([], [[72, 320, 272, 420]])
    assert fig["caption"] is None and fig["box"] == [72, 320, 272, 420]


def test_picture_areas_that_meet_only_once_joined_end_as_one_group() -> None:
    upper, tall, bar = [50, 60, 60, 100], [0, 30, 10, 90], [20, 20, 60, 30]
    # the bar touches the tall area only; joined, the two reach the upper one
    assert picture_groups([upper, tall, bar], gap=12) == [[0, 20, 60, 100]]
    assert len(picture_groups([upper, tall], gap=12)) == 2


def test_a_line_two_captions_could_run_onto_goes_to_one_of_them_only() -> None:
    from pagespeak.backends._layout_figures import _captions

    first, second = line("PLATE 2-1. First", 72, 300), line("PLATE 2-2. Second", 72, 296)
    shared = line("run-on.", 72, 288)
    caps, made_of = _captions([first, second, shared], set(), PROF)
    assert [c["text"] for c in caps] == ["PLATE 2-1. First run-on.", "PLATE 2-2. Second"]
    assert made_of[id(caps[0])] == [first, shared] and made_of[id(caps[1])] == [second]
