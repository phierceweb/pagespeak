from __future__ import annotations

import pytest

from pagespeak.backends._docx_quality import (
    demote_nonsection_h1,
    emit_heading,
    strip_heading_emphasis,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("**Definition of a widget**", "Definition of a widget"),
        ("***See Text Box: Fasteners***", "See Text Box: Fasteners"),
        ("**HYDRAULICS SYSTEM: PUMP **", "HYDRAULICS SYSTEM: PUMP"),
        ("plain title", "plain title"),
        ("**T****oolcraft** position", "Toolcraft position"),
    ],
)
def test_strip_heading_emphasis(raw: str, expected: str) -> None:
    assert strip_heading_emphasis(raw) == expected


def test_emit_heading_kept_strips_emphasis() -> None:
    add, made = emit_heading("#", "**Load transfer**")
    assert add == ["# Load transfer", ""]
    assert made is True


def test_emit_heading_empty_text_skipped() -> None:
    assert emit_heading("#", "   ") == ([], False)
    assert emit_heading("##", "****") == ([], False)


@pytest.mark.parametrize(
    "text",
    [
        # The de-heuristic contract: a structure-faithful reader does
        # NOT decide a heading is "junk" from its wording. If Word's
        # structure made this a heading slot, it is emitted as one —
        # a sentence, a `:`-lead-in, a reaction arrow, a link, a fill
        # blank, a >120-char line: ALL become headings now. (Cleanup
        # of a genuinely messy source is the user's call, not the
        # converter's, and never phrase-based.)
        "Generally you will find it on the outer surface of the frame.",
        "What component is responsible for actuation?",
        "Before you begin, make sure you have mastered the following topics:",
        "In the return line, when the valve and pump are present, the following occurs:",
        "PIPELINE ⇒ output + fuel",
        "[PLAYLIST](https://youtu.be/abc) for this content",
        (
            "The rest of the inflow is balanced by other positive pressure "
            "moving out into the channels, then into the reservoir (line A and line B)"
        ),
    ],
)
def test_emit_heading_is_faithful_no_content_demotion(text: str) -> None:
    # Always a heading (never demoted by wording); the only transform
    # is the general emphasis-strip.
    add, made = emit_heading("#", text)
    assert made is True
    assert add == [f"# {strip_heading_emphasis(text)}", ""]


def test_emit_heading_strips_emphasis_only_no_phrase_logic() -> None:
    # The ONLY transform is emphasis-stripping (general MD hygiene).
    add, made = emit_heading("##", "***Before you begin***")
    assert add == ["## Before you begin", ""]
    assert made is True


def test_demote_nonsection_h1_demotes_label_run_keeps_real_section() -> None:
    # A run of bodyless label H1s, then a real section with a list body.
    # demote_nonsection_h1 is STRUCTURAL (body presence), not phrase.
    lines = [
        "# TCV",
        "",
        "# Reservoir",
        "",
        "# Optical functions; units do the following:",
        "",
        "1. Process input stream",
        "",
    ]
    out = demote_nonsection_h1(lines, protected=set())
    assert out[0] == "TCV"
    assert out[2] == "Reservoir"
    assert out[4] == "# Optical functions; units do the following:"


def test_demote_nonsection_h1_image_only_is_not_body() -> None:
    lines = [
        "# sprockets fittings",
        "",
        "![](images/image11.png)",
        "",
        "# Power conversion",
        "",
        "1. Description: process route",
    ]
    out = demote_nonsection_h1(lines, protected=set())
    assert out[0] == "sprockets fittings"
    assert out[4] == "# Power conversion"


def test_demote_nonsection_h1_protects_promoted_title() -> None:
    # The promoted document title is legitimately bodyless (content
    # starts after the next heading) — protected by index.
    lines = [
        "# Optical Widgetry (Chapters 18, 19)",
        "",
        "# Before you begin:",
        "",
        "1. Toolcraft review",
    ]
    out = demote_nonsection_h1(lines, protected={0})
    assert out[0] == "# Optical Widgetry (Chapters 18, 19)"
    assert out[2] == "# Before you begin:"


def test_demote_nonsection_h1_trailing_shell_demoted() -> None:
    lines = ["# A", "", "1. real body", "", "# Trailing label", ""]
    out = demote_nonsection_h1(lines, protected=set())
    assert out[0] == "# A"
    assert out[4] == "Trailing label"


def test_demote_nonsection_h1_list_continuation_demoted() -> None:
    # A fragment heading interrupting an outline that resumes at `2.`
    # -> the heading did not start that body (structural signal).
    lines = [
        "# sprockets fittings",
        "",
        "    2. Filtration follows:",
        "",
        "# Real section",
        "",
        "1. fresh body",
    ]
    out = demote_nonsection_h1(lines, protected=set())
    assert out[0] == "sprockets fittings"
    assert out[4] == "# Real section"


def test_demote_nonsection_h1_first_item_one_is_real_section() -> None:
    lines = ["# Optical functions", "", "1. Process", "", "2. Regulate"]
    out = demote_nonsection_h1(lines, protected=set())
    assert out[0] == "# Optical functions"
