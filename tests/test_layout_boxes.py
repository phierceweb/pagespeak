"""Tests for backends._layout_boxes."""

from __future__ import annotations

from pagespeak.backends._layout_boxes import inside, mid, near, overlap, union
from tests.fixtures.layout_lines import line


def test_union_overlap_and_nearness() -> None:
    assert union([0, 0, 10, 10], [5, -5, 20, 8]) == [0, -5, 20, 10]
    assert (
        overlap([0, 0, 10, 10], [5, 5, 20, 20]) == 25 and overlap([0, 0, 1, 1], [5, 5, 6, 6]) == 0
    )
    assert near([0, 0, 10, 10], [14, 0, 20, 10], 4) and not near([0, 0, 10, 10], [15, 0, 20, 10], 4)


def test_a_line_is_inside_a_box_by_its_middle() -> None:
    ln = line("abc", 10, 100)  # x 10..25, y 98..107
    assert mid(ln) == (17.5, 102.5)
    assert inside(ln, [15, 100, 20, 103]) and not inside(ln, [30, 100, 40, 103])
