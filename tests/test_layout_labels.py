"""Tests for backends._layout_labels."""

from __future__ import annotations

import pytest

from pagespeak.backends._layout_labels import claim_labels
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line

PROF = profile_from_mapping(profile_mapping())


def claim(lines, box=(100, 300, 300, 500), caption=None, frames=()):
    f = {"box": list(box), "caption": caption, "labels": [], "top": box[3]}
    used: set[int] = set()
    claim_labels(f, lines, used, list(frames), PROF)
    return f, used


def claimed(f) -> set[str]:
    return {ln["text"] for ln in f["labels"]}


def label(text: str, x: float, base: float, **extra):
    return line(text, x, base, font="Helvetica", **extra)


def test_labels_on_the_art_are_claimed_and_running_text_is_not() -> None:
    label = line("femur", 150, 400, font="Helvetica")
    prose = line("The femur is the long bone of the thigh and runs from hip to knee.", 72, 200)
    f, used = claim([label, prose])
    assert f["labels"] == [label] and used == {id(label)}


def test_a_numbered_key_below_the_picture_is_claimed_row_by_row() -> None:
    keys = [
        line("1. ulna", 100, 290, font="Helvetica"),
        line("2. radius", 100, 278, font="Helvetica"),
    ]
    f, _ = claim(keys)
    assert [ln["text"] for ln in f["labels"]] == ["1. ulna", "2. radius"]


def test_a_key_above_the_art_raises_the_box() -> None:
    key = line("a. cortex", 150, 520, font="Helvetica")
    f, _ = claim([key])
    assert f["box"][3] == key["y1"] and f["frames"] == []


def test_the_instruction_line_over_the_picture_reads_first() -> None:
    note = line("Skip this instruction: colour each part.", 120, 480, font="Helvetica")
    f, used = claim([note])
    assert id(note) not in used and f["box"][3] == note["y0"] - 2 and f["top"] == note["base"] + 6


def test_a_key_running_far_below_the_picture_is_claimed_to_its_last_row() -> None:
    bases = [290, 278, 266, 254, 242, 230, 218, 206]  # five rows lie beyond the 40pt around the art
    left = [label(f"{i + 1}. bone {i + 1}", 100, b) for i, b in enumerate(bases)]
    right = [label(f"{i + 9}. bone {i + 9}", 220, b) for i, b in enumerate(bases)]
    prose = line("Body text set under the key, in the body face.", 100, 194)
    apart = label("Notes", 100, 150)
    f, used = claim([*left, *right, prose, apart])
    assert claimed(f) == {ln["text"] for ln in left + right}
    assert id(prose) not in used and id(apart) not in used


def test_a_key_below_needs_a_numbered_entry_to_start_it() -> None:
    f, _ = claim([label("bone one", 100, 254), label("bone two", 100, 242)])
    assert f["labels"] == []


def test_a_head_well_above_the_picture_stops_the_labels_claimed_above_it() -> None:
    below = [label("a. cortex", 150, 510), label("b. medulla", 150, 522)]
    head = line("KIDNEY", 150, 580, font="Helvetica-Bold", h=10)  # beyond the 40pt around the key
    beyond = label("c. capsule", 150, 600)
    f, used = claim([*below, head, beyond])
    assert claimed(f) == {"a. cortex", "b. medulla"} and id(head) not in used
    f, _ = claim([*below, beyond])  # with no head between, all three are the key
    assert claimed(f) == {"a. cortex", "b. medulla", "c. capsule"}


def test_a_table_above_the_picture_stops_the_labels_claimed_above_it() -> None:
    under, over = label("a. cortex", 150, 540), label("b. medulla", 150, 610)
    f, _ = claim([under, over], frames=[[100, 560, 300, 600]])
    assert claimed(f) == {"a. cortex"}
    f, _ = claim([under, over])
    assert claimed(f) == {"a. cortex", "b. medulla"}


def test_a_key_block_taller_than_the_first_reach_is_claimed_on_upward() -> None:
    key = [label(f"{chr(97 + i)}. part", 150, 510 + 12 * i) for i in range(13)]  # up to base 654
    f, _ = claim(key)
    assert claimed(f) == {ln["text"] for ln in key}
    assert f["box"][3] == key[-1]["y1"]  # the art's box rises to the top of its key


def test_claiming_on_upward_stops_at_a_head() -> None:
    key = [label(f"{chr(97 + i)}. part", 150, 510 + 12 * i) for i in range(13)]  # top edge at 661
    head = line("KIDNEY", 150, 667, font="Helvetica-Bold", h=10)
    run = [label(f"note {i}", 150, 682 + 12 * i) for i in range(5)]  # bases 682 to 730
    f, _ = claim([*key, head, *run])
    beyond_reach = {ln["text"] for ln in run if ln["base"] > 700}  # more than 40pt above the key
    assert beyond_reach == {"note 2", "note 3", "note 4"} and not beyond_reach & claimed(f)
    f, _ = claim([*key, *[label(f"note {i}", 150, 666 + 12 * i) for i in range(6)]])
    assert {f"note {i}" for i in range(6)} <= claimed(f)  # with no head, the run is all one key


def test_running_text_beside_the_art_is_not_a_label_but_text_printed_on_it_is() -> None:
    beside = line("runs on.", 305, 400, x1=330)  # body face, within 40pt of the art, not on it
    on_art = line("anterior", 150, 400)  # body face, printed on the art
    side_label = label("lateral", 305, 420, x1=335)
    f, used = claim([beside, on_art, side_label])
    assert claimed(f) == {"anterior", "lateral"} and id(beside) not in used


def test_a_heading_face_line_within_reach_above_the_picture_is_taken_as_its_label() -> None:
    letter = line("A", 100, 510, font="Helvetica-Bold", h=10)  # a panel letter over the art
    f, _ = claim([letter])
    assert claimed(f) == {"A"}


@pytest.mark.parametrize(("base", "taken"), [(535.5, True), (536.5, False)])
def test_a_heading_face_line_is_a_label_only_within_40pt_above_the_art(
    base: float, taken: bool
) -> None:
    head = line(
        "KIDNEY", 100, base, font="Helvetica-Bold", h=10
    )  # its middle 39.5pt or 40.5pt above
    f, used = claim([head])
    assert (id(head) in used) is taken
