"""Tests for pagespeak.services._split_parse."""

from __future__ import annotations

from pagespeak.services._split_parse import _parse_sections

_TITLE_INTEGER_DOC = [
    "# Site Admin",
    "## Using the Dashboard",
    "Dashboard body.",
    "## 404 + Redirect Rules",
    "Overview body.",
    "### 404 ERRORS",
    "404 body.",
    "### REDIRECT RULES",
    "Redirect body.",
    "## 404 Handling With the Admin App",
    "Handling body.",
]


def test_bare_integer_outside_any_numbering_is_title_text() -> None:
    """`## 404 + Redirect Rules` in an unnumbered manual is not section 404:
    nothing else in the document is numbered 403, 405 or 404.x."""
    sections = {s.title: s for s in _parse_sections(_TITLE_INTEGER_DOC, min_level=1)}
    for line in (
        "## 404 + Redirect Rules",
        "### 404 ERRORS",
        "## 404 Handling With the Admin App",
    ):
        title = line.lstrip("# ")
        assert title in sections, f"{title!r} lost its leading integer"
        assert sections[title].number is None
        assert sections[title].heading_line == line
    assert sections["404 ERRORS"].parent is sections["404 + Redirect Rules"]


def test_bare_integer_outside_numbering_is_not_a_section_in_numbered_mode() -> None:
    lines = [
        "# 1 Introduction",
        "Intro body.",
        "## 1.1 Background",
        "Background body.",
        "### 404 ERRORS",
        "404 body.",
        "# 2 Methods",
        "Methods body.",
    ]
    sections = _parse_sections(lines, min_level=None)
    assert [s.number for s in sections] == ["1", "1.1", "2"]
    assert "### 404 ERRORS" in sections[1].content_lines


def test_bare_integer_in_a_numbering_sequence_stays_numbered() -> None:
    """Siblings, a dotted child, a `Chapter N` neighbour, or a sequence Marker
    spread across levels each corroborate the number."""
    cases = [
        (["# 1 Safety", "a", "# 2 Description", "b"], ["1", "2"]),
        (["# 7 Results", "a", "## 7.1 Data", "b"], ["7", "7.1"]),
        (["### Chapter 3 Setup", "a", "### 4 Wiring", "b"], ["3", "4"]),
        (["### 5 Remove", "a", "# 3 RESULTS", "b", "### 4 Insert", "c"], ["5", "3", "4"]),
    ]
    for lines, numbers in cases:
        for min_level in (None, 1):
            got = [s.number for s in _parse_sections(lines, min_level=min_level)]
            assert got == numbers, (lines, min_level)


def test_dotted_single_number_needs_no_corroboration() -> None:
    """`# 2. INSTALLATION` carries its own section-number punctuation."""
    sections = _parse_sections(["# 2. INSTALLATION", "Body."], min_level=None)
    assert [(s.number, s.title) for s in sections] == [("2", "INSTALLATION")]


def test_image_only_preamble_folds_into_first_section() -> None:
    """A preamble with no prose (a cover logo) must not become its own
    retrievable section — it folds into the first real section instead."""
    lines = [
        "![Vendor logo, decorative.](images/logo.jpeg)",
        "",
        "# Setup",
        "Setup body text.",
    ]
    sections = _parse_sections(lines, min_level=1)
    assert [s.title for s in sections] == ["Setup"]
    assert any("logo.jpeg" in line for line in sections[0].content_lines)


def test_prose_preamble_still_becomes_front_matter() -> None:
    """A preamble carrying real prose keeps its own Front Matter section."""
    lines = [
        "**Title:** Widget Guide",
        "![Cover art.](images/cover.jpeg)",
        "",
        "# Setup",
        "Setup body text.",
    ]
    sections = _parse_sections(lines, min_level=1)
    assert [s.title for s in sections] == ["Front Matter", "Setup"]
    joined = "\n".join(sections[0].content_lines)
    assert "**Title:** Widget Guide" in joined and "cover.jpeg" in joined


def test_headless_document_becomes_one_section() -> None:
    sections = _parse_sections(["Body text.", "", "1. Step one.", "   1. Detail."], min_level=1)
    assert [s.title for s in sections] == ["Front Matter"]
    assert "   1. Detail." in sections[0].content_lines


def test_headless_decoration_only_yields_no_section() -> None:
    assert _parse_sections(["![](images/logo.png)", "[ ]"], min_level=1) == []


def test_link_artifact_only_preamble_folds() -> None:
    """Empty-link debris (`[ ]`) is not prose; alone with images it folds."""
    lines = [
        "[ ]",
        "![Logo.](images/logo.png)",
        "",
        "# Intro",
        "Intro body text.",
    ]
    sections = _parse_sections(lines, min_level=1)
    assert [s.title for s in sections] == ["Intro"]
    assert any("logo.png" in line for line in sections[0].content_lines)


_AUTHORED_DOC = [
    "# Guide",
    "Guide body.",
    "## 5.1 Thing",
    "Thing body.",
    "### 5.1.2 Sub",
    "Sub body.",
]

_CHAPTER_DOC = [
    "# Book",
    "Book body.",
    "## Chapter 2 Gears",
    "Gears body.",
    "## 2.1 Teeth",
    "Teeth body.",
]


def _by_title(lines: list[str], **kwargs: object) -> dict[str, object]:
    return {s.title: s for s in _parse_sections(lines, **kwargs)}  # type: ignore[arg-type]


def test_parse_sections_authored_parents_by_level() -> None:
    sections = _by_title(_AUTHORED_DOC, min_level=1, authored_levels=True)
    thing, sub = sections["5.1 Thing"], sections["5.1.2 Sub"]
    assert thing.number is None
    assert thing.parent.title == "Guide"
    assert sub.number is None
    assert sub.parent.title == "5.1 Thing"


def test_parse_sections_authored_same_level_numbers_are_siblings() -> None:
    sections = _by_title(_CHAPTER_DOC, min_level=1, authored_levels=True)
    assert sections["Chapter 2 Gears"].parent.title == "Book"
    assert sections["2.1 Teeth"].parent.title == "Book"


def test_parse_sections_authored_heading_line_verbatim() -> None:
    authored = _by_title(_AUTHORED_DOC, min_level=1, authored_levels=True)
    assert authored["5.1 Thing"].heading_line == "## 5.1 Thing"
    chapter = _by_title(_CHAPTER_DOC, min_level=1, authored_levels=True)
    assert chapter["Chapter 2 Gears"].heading_line == "## Chapter 2 Gears"


def test_parse_sections_authored_min_level_none_finds_no_sections() -> None:
    parsed = _parse_sections(_AUTHORED_DOC, min_level=None, authored_levels=True)
    assert [s for s in parsed if not s.is_preamble] == []


def test_parse_sections_authored_numbered_h1_ancestor_only_below_min_level() -> None:
    lines = ["# 1 Guide", "## 1.1 Part", "Part body."]
    sections = _by_title(lines, min_level=2, authored_levels=True)
    assert sections["1 Guide"].is_ancestor_only is True
    assert sections["1.1 Part"].is_ancestor_only is False
    assert sections["1.1 Part"].parent is sections["1 Guide"]


def test_parse_sections_default_still_numbers() -> None:
    sections = {s.title: s for s in _parse_sections(_AUTHORED_DOC, min_level=1)}
    assert sections["Thing"].number == "5.1"
    assert sections["Thing"].heading_line == "## 5.1. Thing"
