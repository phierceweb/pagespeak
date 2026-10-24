"""Tests for backends._docx_para — what the structured reader reads off a paragraph."""

from __future__ import annotations

import pytest

from pagespeak.backends._docx_para import _heading_level, _indent_depth


@pytest.mark.parametrize(
    ("style", "level"),
    [("Heading 1", 1), ("heading 3", 3), ("Heading 9", 6), ("Title", None), (None, None)],
)
def test_heading_level_reads_only_heading_n_styles(style: str | None, level: int | None) -> None:
    assert _heading_level(style) == level


def test_indent_depth_follows_the_left_indent() -> None:
    stack: list[int] = []
    depths = [_indent_depth(stack, left) for left in (0, 720, 1440, 720, 0, 720)]
    assert depths == [0, 1, 2, 1, 0, 1]
