"""Tests for backends._layout_document."""

from __future__ import annotations

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout_document import build, nest_sections, numbered_stops, read_pages
from pagespeak.backends._layout_pictures import PageSource
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping
from tests.fixtures.layout_lines import line, record

PROF = profile_from_mapping(profile_mapping())


def test_lines_under_a_stops_heading_read_as_a_numbered_list() -> None:
    text = "## BLOOD ROUTE\n\n**heart**\n\n______\n\n| aorta | to the body |\n\n## NEXT"
    assert (
        numbered_stops(text, PROF)
        == "## BLOOD ROUTE\n\n1. **heart**\n2. ______\n3. aorta to the body\n\n## NEXT"
    )


def test_an_excluded_stops_heading_keeps_its_lines_as_they_are() -> None:
    text = "## ROUTE REVIEW\n\n**heart**"
    assert numbered_stops(text, PROF) == text


def test_items_after_a_topic_head_nest_under_it_and_asides_stay_level() -> None:
    text = "# Ch\n\n## BLOOD\n\n## PLATE 1-1\n\n## SUMMARY\n\n## CHART 1-1"
    assert (
        nest_sections(text, PROF)
        == "# Ch\n\n## BLOOD\n\n### PLATE 1-1\n\n## SUMMARY\n\n## CHART 1-1"
    )


def test_a_head_with_no_body_groups_the_heads_after_it_only_when_the_profile_says_so() -> None:
    text = "# Ch\n\n## PARTS\n\n## FIRST\n\nBody.\n\n## SECOND\n\n### Deeper\n\n# Next\n\n## AFTER"
    assert nest_sections(text, PROF) == text
    m = profile_mapping()
    m["document"]["group_after_empty_head"] = True
    assert nest_sections(text, profile_from_mapping(m)) == (
        "# Ch\n\n## PARTS\n\n### FIRST\n\nBody.\n\n### SECOND\n\n#### Deeper\n\n# Next\n\n## AFTER"
    )


def _pages(*chapter_lines: dict) -> dict[int, dict]:
    return {
        0: record([line("Second Edition", 72, 550, font="Helvetica")], page=0),
        1: record([line("ISBN 1", 72, 92)], page=1),
        2: record(list(chapter_lines), page=2),
    }


def _title(**change: object) -> str:
    m = profile_mapping()
    m["document"]["title_block"].update(change)
    text, _ = build(PageSource(None, _pages(line("Body.", 72, 150))), profile_from_mapping(m))
    return text


def test_the_title_block_takes_the_lines_its_profile_names() -> None:
    assert _title().startswith("# A Small Book\n\nSecond Edition. ISBN 1.\n")
    assert _title(lines=[]).startswith("# A Small Book\n\nSecond Edition.\n")
    assert _title(keep="^Nothing", lines=[]).startswith("# A Small Book\n\nBody.")


def test_a_title_block_line_the_book_does_not_have_is_refused() -> None:
    with pytest.raises(
        InvalidInputError, match=r"title_block\.lines\[0\]: no line on page 1 .*'\^DOI'"
    ):
        _title(lines=[{"page": 1, "pattern": "^DOI"}])


def test_a_chapter_opener_past_the_listed_titles_is_refused() -> None:
    pages = _pages(line("PART", 72, 732, font="Helvetica-Bold"))
    pages[3] = record([line("PART", 72, 732, font="Helvetica-Bold")], page=3)
    m = profile_mapping()
    m["pages"]["last"] = 3
    with pytest.raises(InvalidInputError, match=r"page 3 .* opens chapter 2, but .* lists 1"):
        build(PageSource(None, pages), profile_from_mapping(m))


def test_the_pages_read_skip_the_cover_and_the_skipped() -> None:
    assert read_pages(PROF) == [2]


def test_build_reads_records_into_one_document_and_applies_crop_overrides() -> None:
    m = profile_mapping()
    m["document"]["crop_overrides"] = {"p0002-plate-1-1.jpeg": [1, 2, 3, 4]}
    prof = profile_from_mapping(m)
    pages = {
        0: record([line("Second Edition", 72, 550, font="Helvetica")], page=0),
        1: record([line("ISBN 1", 72, 92)], page=1),
        2: record(
            [
                line("PART", 72, 732, font="Helvetica-Bold"),
                line("PLATE 1-1. A thing.", 72, 290),
                line("Some body text.", 72, 150),
            ],
            page=2,
            images=[[72, 300, 272, 420]],
        ),
    }
    text, crops = build(PageSource(None, pages), prof)
    assert text.startswith("# A Small Book\n\nSecond Edition. ISBN 1.\n\n# Part 1: First Things\n")
    assert "## PLATE 1-1. A thing.\n\n![PLATE 1-1. A thing.](images/p0002-plate-1-1.jpeg)" in text
    assert text.rstrip().endswith("Some body text.") and "PART" not in text
    assert crops == [(2, [1.0, 2.0, 3.0, 4.0], "p0002-plate-1-1.jpeg", 0)]


def test_a_transcribed_picture_table_replaces_the_pages_figure() -> None:
    m = profile_mapping()
    m["document"]["raster_tables"] = {
        2: {
            "top": 430,
            "figure": [100, 320, 250, 400],
            "label": "Parts, numbered",
            "title": "CHART 1-1. Parts",
            "header": ["#", "NAME"],
            "rows": [["1", "cortex"], ["2", "medulla"]],
        }
    }
    pages = _pages(line("Lead-in text.", 72, 600), line("After the table.", 72, 150))
    pages[2]["images"] = [[72, 300, 400, 420]]
    text, crops = build(PageSource(None, pages), profile_from_mapping(m))
    assert text.split("ISBN 1.\n\n")[1] == (
        "Lead-in text.\n\n## CHART 1-1. Parts\n\n"
        "![Parts, numbered](images/p0002-parts-numbered.jpeg)\n\n"
        "| # | NAME |\n|---|---|\n| 1 | cortex |\n| 2 | medulla |\n\nAfter the table.\n"
    )
    assert crops == [(2, [97, 317, 253, 403], "p0002-parts-numbered.jpeg", 0)]
