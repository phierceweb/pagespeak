from __future__ import annotations

from pagespeak.services._frontmatter import (
    count_frontmatter_patterns,
    strip_template_frontmatter,
)


def test_count_frontmatter_patterns_zero_for_plain_text() -> None:
    assert count_frontmatter_patterns("Just a normal paragraph.\n# Heading\nbody.") == 0


def test_count_frontmatter_patterns_word_toc_anchor() -> None:
    text = "Some text [Section 1](#_Toc352250146) more text."
    assert count_frontmatter_patterns(text) == 1


def test_count_frontmatter_patterns_revision_history_table() -> None:
    text = "header\n| Date | Version | Description | Author |\n| --- | --- | --- | --- |\nbody"
    assert count_frontmatter_patterns(text) == 1


def test_count_frontmatter_patterns_template_placeholders() -> None:
    text = "<Project Name>\n<Month> <Year>\nVersion <#.#>"
    assert count_frontmatter_patterns(text) >= 1


def test_count_frontmatter_patterns_two_or_more_for_typical_template() -> None:
    text = (
        "<Project Name>\n\n"
        "Revision History\n"
        "| Date | Version | Description | Author |\n"
        "Place latest revisions at top of table.\n\n"
        "[Introduction](#_Toc352250146)\n"
        "Artifact Rationale\n"
    )
    assert count_frontmatter_patterns(text) >= 4


def test_strip_template_frontmatter_drops_when_threshold_met() -> None:
    text = (
        "<Project Name>\n"
        "| Date | Version | Description | Author |\n"
        "[1. Intro](#_Toc352250146)\n"
        "Artifact Rationale\n"
        "\n"
        "# Real Heading\n"
        "Real body content.\n"
    )
    stripped, dropped = strip_template_frontmatter(text)
    assert dropped > 0
    assert stripped.startswith("# Real Heading")
    assert "Real body content." in stripped
    assert "Artifact Rationale" not in stripped
    assert "<Project Name>" not in stripped


def test_strip_template_frontmatter_no_op_when_no_h1() -> None:
    text = "<Project Name>\n[1. Intro](#_Toc1)\nArtifact Rationale\nNo H1 in this doc."
    stripped, dropped = strip_template_frontmatter(text)
    assert dropped == 0
    assert stripped == text


def test_strip_template_frontmatter_no_op_when_below_threshold() -> None:
    text = "Real prose with [a link](#_Toc1).\n\n# First Heading\nBody.\n"
    stripped, dropped = strip_template_frontmatter(text)
    assert dropped == 0
    assert stripped == text


def test_strip_template_frontmatter_no_op_when_h1_at_start() -> None:
    text = "# First Heading\nbody\n"
    stripped, dropped = strip_template_frontmatter(text)
    assert dropped == 0
    assert stripped == text
