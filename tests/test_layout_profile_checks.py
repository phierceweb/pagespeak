"""Tests for backends._layout_profile_checks."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout_profile import profile_from_mapping
from pagespeak.backends._layout_profile_checks import check_profile
from tests.fixtures.layout_book import profile_mapping

PROF = profile_from_mapping(profile_mapping())
RASTER = {"top": 600, "figure": [100, 300, 400, 500], "header": ["A", "B"], "rows": [["1", "x"]]}


def test_a_sound_profile_passes() -> None:
    check_profile(PROF)
    check_profile(replace(PROF, raster_tables={2: RASTER}, crop_overrides={"a": [0, 0, 1, 1]}))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"pages": (-1, 2)}, r"pages\.first must be between 0 and pages\.last, got -1 and 2"),
        ({"pages": (3, 2)}, r"pages\.first must be between 0 and pages\.last"),
        (
            {"skip_pages": frozenset({3})},
            r"pages\.skip names page 3 \(0-based\), outside .*\(0–2\)",
        ),
        (
            {"flow_chart_pages": frozenset({5})},
            r"pages\.flow_charts names page 5 \(0-based\), outside",
        ),
        ({"pages": (1, 2)}, r"title_block\.cover_page names page 0 \(0-based\), outside"),
        ({"drop_lines": ((4, None),)}, r"drop_lines\[0\]\.page names page 4 \(0-based\), outside"),
        ({"raster_tables": {7: RASTER}}, r"raster_tables names page 7 \(0-based\), outside"),
        ({"floor_y": 740.0}, r"bands\.floor_y must be below bands\.head_y, got 740 and 740"),
        ({"page_number_inner": (500.0, 500.0)}, r"page_number_inner must run from left to right"),
        (
            {"crop_overrides": {"a.jpeg": [1.0, 2.0, 1.0, 4.0]}},
            r"crop_overrides\.a\.jpeg must be a box",
        ),
        (
            {"crop_overrides": {"a.jpeg": [1.0, 4.0, 3.0, 4.0]}},
            r"crop_overrides\.a\.jpeg must be a box",
        ),
        (
            {"raster_tables": {2: dict(RASTER, figure=[100, 500, 400, 300])}},
            r"raster_tables\.2\.figure must be a box",
        ),
        (
            {"raster_tables": {2: dict(RASTER, rows=[["1", "x"], ["2"]])}},
            r"raster_tables\.2\.rows\[1\] must have 2 cells, as the header has, got 1",
        ),
    ],
)
def test_values_that_cannot_work_together_are_refused(change: dict, message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        check_profile(replace(PROF, **change))


@pytest.mark.parametrize("level", [0, 7, -1])
def test_a_heading_level_markdown_does_not_have_is_refused(level: int) -> None:
    rules = (replace(PROF.headings[0], level=1), replace(PROF.headings[0], level=level))
    with pytest.raises(InvalidInputError, match=r"headings\[1\]\.level must be between 1 and 6"):
        check_profile(replace(PROF, headings=rules))
    check_profile(replace(PROF, headings=(replace(PROF.headings[0], level=6),)))


@pytest.mark.parametrize(
    ("field", "template", "names"),
    [
        ("heading", "Part {x}", r"\{n\}, \{title\}"),
        ("heading", "Part {", r"\{n\}, \{title\}"),
        ("heading", "Part {0}", r"\{n\}, \{title\}"),
        ("picture_label", "{title} picture", r"\{n\}$"),
    ],
)
def test_a_template_with_a_name_it_is_not_given_is_refused(
    field: str, template: str, names: str
) -> None:
    opener = replace(PROF.opener, **{field: template})
    with pytest.raises(
        InvalidInputError, match=rf"opener\.{field} is not a valid template.*it may use {names}"
    ):
        check_profile(replace(PROF, opener=opener))


def test_the_box_message_says_which_way_round_a_box_runs() -> None:
    with pytest.raises(InvalidInputError) as caught:
        check_profile(replace(PROF, crop_overrides={"a.jpeg": [3.0, 2.0, 1.0, 4.0]}))
    assert str(caught.value) == (
        "layout profile: document.crop_overrides.a.jpeg must be a box [left, bottom, right, top] "
        "with left < right and bottom < top, got [3.0, 2.0, 1.0, 4.0]"
    )
