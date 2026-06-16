"""Tests for pagespeak._heading_sanity.

Heuristic demote of Marker-promoted prose-shaped numbered headings.
"""

from __future__ import annotations

from pagespeak.services._cleanup import cleanup_markdown
from pagespeak.services._heading_sanity import (
    demote_prose_heading,
    is_prose_shaped_title,
    is_toc_phantom_heading,
)

# --- is_prose_shaped_title --------------------------------------------------


def test_short_section_title_is_not_prose() -> None:
    assert not is_prose_shaped_title("Introduction")
    assert not is_prose_shaped_title("ARCHITECTURE")
    assert not is_prose_shaped_title("Quick Start")


def test_long_descriptive_title_under_120_chars_is_not_prose() -> None:
    # Real section titles can be moderately long — must not false-positive.
    title = "The Hydraulics System and Its Regulation Under Stress"
    assert len(title) < 120
    assert not is_prose_shaped_title(title)


def test_over_120_chars_is_prose() -> None:
    title = "A" + " word" * 30  # ~150 chars, no internal period
    assert len(title) > 120
    assert is_prose_shaped_title(title)


def test_internal_period_capital_is_prose() -> None:
    # Hallmark of prose: sentence-ending period followed by a capital.
    title = "Closed but capable of opening. At rest the gate is open"
    assert is_prose_shaped_title(title)


def test_internal_period_lowercase_is_not_prose() -> None:
    # Abbreviations like `e.g. foo` shouldn't fire (period followed by
    # lowercase is not a sentence boundary).
    assert not is_prose_shaped_title("Configuration e.g. timeouts")


def test_short_terminal_period_is_not_prose() -> None:
    # Short titles ending in a period (like `1. Open.`) survive — the
    # length threshold (40) keeps them.
    assert not is_prose_shaped_title("Open.")
    assert not is_prose_shaped_title("Why?")


def test_long_terminal_period_is_prose() -> None:
    # Length > 40 AND ending in `.` / `?` / `!` reads as a sentence.
    title = "This is a sentence describing some property here."
    assert len(title) > 40
    assert title.endswith(".")
    assert is_prose_shaped_title(title)


def test_lowercase_first_char_is_prose() -> None:
    # Continuation-shape: starts with lowercase. Real titles capitalize.
    assert is_prose_shaped_title("and the gate closes")
    assert is_prose_shaped_title("the activation gate is closed")


def test_empty_title_is_not_prose() -> None:
    assert not is_prose_shaped_title("")
    assert not is_prose_shaped_title("   ")


def test_non_alpha_first_char_does_not_fire_lowercase_rule() -> None:
    # First char is `(`, not a letter — lowercase rule shouldn't fire.
    assert not is_prose_shaped_title("(Optional) Configuration")


# --- demote_prose_heading ---------------------------------------------------


def test_demote_drops_hashes_keeps_number_prefix() -> None:
    line = (
        "### 1. Closed but capable of opening. At rest the inactivation "
        "gate is open and the activation gate is closed."
    )
    out = demote_prose_heading(line)
    assert not out.lstrip().startswith("#")
    assert out.startswith("1. ")
    assert "Closed but capable of opening." in out


def test_demote_keeps_short_section_heading() -> None:
    assert demote_prose_heading("### 1. Introduction") == "### 1. Introduction"
    assert demote_prose_heading("# 1. ARCHITECTURE") == "# 1. ARCHITECTURE"


def test_demote_keeps_short_terminal_punct() -> None:
    assert demote_prose_heading("### 1. Open.") == "### 1. Open."
    assert demote_prose_heading("### 1. Why?") == "### 1. Why?"


def test_demote_keeps_multipart_numbered_section() -> None:
    # Real subsections survive even with terse titles.
    assert demote_prose_heading("### 1.4.1. Triggers") == "### 1.4.1. Triggers"


def test_demote_ignores_non_heading_line() -> None:
    assert demote_prose_heading("just some prose") == "just some prose"
    assert demote_prose_heading("1. plain numbered list item") == ("1. plain numbered list item")


def test_demote_keeps_short_non_numbered_heading() -> None:
    # Short non-numbered headings (real section titles) are unchanged.
    assert demote_prose_heading("### Introduction") == "### Introduction"
    assert demote_prose_heading("## Quick Start") == "## Quick Start"
    assert demote_prose_heading("### HOW TO TUNE A SNARE") == "### HOW TO TUNE A SNARE"


def test_demote_non_numbered_with_internal_sentence() -> None:
    # non-numbered headings with prose-shape demote too.
    long_unnumbered = "### A long heading with internal. Period boundary"
    assert demote_prose_heading(long_unnumbered) == "A long heading with internal. Period boundary"


def test_demote_lowercase_continuation() -> None:
    assert demote_prose_heading("### 1. and the gate closes") == "1. and the gate closes"


def test_demote_long_title_ending_in_period() -> None:
    line = "### 1. The channel is non-conducting in this state and remains so until reactivation."
    out = demote_prose_heading(line)
    assert not out.lstrip().startswith("#")
    assert out.startswith("1. ")


# --- Orchestrator integration via cleanup_markdown --------------------------


def test_cleanup_demotes_prose_heading_after_promote() -> None:
    # Marker emits a numbered bullet that promote_numbered_heading would turn
    # into a heading. The heuristic catches it post-promotion and demotes.
    raw = (
        "1. Closed but capable of opening. At rest the inactivation gate is "
        "open and the activation gate is closed.\n"
        "\n"
        "next paragraph here.\n"
    )
    out = cleanup_markdown(raw, level="basic")
    # No heading markers on the bullet line.
    bullet_lines = [line for line in out.splitlines() if "Closed but capable of opening" in line]
    assert bullet_lines, "bullet line missing from output"
    assert not any(line.lstrip().startswith("#") for line in bullet_lines)
    # Numeric prefix preserved.
    assert any(line.lstrip().startswith("1. ") for line in bullet_lines)


def test_cleanup_keeps_real_section_heading() -> None:
    # single-dot plaintext is no longer auto-promoted (docling-fix
    # — single-dot in plain text is almost always a list item or quiz answer,
    # not a section heading). Multi-dot is still promoted. Real chapter
    # promotion is the LLM normalize pass's job.
    raw = "1.1. Introduction\n\nbody.\n"
    out = cleanup_markdown(raw, level="basic")
    assert "## 1.1. Introduction" in out


def test_cleanup_demotes_marker_pre_promoted_prose() -> None:
    # Marker sometimes emits the heading shape directly (`### 1. <prose>`)
    # rather than a bullet that promote_numbered_heading would catch. The
    # demote pass must catch this shape too.
    raw = (
        "### 1. Closed but capable of opening. At rest the inactivation gate is "
        "open and the activation gate is closed.\n\nbody.\n"
    )
    out = cleanup_markdown(raw, level="basic")
    assert "### 1. Closed" not in out
    assert "1. Closed but capable of opening." in out


def test_cleanup_preserves_anchors_after_demote() -> None:
    # If a heading line had a page anchor and the heuristic demotes it,
    # the anchor must still appear on a following line so [label](#page-X-Y)
    # cross-refs still resolve to the document position.
    raw = (
        '### <span id="page-7-0"></span>1. Closed but capable of opening. '
        "At rest the inactivation gate is open and the activation gate is "
        "closed.\n\nbody.\n"
    )
    out = cleanup_markdown(raw, level="basic")
    # The line is no longer a heading.
    assert "### 1. Closed" not in out
    # The anchor is still in the document somewhere.
    assert '<span id="page-7-0"></span>' in out


def test_cleanup_aggressive_still_demotes() -> None:
    raw = (
        "### 1. Closed but capable of opening. At rest the inactivation gate is "
        "open and the activation gate is closed.\n\nbody.\n"
    )
    out = cleanup_markdown(raw, level="aggressive")
    assert "### 1. Closed" not in out
    assert "1. Closed but capable of opening." in out


def test_cleanup_does_not_demote_legitimate_subsection() -> None:
    # `1.1. Triggers` is a real subsection. lock_numbered_section_depth
    # re-levels to match the dot count: `1.1` (one dot) → H2. Inputs at
    # H3 are re-leveled DOWN to H2; the legitimate subsection survives,
    # just at the natural depth.
    raw = "### 1.1. Triggers\n\nbody.\n"
    out = cleanup_markdown(raw, level="basic")
    assert "## 1.1. Triggers" in out


# --- is_toc_phantom_heading ---------------------------------------


def test_toc_phantom_p_dot_suffix_drops() -> None:
    """Direct page-suffix shape: `..., p. NN`. Strong signal regardless
    of any prefix."""
    assert is_toc_phantom_heading("20.2. Functional Toolcraft of the Fluidic System, p. 596")
    assert is_toc_phantom_heading("Functional Toolcraft, p. 32")
    assert is_toc_phantom_heading("Foo, p. 8")
    assert is_toc_phantom_heading("Foo Bar, P. 100")  # case-insensitive


def test_toc_phantom_chapter_with_trailing_pagenum() -> None:
    """`Chapter N <title> NN` — Marker-promoted chapter heading from
    the front-matter TOC."""
    assert is_toc_phantom_heading("Chapter 1 Introduction to Widgetry 31")
    assert is_toc_phantom_heading("Chapter 14 Calibration 686")


def test_toc_phantom_numbered_with_trailing_pagenum() -> None:
    """`N.M <title> NN` — Marker-promoted subsection heading from the TOC."""
    assert is_toc_phantom_heading("1.1 Organization of the Device 32")
    assert is_toc_phantom_heading("2.5.7 Bank Account Validation 88")


def test_toc_phantom_keeps_legit_chapter_heading() -> None:
    """`Chapter N` (no title or no trailing page) is real content."""
    assert not is_toc_phantom_heading("Chapter 14")
    assert not is_toc_phantom_heading("Chapter 1 Introduction to Widgetry")


def test_toc_phantom_keeps_legit_numbered_subsection() -> None:
    """`1.1 Foo` (no trailing page number) is real content."""
    assert not is_toc_phantom_heading("1.1 Organization of the Device")
    assert not is_toc_phantom_heading("2.5.7 Bank Account Validation")


def test_toc_phantom_keeps_bare_titles_with_numbers() -> None:
    """Titles without a Chapter/numbered prefix can have trailing
    digits without being TOC entries — false-positive guard.
    `RFC 822`, `Section 100`, etc."""
    assert not is_toc_phantom_heading("RFC 822")
    assert not is_toc_phantom_heading("Section 100")
    assert not is_toc_phantom_heading("IEEE 802.11")


def test_toc_phantom_keeps_normal_section_titles() -> None:
    assert not is_toc_phantom_heading("Introduction")
    assert not is_toc_phantom_heading("Quick Start")
    assert not is_toc_phantom_heading("HOW TO TUNE A SNARE")
    assert not is_toc_phantom_heading("References")


def test_toc_phantom_handles_empty_input() -> None:
    assert not is_toc_phantom_heading("")
    assert not is_toc_phantom_heading("   ")


# --- non-numbered prose demote -------------------------------------


def test_demote_caption_promote_figure() -> None:
    """Marker promotes `Figure 13.24 <caption>` to a heading. The
    splitter then writes a section file. Always demote regardless of
    length — figure captions aren't section content."""
    line = "#### Figure 13.24 Major control inputs to the pump."
    out = demote_prose_heading(line)
    assert out == "Figure 13.24 Major control inputs to the pump."


def test_demote_caption_promote_table() -> None:
    line = "#### Table 4.2 Common connectors and receivers"
    out = demote_prose_heading(line)
    assert out == "Table 4.2 Common connectors and receivers"


def test_demote_caption_promote_short_fig() -> None:
    line = "#### Fig. 7 Housing panel diagram"
    out = demote_prose_heading(line)
    assert out == "Fig. 7 Housing panel diagram"


def test_demote_non_numbered_long_sentence_terminal_period() -> None:
    """`### If you're new to drums, here's the toolcraft of a typical tom.`
    — sentence Marker promoted from running text; must be demoted."""
    line = "### If you're new to drums, here's the toolcraft of a typical tom."
    out = demote_prose_heading(line)
    assert out == "If you're new to drums, here's the toolcraft of a typical tom."


def test_demote_non_numbered_parenthetical_reference() -> None:
    """`### (see Understanding Exercise - Adaptations of the External
    Wiring System ).` — parenthetical reference promoted; demote."""
    line = "### (see Understanding Exercise - Adaptations of the External Wiring System )."
    out = demote_prose_heading(line)
    assert out.startswith("(see Understanding Exercise")


def test_demote_keeps_legit_long_capitalized_section_title() -> None:
    """Real product-manual section titles can be long, capitalized,
    no terminal punctuation, no internal period. Don't demote."""
    line = "## Configuring the Quick-Connect Audio Interface for Multi-Channel Recording"
    out = demote_prose_heading(line)
    assert out == line


def test_demote_keeps_all_caps_section_title() -> None:
    """`## INTRODUCTION TO WIDGETRY AND EQUILIBRIUM PRINCIPLES.` —
    all-caps with terminal period. Looks like prose by length+punct
    but is_upper guard preserves it."""
    line = "## INTRODUCTION TO WIDGETRY AND EQUILIBRIUM PRINCIPLES."
    out = demote_prose_heading(line)
    assert out == line


def test_demote_keeps_short_non_numbered_with_question() -> None:
    # FAQ-style short questions — real headings.
    assert demote_prose_heading("### Why do we tune drums?") == "### Why do we tune drums?"
    assert (
        demote_prose_heading("### How long does it take to tune drums?")
        == "### How long does it take to tune drums?"
    )
