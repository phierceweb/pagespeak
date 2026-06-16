"""Tests for pagespeak._cleanup.

Each per-line transform has its own narrow test. Orchestrator behavior
(level flags, table buffering, blank-line collapsing) is tested via
cleanup_markdown() directly.
"""

from __future__ import annotations

from pagespeak.services._cleanup import (
    build_anchor_map,
    cleanup_markdown,
    collapse_multi_space,
    collapse_shattered_emphasis,
    decode_html_entities,
    dedupe_consecutive_headings,
    demote_front_matter_headings,
    heading_slug,
    is_image_only_line,
    lock_numbered_section_depth,
    normalize_list_bullet,
    normalize_table_block,
    promote_numbered_heading,
    remap_page_refs,
    repair_broken_cross_ref,
    strip_garbage_chars,
    strip_html_inline_tags,
    strip_marker_pollution,
    strip_page_refs,
    strip_page_spans,
    unescape_underscores,
)

# --- Per-step unit tests -------------------------------------------------


def test_off_returns_text_unchanged() -> None:
    raw = "Δ\n<i>foo</i>\n  multi  space  \n1.4.1. Heading"
    assert cleanup_markdown(raw, level="off") == raw


def test_decode_html_entities_prose() -> None:
    """Backends leave entities in extracted markdown — decode them so the RAG
    sees the real char."""
    assert decode_html_entities("T3 &lt; 34F &amp; up &gt; 0") == "T3 < 34F & up > 0"
    assert decode_html_entities("non&#x20;breaking") == "non breaking"
    assert decode_html_entities("no entities here") == "no entities here"


def test_decode_html_entities_preserves_fenced_code() -> None:
    """A literal entity inside a code example must survive verbatim."""
    text = "Prose &amp; more.\n```\ncode = a &lt; b\n```\nAfter &gt; 0."
    out = decode_html_entities(text)
    assert "Prose & more." in out
    assert "code = a &lt; b" in out  # preserved inside the fence
    assert "After > 0." in out


def test_collapse_shattered_emphasis_quiz_stem() -> None:
    """The Canvas quiz shatter: `****incorrectly****` → `**incorrectly**`."""
    out = collapse_shattered_emphasis("Which statement ****incorrectly**** describes it?")
    assert out == "Which statement **incorrectly** describes it?"


def test_collapse_shattered_emphasis_marker_doubled_bold() -> None:
    """The Marker shape, incl. 6- and 8-asterisk runs in a table."""
    text = "|  | ****Sales:**** | ******Web:****** | ********Hours******** |"
    out = collapse_shattered_emphasis(text)
    assert out == "|  | **Sales:** | **Web:** | **Hours** |"


def test_collapse_shattered_emphasis_leaves_valid_emphasis() -> None:
    """`**bold**` and `***bold-italic***` (≤3 markers) are never touched."""
    text = "a **bold** and ***bolditalic*** and *italic* stay"
    assert collapse_shattered_emphasis(text) == text


def test_collapse_shattered_emphasis_preserves_hr_line() -> None:
    """A line of only asterisks is a thematic break, not shatter."""
    text = "above\n\n****\n\nbelow"
    assert collapse_shattered_emphasis(text) == text


def test_collapse_shattered_emphasis_preserves_fenced_code() -> None:
    text = "prose ****x****\n```\ncode = a ****b\n```\nmore ****y****"
    out = collapse_shattered_emphasis(text)
    assert "prose **x**" in out
    assert "code = a ****b" in out  # preserved inside the fence
    assert "more **y**" in out


def test_collapse_shattered_emphasis_noop_without_run() -> None:
    assert collapse_shattered_emphasis("plain **bold** text") == "plain **bold** text"


def test_cleanup_markdown_decodes_entities() -> None:
    out = cleanup_markdown("Temperature T3 &lt; 34F and A &amp; B.")
    assert "T3 < 34F" in out
    assert "A & B" in out
    assert "&lt;" not in out and "&amp;" not in out


def test_reader_clean_nested_list_survives_cleanup() -> None:
    # Detect→correct invariant at the cleanup level: the python-docx
    # reader's clean headed nested list has no flattened-outline
    # fingerprint, so cleanup must neither re-promote it into a
    # heading cascade (promote_outline no-op) nor flatten its
    # structural indentation (per-line indent preservation).
    raw = (
        "# Steps of transfer\n"
        "\n"
        "1. **External transfer **\n"
        "  1. **Primary intake** (loading)\n"
        "  2. Exchange between buffer and downstream reservoir\n"
        "2. **Internal transfer**\n"
        "  1. Local processing in modules\n"
        "3. Payload transport in the loop\n"
    )
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    assert "# Steps of transfer" in lines  # real heading kept
    assert "  1. **Primary intake** (loading)" in lines  # indent kept
    assert "  1. Local processing in modules" in lines  # indent kept
    assert not any(ln.startswith("##") for ln in lines)  # no heading cascade
    assert not any(ln.lstrip().startswith("# 1.") for ln in lines)  # no promote


def test_cleanup_keeps_blank_line_between_adjacent_tables() -> None:
    """Two distinct tables separated by a blank line must STAY separated. The
    blank-run dedup must not treat the blank *before* a table and the blank
    *after* it as consecutive — the table rows between them have to reset the
    run. Otherwise the separator is dropped and a 2-col table glues onto a
    wider one, which a markdown viewer renders as a single table and truncates
    the second to the first's column count. Regression: a 2-col-then-wide-table
    case — a 2-col table glued to a 9-col table,
    making the second table's data look wiped on screen."""
    text = (
        "Intro paragraph before the tables.\n"
        "\n"
        "| Condition | Solution |\n"
        "| --- | --- |\n"
        "| Lack of humidity. | Increase the dial. |\n"
        "\n"
        "| TABLE 3 | a | b | c |\n"
        "| --- | --- | --- | --- |\n"
        "| Dial | 1 | 10% | 20% |\n"
    )
    lines = cleanup_markdown(text, level="basic").splitlines()
    i = next(k for k, ln in enumerate(lines) if "TABLE 3" in ln)
    assert lines[i - 1].strip() == "", (
        f"adjacent tables glued — line before TABLE 3 is {lines[i - 1]!r}"
    )


def test_demote_front_matter_headings_book() -> None:
    """In a multi-chapter book, headings before the first chapter (first H1)
    are title-page / copyright / TOC boilerplate — demote them; body kept."""
    text = (
        "## Quick Start Guide\n"
        "## JANE Q AUTHOR\n"
        "### 1 Introduction 31\n"
        "# 1 Introduction to Widgetry\n"
        "## The Module\n"
        "## Equilibrium\n"
        "## Feedback Loops\n"
        "Real body content of the chapter.\n"
        "# 2 Module Assembly\n"
        "## Pipeline\n"
        "## Staging Cycle\n"
        "More real content here.\n"
        "# 3 Boundary Transfer\n"
        "## Diffusion\n"
        "Even more content here.\n"
    )
    out, n = demote_front_matter_headings(text)
    lines = out.splitlines()
    assert n == 3
    assert "Quick Start Guide" in lines and "## Quick Start Guide" not in lines
    assert "JANE Q AUTHOR" in lines and "## JANE Q AUTHOR" not in lines
    assert "1 Introduction 31" in lines  # the TOC entry demoted too
    assert "# 1 Introduction to Widgetry" in lines  # first chapter kept
    assert "## The Module" in lines and "## Pipeline" in lines  # body kept


def test_demote_front_matter_noop_not_a_book() -> None:
    """Fewer than 3 H1 chapters → not a book; pre-H1 headings are real sections."""
    text = "## Overview\n## Setup\n# The One Section\n## Sub\ncontent\n"
    out, n = demote_front_matter_headings(text)
    assert n == 0
    assert out == text


def test_demote_front_matter_noop_body_starts_at_h1() -> None:
    """No headings before the first H1 → nothing is front matter."""
    text = "# 1 One\n## a\nc\n# 2 Two\n## b\nc\n# 3 Three\nc\n"
    out, n = demote_front_matter_headings(text)
    assert n == 0
    assert out == text


def test_demote_front_matter_noop_pre_h1_majority() -> None:
    """If most headings precede the first H1, the body isn't H1-led — no-op,
    so a doc that merely opens with several sections isn't gutted."""
    text = (
        "## a\n## b\n## c\n## d\n## e\n## f\n## g\n"  # 7 before
        "# 1 One\nc\n# 2 Two\nc\n# 3 Three\nc\n"  # 3 H1 → 7/10 = 70%
    )
    out, n = demote_front_matter_headings(text)
    assert n == 0
    assert out == text


# --- TOC-outline heading demote (a book's detailed table of contents) ---


def test_demote_toc_outline_headings_book() -> None:
    """A book's detailed Contents lists each chapter heading above bulleted
    `- N.N <title> <page>` section lines. Those are TOC headings — demote
    them. A real chapter heading (prose body) is kept untouched."""
    from pagespeak.services._cleanup import demote_toc_outline_headings

    text = (
        "# Chapter 1\n"
        "Introduction to the Subject 1\n"
        "- 1.1 Origins of the Field 2\n"
        "- 1.2 Definition of Toolcraft 3\n"
        "# Chapter 2\n"
        "The Module 23\n"
        "- 2.1 The Study of Modules 24\n"
        "- 2.3 Plasma Membrane 30\n"
        "# Chapter 1 Introduction to the Subject\n"
        "Real prose body content for the actual first chapter.\n"
        "# Some Real Chapter\n"
        "More real prose content here.\n"
    )
    out, n = demote_toc_outline_headings(text)
    lines = out.splitlines()
    assert n == 2  # the two TOC chapter headings
    assert "# Chapter 1" not in lines  # TOC heading demoted...
    assert "Chapter 1" in lines  # ...to plain text
    assert "# Chapter 2" not in lines
    assert "The Module 23" in lines  # its body preserved as prose
    assert "- 1.1 Origins of the Field 2" in lines  # TOC list kept as body
    assert "# Chapter 1 Introduction to the Subject" in lines  # real chapter kept
    assert "# Some Real Chapter" in lines  # prose-bodied heading kept


def test_demote_toc_outline_noop_prose_body() -> None:
    """A book heading whose body is prose (no section-number TOC list) is a
    real section — never demoted, even though the doc is a book."""
    from pagespeak.services._cleanup import demote_toc_outline_headings

    text = (
        "# Chapter 1\n"
        "This chapter introduces toolcraft with several sentences of prose.\n"
        "# Chapter 2\n"
        "The second chapter continues with more real prose content here.\n"
        "# Chapter 3\n"
        "A third chapter, also prose, with no contents listing at all.\n"
    )
    out, n = demote_toc_outline_headings(text)
    assert n == 0
    assert out == text


def test_demote_toc_outline_noop_not_a_book() -> None:
    """Fewer than 3 H1s → not a book; a section-number list under a heading
    isn't assumed to be a TOC (could be a manual's real numbered list)."""
    from pagespeak.services._cleanup import demote_toc_outline_headings

    text = "# Only Chapter\n- 1.1 First Topic 2\n- 1.2 Second Topic 3\nbody\n"
    out, n = demote_toc_outline_headings(text)
    assert n == 0
    assert out == text


def test_demote_toc_outline_noop_single_toc_line() -> None:
    """One section-number line under a heading is below the >=2 threshold —
    not enough signal to call it a TOC heading."""
    from pagespeak.services._cleanup import demote_toc_outline_headings

    text = (
        "# Chapter 1\n"
        "- 1.1 History 2\n"
        "Then real prose about the history of toolcraft follows here.\n"
        "# Chapter 2\nprose\n# Chapter 3\nprose\n"
    )
    out, n = demote_toc_outline_headings(text)
    assert n == 0
    assert out == text


def test_strips_garbage_chars_basic_keeps_unicode() -> None:
    # Basic mode only strips control chars; real typography survives.
    assert strip_garbage_chars("Saffron House, 6–10 Kirby Street") == (
        "Saffron House, 6–10 Kirby Street"
    )
    assert strip_garbage_chars("© 2025 ®™ smart’quotes") == "© 2025 ®™ smart’quotes"
    # Control chars are stripped.
    assert strip_garbage_chars("foo\x07bar") == "foobar"


def test_strips_garbage_chars_aggressive_strips_non_ascii() -> None:
    # Aggressive matches the strict ASCII filter.
    assert strip_garbage_chars("normal Δ text", aggressive=True) == "normal  text"
    assert strip_garbage_chars("6–10 Kirby", aggressive=True) == "610 Kirby"


def test_strips_html_tags() -> None:
    assert strip_html_inline_tags("<i>foo</i>") == "foo"
    assert strip_html_inline_tags("<B>bar</B>") == "bar"
    assert strip_html_inline_tags("<strong>baz</strong>") == "baz"


def test_collapses_multi_space() -> None:
    assert collapse_multi_space("a   b") == "a b"
    assert collapse_multi_space("a b") == "a b"


def test_single_dot_plaintext_is_not_promoted() -> None:
    # single-dot plaintext patterns are almost always list items,
    # quiz answers, or procedural steps — not section headings. They
    # stay as plaintext; the LLM heading-normalize pass handles real
    # H1 chapter promotion. Multi-dot patterns are still promoted.
    assert promote_numbered_heading("1. ARCHITECTURE") == "1. ARCHITECTURE"
    assert (
        promote_numbered_heading("1. Synthesis: Provides a place for reactions")
        == "1. Synthesis: Provides a place for reactions"
    )
    assert (
        promote_numbered_heading("5. Which eye muscle moves the eye medially?")
        == "5. Which eye muscle moves the eye medially?"
    )


def test_promotes_numbered_heading_depth_2() -> None:
    # Multi-dot patterns are unambiguously hierarchical → still promoted.
    # Note `HEADING_NUM_RE` requires a trailing period on the numeric prefix.
    assert promote_numbered_heading("1.1. Foo") == "## 1.1. Foo"


def test_promotes_numbered_heading_depth_3() -> None:
    assert promote_numbered_heading("1.4.1. Triggers") == "### 1.4.1. Triggers"


def test_promotes_numbered_heading_caps_at_six() -> None:
    assert promote_numbered_heading("1.2.3.4.5.6.7. Deep") == "###### 1.2.3.4.5.6.7. Deep"


def test_keeps_existing_hashed_heading() -> None:
    assert promote_numbered_heading("## 1.1. STACK") == "## 1.1. STACK"


def test_keeps_non_heading_text() -> None:
    assert promote_numbered_heading("just some prose") == "just some prose"


def test_does_not_promote_number_without_trailing_period() -> None:
    # Copyright-page printing sequence — no period after "10", so not a heading.
    assert promote_numbered_heading("10 9 8 7 6 5 4 3 2 1") == "10 9 8 7 6 5 4 3 2 1"
    # Sentences that happen to start with a digit shouldn't be promoted.
    assert promote_numbered_heading("10 cats sat on the mat") == "10 cats sat on the mat"


# --- deterministic structural promote: numbered-section depth lock ---


# --- TOC-phantom heading demote ---


def test_demote_toc_phantom_with_body_match() -> None:
    """TOC entry with page-num suffix + matching body heading → demote."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## 1.1 Origins of the Field 2\n\n## 1.1 Origins of the Field\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "1.1 Origins of the Field 2\n\n## 1.1 Origins of the Field\n"


def test_demote_toc_phantom_no_body_match_preserves() -> None:
    """Heading with trailing digit but no body match → preserve (signal 2 protection)."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## Section 2020\n\nsome body text\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_body_only_preserves() -> None:
    """Body heading with no TOC entry → preserve."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## 1.1 Origins of the Field\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_multiple_toc_entries() -> None:
    """Brief + Detailed Contents both pointing at same body heading → demote both."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## 1.1 History 2\n\n## 1.1 History 2\n\n## 1.1 History\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 2
    assert out == "1.1 History 2\n\n1.1 History 2\n\n## 1.1 History\n"


def test_demote_toc_phantom_multi_digit_pagenum() -> None:
    """Page number can be 1-4 digits."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## 14.3 Signal Pulses 412\n\n## 14.3 Signal Pulses\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "14.3 Signal Pulses 412\n\n## 14.3 Signal Pulses\n"


def test_demote_toc_phantom_non_numbered() -> None:
    """Non-numbered TOC entries also fire when signal 2 matches."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## Introduction 5\n\n## Introduction\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "Introduction 5\n\n## Introduction\n"


def test_demote_toc_phantom_bullet_list_immune() -> None:
    """Bullet items with page numbers are not headings; preserved unchanged."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "- 1.1 Origins of the Field 2\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_no_suffix_unaffected() -> None:
    """A heading whose text matches a later heading but lacks a page suffix
    on EITHER side is not a phantom — preserved verbatim."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## 1.1 History\n\n## 1.1 History\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_five_digit_number_preserves() -> None:
    """5+ digit trailing number is unlikely to be a page number; don't fire."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## Section 12345\n\n## Section\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_preserves_depth_of_body_heading() -> None:
    """When demoting, the body heading's depth marker is untouched."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "### 1.2b Gross Toolcraft 4\n\n### 1.2b Gross Toolcraft\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "1.2b Gross Toolcraft 4\n\n### 1.2b Gross Toolcraft\n"


def test_demote_toc_phantom_numbering_insensitive_twin() -> None:
    """The dominant textbook case. The front-matter TOC prints
    `Organization of the Body 32` (no section number); the body heading
    is `## 1.1 Organization of the Body` (numbered, no page num). The
    match key strips BOTH the page number and the leading `1.1`
    section-number prefix, so the TOC line is recognised and demoted
    while the real numbered heading is kept untouched."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = (
        "#### Organization of the Body 32\n\n"
        "blurb line\n\n"
        "## 1.1 Organization of the Body\n\n"
        "Real section body content.\n"
    )
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert "#### Organization of the Body 32" not in out  # TOC demoted
    assert "Organization of the Body 32" in out  # text preserved as prose
    assert "## 1.1 Organization of the Body" in out  # real heading kept


def test_demote_toc_phantom_case_insensitive_twin() -> None:
    """Match key is casefolded — a SHOUTED TOC entry matches its
    title-case real heading twin."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## MODULE STRUCTURE 59\n\n## 2.1 Module Structure\n\nBody.\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert "## MODULE STRUCTURE 59" not in out
    assert "## 2.1 Module Structure" in out


def test_demote_toc_phantom_no_twin_still_preserved() -> None:
    """Safety unchanged: a page-numbered heading with NO same-core clean
    twin elsewhere is NOT demoted (could be a real heading that happens
    to end in a number)."""
    from pagespeak.services._cleanup import demote_toc_phantom_headings

    text = "## Appendix Table 7\n\nsome content\n\n## Glossary\n\nmore\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


# --- strip_emphasis_from_heading ---


def test_strip_emphasis_strips_leading_bold() -> None:
    """Marker often leaks `**` from PDF bold style into heading text."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    assert strip_emphasis_from_heading("# **2. Callouts") == "# 2. Callouts"
    assert (
        strip_emphasis_from_heading("## **Important Safety Instructions")
        == "## Important Safety Instructions"
    )
    assert strip_emphasis_from_heading("### **1.1.1. API") == "### 1.1.1. API"


def test_strip_emphasis_strips_trailing_and_middle_bold() -> None:
    """Strip `**` anywhere in heading text — markdown headings don't need bold."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    assert (
        strip_emphasis_from_heading("## Section title with **bold** in middle")
        == "## Section title with bold in middle"
    )
    assert strip_emphasis_from_heading("## Title**") == "## Title"


def test_strip_emphasis_preserves_clean_headings() -> None:
    """No `**` in input → unchanged."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    assert strip_emphasis_from_heading("# 1.1 Origins of the Field") == "# 1.1 Origins of the Field"


def test_strip_emphasis_only_affects_headings() -> None:
    """Body text with bold passes through unchanged — only `#`-prefixed lines."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    assert (
        strip_emphasis_from_heading("This is **bold** body text.") == "This is **bold** body text."
    )
    assert strip_emphasis_from_heading("- **list item with bold**") == "- **list item with bold**"


def test_strip_emphasis_handles_underscore_emphasis() -> None:
    """`__` is another markdown bold form; also strip from heading lines."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    assert strip_emphasis_from_heading("## __Title__") == "## Title"


def test_strip_emphasis_collapses_resulting_whitespace() -> None:
    """When `**` is stripped from the middle, collapse the gap."""
    from pagespeak.services._cleanup import strip_emphasis_from_heading

    # `## ** Title **` → `##  Title ` → `## Title` after whitespace collapse
    assert strip_emphasis_from_heading("## ** Title **") == "## Title"


# --- demote_recurring_scaffold_headings ---


def test_demote_recurring_keeps_largest_body() -> None:
    """3+ occurrences of same heading text → keep largest body, demote others."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    # The middle occurrence's body must be substantive (well over the
    # ~80-non-whitespace-char empty-section floor); the other two are
    # stubs → exactly 1 substantive → keep the real one, demote the rest.
    long_body = (
        "This is the real section with substantial prose body content. "
        "It contains multiple sentences across several paragraphs and is "
        "clearly the body of the actual section, not a scaffold reference. "
    ) * 5
    text = (
        "## Outline\n## 1.1 Foo\n- bullet\n"
        f"## Body\n## 1.1 Foo\n{long_body}\n"
        "## Summary\n## 1.1 Foo\n- key point\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    assert count == 2  # The two short-body occurrences demoted
    # The middle occurrence (largest body) keeps its `##`
    assert out.count("## 1.1 Foo") == 1
    assert "1.1 Foo\n- bullet" in out  # First was demoted
    assert "1.1 Foo\n- key point" in out  # Last was demoted


def test_demote_recurring_two_occurrences_unaffected() -> None:
    """Only 2 occurrences → out of scope (threshold is 3)."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    text = "## Foo\nbody\n## Foo\nother body\n"
    out, count = demote_recurring_scaffold_headings(text)
    assert count == 0
    assert out == text


def test_demote_recurring_single_occurrence_unaffected() -> None:
    """A unique heading is never affected."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    text = "## Foo\nbody\n## Bar\nother\n"
    out, count = demote_recurring_scaffold_headings(text)
    assert count == 0
    assert out == text


def test_demote_recurring_all_short_demotes_all() -> None:
    """When ALL occurrences have short bodies, all are scaffold — demote all."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    text = (
        "## In This Chapter\n- item\n"
        "## Body\n## In This Chapter\n- other item\n"
        "## More\n## In This Chapter\n- third item\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    assert count == 3
    assert "## In This Chapter" not in out
    assert "In This Chapter\n- item" in out


def test_demote_recurring_preserves_heading_marker_on_kept() -> None:
    """The kept occurrence (largest body) retains its original heading marker."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    long_body = "Real prose. " * 100  # >> threshold
    text = f"### Foo\nshort\n### Foo\n{long_body}\n### Foo\nshort too\n"
    out, count = demote_recurring_scaffold_headings(text)
    assert count == 2
    # The middle occurrence stays as `### Foo`
    assert "### Foo" in out
    # Only ONE `### Foo` remains (the others demoted)
    assert out.count("### Foo") == 1


# --- per-instance recurring section protection ---


def test_demote_recurring_per_instance_with_substantial_bodies_keeps_all() -> None:
    """When 3+ occurrences are ALL substantive (each carries a real
    section body), they're per-instance recurring sections — keep all.
    2+ substantive → not scaffold. No size-similarity / ratio needed.

    Models a film-stock-catalog case: ``### Exposure Indexes and Filters``
    repeated per film, each with different exposure data per film.
    """
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    body_a = "Tungsten EI 500. Filter values vary by stock. " * 30  # ~1500 chars
    body_b = "Daylight EI 250. Use #85 with care. " * 30  # ~1100 chars
    body_c = "Tungsten EI 100. Different filter mix entirely. " * 30  # ~1500 chars
    text = (
        f"## Film A\n### Exposure Indexes\n{body_a}\n"
        f"## Film B\n### Exposure Indexes\n{body_b}\n"
        f"## Film C\n### Exposure Indexes\n{body_c}\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    # 3 substantive occurrences → per-instance pattern → keep all
    assert count == 0
    assert out.count("### Exposure Indexes") == 3


def test_demote_recurring_clear_outlier_demotes_scaffold() -> None:
    """Exactly 1 substantive occurrence + stub copies → keep the real
    section, demote the stubs. Models widgetry's Outline/Body/Summary
    triple (Body is the only substantive one)."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    long_body = "Real section content. " * 100  # ~2200 chars
    text = (
        "## Outline\n### 1.1 Section\n- short bullet\n"
        f"## Body\n### 1.1 Section\n{long_body}\n"
        "## Summary\n### 1.1 Section\n- short recap\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    # 1 substantive (the long Body) + 2 stubs → keep Body, demote stubs
    assert count == 2
    assert out.count("### 1.1 Section") == 1


def test_demote_recurring_varied_sizes_all_substantive_keeps_all() -> None:
    """Bodies vary widely in size but every occurrence is substantive
    (each well over the empty-section floor). 3 substantive →
    per-instance recurring sections → keep all. No ratio: a real
    section is a real section regardless of how big its siblings are."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    body_a = "Real section A content. " * 40  # ~960 chars
    body_b = "Section B content here. " * 25  # ~600 chars
    body_c = "Third section C content. " * 30  # ~750 chars
    text = (
        f"## A\n### Common Title\n{body_a}\n"
        f"## B\n### Common Title\n{body_b}\n"
        f"## C\n### Common Title\n{body_c}\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    # 3 substantive → keep all (the max/second<3x ratio is gone)
    assert count == 0
    assert out.count("### Common Title") == 3


def test_demote_recurring_two_substantive_one_stub_keeps_all() -> None:
    """Two occurrences carry real section bodies (one huge, one a short
    paragraph) and one is an empty stub. 2+ substantive → per-instance
    recurring sections → keep ALL (the lone stub rides along, harmless):
    a heading with 2 genuinely-bodied occurrences is per-instance content,
    not scaffold."""
    from pagespeak.services._cleanup import demote_recurring_scaffold_headings

    huge_body = "Real chapter content with many sentences. " * 100  # ~4200 chars
    medium_body = "Some real content here, a short paragraph. " * 6  # >80 non-ws
    text = (
        "## A\n### Common\n- stub\n"
        f"## B\n### Common\n{huge_body}\n"
        f"## C\n### Common\n{medium_body}\n"
    )
    out, count = demote_recurring_scaffold_headings(text)
    # B + C both substantive → 2+ → keep all; A's stub is left as-is
    assert count == 0
    assert out.count("### Common") == 3


def test_lock_numbered_section_depth_promotes_h3_to_h2() -> None:
    # docling tags `N.M` sections at H2 by default but some backends use
    # deeper. `N.M` → depth 2 from the dot count.
    assert (
        lock_numbered_section_depth("### 1.1 Definition of Toolcraft")
        == "## 1.1 Definition of Toolcraft"
    )


def test_lock_numbered_section_depth_demotes_h1_to_h2() -> None:
    # Marker occasionally promotes `1.1` to H1; lock back to depth 2.
    assert (
        lock_numbered_section_depth("# 1.1 Definition of Toolcraft")
        == "## 1.1 Definition of Toolcraft"
    )


def test_lock_numbered_section_depth_ignores_single_dot() -> None:
    # Single-dot patterns (`1. Foo`) are list items, not sections.
    # Handled separately by `promote_numbered_heading`'s guard.
    assert lock_numbered_section_depth("# 1. Foo") == "# 1. Foo"


def test_lock_numbered_section_depth_three_dots_is_h3() -> None:
    # `1.1.1` → depth 3, even if the input was at a wrong level.
    assert lock_numbered_section_depth("#### 1.1.1 Sub-sub-section") == "### 1.1.1 Sub-sub-section"


def test_lock_numbered_section_depth_four_dots_is_h4() -> None:
    assert lock_numbered_section_depth("## 1.1.1.1 Deep section") == "#### 1.1.1.1 Deep section"


def test_lock_numbered_section_depth_caps_at_h6() -> None:
    # `1.1.1.1.1.1.1` would naturally be depth 7; cap.
    assert lock_numbered_section_depth("## 1.1.1.1.1.1.1 Deep") == ("###### 1.1.1.1.1.1.1 Deep")


# --- letter-suffixed subsections (e.g. textbook `2.3a`) are one deeper ---


def test_lock_numbered_section_depth_letter_suffix_one_deeper() -> None:
    # `2.3a` is a subsection of `2.3` → one level deeper. `2.3` is depth 2,
    # so `2.3a` is depth 3. (Marker/docling tag both flat at H2.)
    assert (
        lock_numbered_section_depth("## 2.3a Composition of Membranes")
        == "### 2.3a Composition of Membranes"
    )


def test_lock_numbered_section_depth_plain_nm_unchanged_by_letter_rule() -> None:
    # REGRESSION GUARD: a plain `N.M` (no letter) still maps to dot-depth,
    # unaffected by the letter-suffix handling.
    assert lock_numbered_section_depth("# 2.3 Plasma Membrane") == "## 2.3 Plasma Membrane"


def test_lock_numbered_section_depth_letter_suffix_three_part() -> None:
    # `2.3.1a` → 2 dots (depth 3) + letter (one deeper) = depth 4.
    assert lock_numbered_section_depth("## 2.3.1a Detail") == "#### 2.3.1a Detail"


def test_lock_numbered_section_depth_ignores_uppercase_unit() -> None:
    # NO-BREAK GUARD: `3.5GHz` is a measurement, not a subsection — the
    # uppercase letter is not a section letter; leave untouched.
    assert lock_numbered_section_depth("## 3.5GHz Clock Speed") == "## 3.5GHz Clock Speed"


def test_lock_numbered_section_depth_ignores_multichar_suffix() -> None:
    # NO-BREAK GUARD: only a SINGLE lowercase letter is a subsection
    # marker; `2.3ab` (two letters) is not — leave untouched.
    assert lock_numbered_section_depth("## 2.3ab Foo") == "## 2.3ab Foo"


def test_cleanup_markdown_does_not_promote_chapter_keeps_backend_depth() -> None:
    # Cleanup does NOT promote `## Chapter N <title>` — it leaves the
    # heading at the backend-assigned depth (faithful, not guessed). The
    # language-agnostic `N.M` depth lock still applies (`## 1.1` → depth 2).
    raw = (
        "## Chapter 1 Introduction to the Subject\n\n"
        "body text\n\n"
        "## 1.1 Definition of Toolcraft\n\n"
        "more body\n"
    )
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    # NOT promoted to H1 — stays exactly as the backend emitted it.
    assert "## Chapter 1 Introduction to the Subject" in lines
    assert "# Chapter 1 Introduction to the Subject" not in lines
    # Numbered-section depth lock is language-agnostic and still runs.
    assert "## 1.1 Definition of Toolcraft" in lines


def test_normalizes_o_bullet() -> None:
    assert normalize_list_bullet("- o item") == "  - item"


def test_normalizes_alpha_bullet() -> None:
    assert normalize_list_bullet("- a. item") == "  - a) item"


def test_normalizes_roman_bullet() -> None:
    assert normalize_list_bullet("- ii. item") == "    - ii) item"


def test_strips_redundant_ordinal_on_circled_sublabel() -> None:
    """markitdown stacks `1.` on circled ⓐ/ⓑ/ⓒ sub-labels; the redundant
    ordinal is stripped, leaving the circled letter as the sole label."""
    assert normalize_list_bullet("1. ⓐ $-\\frac{5}{7}$") == "ⓐ $-\\frac{5}{7}$"
    assert normalize_list_bullet("3. ⓒ content") == "ⓒ content"
    # a plain numbered list (no circled sub-label) is left untouched
    assert normalize_list_bullet("1. plain item") == "1. plain item"


def test_repairs_broken_cross_ref() -> None:
    assert repair_broken_cross_ref("Se[e Configuration](#page-36-0)") == (
        "[See Configuration](#page-36-0)"
    )


def test_unescapes_underscores() -> None:
    assert unescape_underscores("foo\\_bar") == "foo_bar"


def test_strip_page_spans_removes_span_only() -> None:
    assert strip_page_spans('before<span id="page-1-2"></span>after') == "beforeafter"


# --- strip_marker_pollution (broad heading cleanup) -----------


def test_strip_marker_pollution_removes_span_with_attrs_whitespace() -> None:
    """Stricter regex than `strip_page_spans` — tolerates whitespace
    inside the span tag (Marker occasionally emits `<span id="..." ></span>`)."""
    assert strip_marker_pollution('<span id="page-48-0" ></span>The Module') == "The Module"


def test_strip_marker_pollution_unwraps_well_formed_page_link() -> None:
    assert strip_marker_pollution("[The Hydraulics](#page-26-0) System") == "The Hydraulics System"


def test_strip_marker_pollution_strips_dangling_orphan_link_tail() -> None:
    """Marker emits broken markup like
    `**The Hydraulics](#page-26-0) 15 System` — orphan close-bracket
    + link with no matching `[`. Strip the dangling tail."""
    raw = "**The Hydraulics](#page-26-0) 15 System"
    out = strip_marker_pollution(raw)
    assert "](#page-" not in out
    assert "Hydraulics" in out and "15 System" in out


def test_strip_marker_pollution_preserves_bold_italic() -> None:
    assert (
        strip_marker_pollution("**Chapter 5** Signal Handlers") == "**Chapter 5** Signal Handlers"
    )


def test_cleanup_markdown_strips_polluted_chapter_heading_text() -> None:
    """The rendered markdown gets clean heading text — not
    just the LLM's view. Heading lines processed by
    `cleanup_markdown` should have their TOC-wrapping artifacts stripped."""
    raw = (
        '# <span id="page-462-0"></span>**The Hydraulics](#page-26-0) 15 System: Fluid\n'
        "intro body\n"
        '## <span id="page-23-0"></span>[Chapter 5](#page-23-0) Signal Handlers\n'
        "body\n"
    )
    out = cleanup_markdown(raw, level="basic")
    assert "<span" not in out.split("\n")[0]  # H1 line has no span
    assert "](#page-" not in out.split("\n")[0]  # H1 line has no link tail
    # Cleaned headings retain their semantic content.
    assert "Hydraulics" in out
    assert "Chapter 5 Signal Handlers" in out


def test_cleanup_markdown_leaves_body_cross_refs_intact() -> None:
    """Body cross-refs ARE legitimate navigation — the pollution strip
    must only run on heading lines, not body content."""
    raw = (
        "# Clean Heading\n"
        "See [the next section](#page-50-0) for details.\n"
        '<span id="page-50-0"></span>Some text.\n'
    )
    out = cleanup_markdown(raw, level="basic", cross_refs="keep")
    # Body cross-ref preserved.
    assert "[the next section](#page-50-0)" in out
    # Body span preserved (only aggressive level strips body spans).
    assert '<span id="page-50-0"></span>' in out


def test_is_image_only_line_detects_empty_alt_only() -> None:
    # Empty alt = decoration (bare image with no caption).
    assert is_image_only_line("![](foo.png)")
    assert is_image_only_line("  ![](path/to/img.jpeg)  ")
    # Non-empty alt = content (caption survived diagram pass) — NOT decoration.
    assert not is_image_only_line("![A flowchart.](foo.png)")
    assert not is_image_only_line("text with ![](foo.png) inline")
    assert not is_image_only_line("plain text")


def test_aggressive_keeps_image_with_alt_text() -> None:
    # Regression: introduced alt-text captions; aggressive must NOT
    # drop them as decoration. Empty-alt refs still get dropped.
    raw = "before\n\n![](decoration.png)\n\n![A flowchart.](real-diagram.png)\n\nafter\n"
    out = cleanup_markdown(raw, level="aggressive")
    assert "decoration.png" not in out  # bare image still dropped
    assert "![A flowchart.](real-diagram.png)" in out  # alt-tagged kept


# --- Table normalization -------------------------------------------------


def test_normalizes_table_pads_rows() -> None:
    block = [
        "| col1 | col2 | col3 |",
        "| --- | --- | --- |",
        "| val1 | val2 |",
    ]
    out = normalize_table_block(block)
    assert out[-1] == "| val1 | val2 |  |"


def test_normalizes_table_inserts_divider() -> None:
    block = [
        "| col1 | col2 |",
        "| val1 | val2 |",
    ]
    out = normalize_table_block(block)
    assert "| --- | --- |" in out


def test_promotes_table_title_to_caption() -> None:
    block = [
        "| Some Table Title |",
        "|---|",
        "| col1 | col2 |",
        "| val1 | val2 |",
    ]
    out = normalize_table_block(block)
    assert out[0] == "**Some Table Title**"
    assert out[1] == ""
    assert "| col1 | col2 |" in out


def test_normalize_table_block_empty_returns_empty() -> None:
    assert normalize_table_block([]) == []


# --- Orchestrator: blank-line collapse + level dispatch -----------------


def test_collapses_blank_runs() -> None:
    raw = "line1\n\n\n\nline2\n"
    out = cleanup_markdown(raw, level="basic")
    assert "\n\n\n" not in out
    assert out == "line1\n\nline2\n"


def test_preserves_internal_spacing_strips_leading_trailing() -> None:
    # A mid-line run of spaces (e.g. a space-laid pseudo-diagram) never
    # breaks markdown, so it is preserved verbatim. Only leading
    # whitespace (would mis-form an indented code block) and trailing
    # whitespace (stray hard break) are stripped.
    raw = "   alpha        beta        gamma   \n"
    out = cleanup_markdown(raw, level="basic")
    assert out == "alpha        beta        gamma\n"


def test_preserves_internal_spacing_inside_nested_list() -> None:
    # Structural list indentation is still preserved; the author's
    # internal spacing inside the item body is kept too.
    raw = "- top\n    - child  with   inner   gaps\n"
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    assert "- top" in lines
    # 4-space structural indent preserved AND internal gaps kept.
    assert "    - child  with   inner   gaps" in lines


def test_basic_promotes_numbered_heading() -> None:
    out = cleanup_markdown("1.4.1. Triggers\n", level="basic")
    assert "### 1.4.1. Triggers" in out


def test_basic_keeps_image_only_line() -> None:
    out = cleanup_markdown("![](foo.png)\n", level="basic")
    assert "![](foo.png)" in out


def test_basic_keeps_page_span() -> None:
    out = cleanup_markdown('<span id="page-3-2"></span>text\n', level="basic")
    assert "<span" in out


def test_basic_strips_page_span_from_heading_lines() -> None:
    # Regression: Marker emits `## <span id="page-X-Y"></span>Title`
    # in PDFs with no numbered headings (e.g. a non-numbered manual). The
    # spans were leaking through `cleanup="basic"` into the splitter, which
    # then sanitized them into ugly filenames like
    # `(span id=page-103-0)( - span)Analog Octaver.md` and ugly breadcrumb
    # display text. Basic mode now strips heading-line spans and re-emits
    # them on the line immediately after the heading so cross-refs still
    # resolve to the heading's location (cross_refs="keep" default).
    raw = '## <span id="page-103-0"></span>Analog Octaver\n\nbody paragraph here.\n'
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    assert "## Analog Octaver" in lines
    assert not any(line.startswith("#") and "<span" in line for line in lines)
    heading_idx = lines.index("## Analog Octaver")
    assert lines[heading_idx + 1] == '<span id="page-103-0"></span>'


def test_basic_strips_page_span_from_heading_but_preserves_body_spans() -> None:
    # Regression: the heading strip must be surgical. Body lines
    # keep their `<span id="page-X-Y"></span>` anchors so existing
    # `[label](#page-X-Y)` cross-refs still resolve in basic mode. Heading-
    # line spans are stripped *and* re-emitted on the next line so refs
    # that targeted them also still resolve.
    raw = (
        '## <span id="page-1-0"></span>Heading\n\n'
        '<span id="page-2-0"></span>body anchor preserved\n\n'
        "see [Heading](#page-1-0) for details.\n"
    )
    out = cleanup_markdown(raw, level="basic")
    assert "## Heading" in out
    assert '<span id="page-1-0"></span>' in out
    assert '## <span id="page-1-0"></span>' not in out
    assert '<span id="page-2-0"></span>body anchor preserved' in out
    assert "[Heading](#page-1-0)" in out


def test_basic_strips_multiple_spans_from_heading() -> None:
    raw = '### <span id="page-44-0"></span><span id="page-44-1"></span>CONFIGURATION\n'
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    assert "### CONFIGURATION" in lines
    assert not any(line.startswith("#") and "<span" in line for line in lines)
    heading_idx = lines.index("### CONFIGURATION")
    assert lines[heading_idx + 1] == '<span id="page-44-0"></span>'
    assert lines[heading_idx + 2] == '<span id="page-44-1"></span>'


def test_basic_strips_page_span_at_end_of_heading_line() -> None:
    # Marker can emit the span at the end of the heading depending on layout.
    raw = '## Some Heading <span id="page-44-0"></span>\nbody\n'
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    assert "## Some Heading" in lines
    assert not any(line.startswith("#") and "<span" in line for line in lines)
    heading_idx = lines.index("## Some Heading")
    assert lines[heading_idx + 1] == '<span id="page-44-0"></span>'


def test_basic_strips_page_spans_anywhere_in_heading_and_preserves_each() -> None:
    raw = (
        '## <span id="page-1-0"></span>Foo '
        '<span id="page-2-0"></span>Bar '
        '<span id="page-3-0"></span>\n'
    )
    out = cleanup_markdown(raw, level="basic")
    lines = out.splitlines()
    heading_line = next(
        line
        for line in lines
        if line.startswith("## ") and "<span" not in line and "Foo" in line and "Bar" in line
    )
    heading_idx = lines.index(heading_line)
    assert lines[heading_idx + 1] == '<span id="page-1-0"></span>'
    assert lines[heading_idx + 2] == '<span id="page-2-0"></span>'
    assert lines[heading_idx + 3] == '<span id="page-3-0"></span>'


def test_aggressive_strips_heading_anchor_without_preserving() -> None:
    # In aggressive mode every body span is already stripped, so preserving
    # heading anchors would be inconsistent. Aggressive + cross_refs="strip"
    # is the expected pairing for "drop everything page-anchor-related".
    raw = '### <span id="page-44-0"></span>CONFIGURATION\nbody\n'
    out = cleanup_markdown(raw, level="aggressive")
    assert "### CONFIGURATION" in out
    assert "<span" not in out


def test_basic_with_cross_refs_strip_does_not_preserve_heading_anchor() -> None:
    # cross_refs="strip" drops the [label](#page-X-Y) refs, so the anchor
    # has nothing to resolve. Don't bother re-emitting it.
    raw = '## <span id="page-1-0"></span>Heading\n\nsee [Heading](#page-1-0).\n'
    out = cleanup_markdown(raw, level="basic", cross_refs="strip")
    assert "## Heading" in out
    assert "<span" not in out
    assert "(#page-1-0)" not in out


def test_basic_with_cross_refs_remap_does_not_preserve_heading_anchor() -> None:
    # cross_refs="remap" rewrites refs to use heading slugs, making the
    # raw page-anchor obsolete. Skip preservation.
    raw = '## <span id="page-1-0"></span>Heading\n\nsee [Heading](#page-1-0).\n'
    out = cleanup_markdown(raw, level="basic", cross_refs="remap")
    assert "## Heading" in out
    assert "<span" not in out
    assert "[Heading](#heading)" in out


def test_basic_preserves_endash_in_text() -> None:
    # Regression: stripped en-dashes mid-text, turning "6–10" into "610".
    out = cleanup_markdown("Saffron House, 6–10 Kirby Street\n", level="basic")
    assert "6–10" in out
    assert "610 Kirby" not in out


def test_basic_does_not_promote_printing_sequence_to_heading() -> None:
    # Regression: promoted "10 9 8 7 6 5 4 3 2 1" to a heading, which then
    # captured the entire rest of the document into one bogus section.
    raw = "before\n\n10 9 8 7 6 5 4 3 2 1\n\nafter\n"
    out = cleanup_markdown(raw, level="basic")
    assert "# 10." not in out
    assert "10 9 8 7 6 5 4 3 2 1" in out


# --- Aggressive-only behaviors ------------------------------------------


def test_aggressive_drops_image_only_line() -> None:
    raw = "before\n\n![](foo.png)\n\nafter\n"
    out = cleanup_markdown(raw, level="aggressive")
    assert "![](foo.png)" not in out
    assert "before" in out
    assert "after" in out


def test_aggressive_preserves_toc_table() -> None:
    """Aggressive cleanup keeps the TOC table — on some real-world docs the
    pipe-table TOC is the only one the document has, and dropping it leaves
    a heading with no body."""
    raw = (
        "## Table of Contents\n"
        "\n"
        "| 1. | Foo | 4 |\n"
        "| --- | --- | --- |\n"
        "| 1.1. | Bar | 5 |\n"
        "\n"
        "### 1. ARCHITECTURE\n"
    )
    out = cleanup_markdown(raw, level="aggressive")
    assert "Foo" in out
    assert "Bar" in out
    assert "## Table of Contents" in out
    assert "### 1. ARCHITECTURE" in out


def test_aggressive_strips_page_span() -> None:
    raw = '<span id="page-3-2"></span>### 2.5. CONFIGURATION\n'
    out = cleanup_markdown(raw, level="aggressive")
    assert "<span" not in out
    # lock_numbered_section_depth re-levels `2.5` to depth 2
    # (one dot in the prefix → H2), overriding the input H3.
    assert "## 2.5. CONFIGURATION" in out


def test_aggressive_strips_endash() -> None:
    # Aggressive keeps the strict ASCII filter; en-dashes vanish.
    out = cleanup_markdown("Saffron House, 6–10 Kirby Street\n", level="aggressive")
    assert "6–10" not in out


# --- cross_refs handling -------------------------------------------------


def test_strip_page_refs_unit() -> None:
    assert strip_page_refs("[Foo](#page-1-0)") == "Foo"
    assert strip_page_refs("see [Configuration](#page-36-0) for details") == (
        "see Configuration for details"
    )


def test_strip_page_refs_only_targets_page_anchors() -> None:
    # Real anchors (`#section-name`) are preserved; only `#page-X-Y` is rewritten.
    assert strip_page_refs("[Foo](#real-anchor)") == "[Foo](#real-anchor)"
    assert strip_page_refs("[Foo](https://example.com)") == "[Foo](https://example.com)"


def test_cross_refs_keep_is_default() -> None:
    raw = "see [Configuration](#page-36-0) for details\n"
    out = cleanup_markdown(raw, level="basic")
    assert "[Configuration](#page-36-0)" in out


def test_cross_refs_strip_drops_page_refs() -> None:
    raw = "see [Configuration](#page-36-0) for details\n"
    out = cleanup_markdown(raw, level="basic", cross_refs="strip")
    assert "[Configuration]" not in out
    assert "(#page-36-0)" not in out
    assert "see Configuration for details" in out


def test_cross_refs_strip_with_aggressive_clears_orphans() -> None:
    # Real-world non-numbered-manual-style case: span target + ref to it.
    raw = (
        '<span id="page-44-0"></span>### 2.5. CONFIGURATION\n\n'
        "later: [Tap repeatedly](#page-44-0) to trigger Tap Tempo.\n"
    )
    out = cleanup_markdown(raw, level="aggressive", cross_refs="strip")
    assert "<span" not in out  # aggressive strips the target
    assert "[Tap repeatedly]" not in out  # cross_refs strips the ref
    assert "(#page-44-0)" not in out
    assert "later: Tap repeatedly to trigger Tap Tempo." in out


def test_cross_refs_strip_preserves_real_anchors() -> None:
    raw = "see [the real section](#real-anchor) for details\n"
    out = cleanup_markdown(raw, level="basic", cross_refs="strip")
    assert "[the real section](#real-anchor)" in out


# --- Dedupe consecutive identical headings -------------------------------


def test_dedupe_consecutive_identical_headings_unit() -> None:
    assert dedupe_consecutive_headings("## Foo\n## Foo\nbody\n") == ("## Foo\nbody\n")


def test_dedupe_keeps_consecutive_different_headings() -> None:
    assert dedupe_consecutive_headings("## Foo\n## Bar\nbody\n") == ("## Foo\n## Bar\nbody\n")


def test_dedupe_keeps_when_interrupted_by_content() -> None:
    raw = "## Foo\nintro\n## Foo\n"
    assert dedupe_consecutive_headings(raw) == raw


def test_dedupe_collapses_across_blank_lines() -> None:
    # Marker's actual emission pattern: two identical headings separated by a blank.
    assert dedupe_consecutive_headings("## Foo\n\n## Foo\nbody\n") == ("## Foo\nbody\n")


def test_dedupe_handles_three_in_a_row() -> None:
    assert dedupe_consecutive_headings("## Foo\n## Foo\n## Foo\nbody\n") == ("## Foo\nbody\n")


def test_basic_dedupes_non_numbered_double_toc() -> None:
    raw = "## Table of Contents\n\n## Table of Contents\n\nbody\n"
    out = cleanup_markdown(raw, level="basic")
    # One occurrence, not two.
    assert out.count("## Table of Contents") == 1
    assert "body" in out


def test_off_does_not_dedupe() -> None:
    raw = "## Foo\n## Foo\nbody\n"
    out = cleanup_markdown(raw, level="off")
    # off returns text unchanged.
    assert out == raw


# --- cross_refs="remap" --------------------------------------------------


def test_heading_slug_basics() -> None:
    assert heading_slug("## Quick Start") == "quick-start"
    assert heading_slug("### 1.4.1. Foo Bar") == "141-foo-bar"
    assert heading_slug("# **Table of Contents**") == "table-of-contents"
    # Unpromoted numbered heading (no leading #) still slugged.
    assert heading_slug("1.4. Triggers") == "14-triggers"
    # Strips a leading page-span before slugging.
    assert heading_slug('<span id="page-3-2"></span>### 2.5. Configuration') == ("25-configuration")


def test_build_anchor_map_pairs_span_with_next_heading() -> None:
    raw = '<span id="page-3-2"></span>\n### Configuration\nbody\n'
    assert build_anchor_map(raw) == {"page-3-2": "configuration"}


def test_build_anchor_map_skips_target_with_no_following_heading() -> None:
    raw = '<span id="page-99-0"></span>\nplain text only\n'
    assert build_anchor_map(raw) == {}


def test_build_anchor_map_handles_inline_span_before_heading() -> None:
    raw = '<span id="page-44-0"></span>### TAP/TUNER Button (5)\n'
    assert build_anchor_map(raw) == {"page-44-0": "taptuner-button-5"}


def test_remap_page_refs_unit() -> None:
    anchor_map = {"page-3-2": "configuration", "page-44-0": "tap-tempo"}
    raw = "see [Configuration](#page-3-2) and [Tap Tempo](#page-44-0) for details"
    out = remap_page_refs(raw, anchor_map)
    assert out == "see [Configuration](#configuration) and [Tap Tempo](#tap-tempo) for details"


def test_remap_page_refs_falls_back_to_strip_when_no_target() -> None:
    raw = "[Foo](#page-99-0) is missing"
    out = remap_page_refs(raw, {})
    assert out == "Foo is missing"


def test_remap_page_refs_does_not_touch_non_page_anchors() -> None:
    raw = "[Foo](#real-anchor) and [Bar](https://example.com)"
    out = remap_page_refs(raw, {"page-1-0": "elsewhere"})
    assert out == raw


def test_cross_refs_remap_orchestrator_aggressive() -> None:
    # Real-world non-numbered-manual-style: span target + heading + ref to it. Aggressive
    # strips the span, but the remap pre-pass already collected the slug.
    raw = (
        '<span id="page-44-0"></span>### Tap Tempo\n\n'
        "Hit this to set tempo. See [Tap Tempo info](#page-44-0) for details.\n"
    )
    out = cleanup_markdown(raw, level="aggressive", cross_refs="remap")
    assert "<span" not in out
    assert "[Tap Tempo info](#tap-tempo)" in out


def test_cross_refs_remap_with_basic_keeps_spans() -> None:
    # Basic doesn't strip the span target, but remap still rewrites the ref.
    raw = '<span id="page-44-0"></span>### Tap Tempo\n\n[Tap Tempo info](#page-44-0)\n'
    out = cleanup_markdown(raw, level="basic", cross_refs="remap")
    assert "[Tap Tempo info](#tap-tempo)" in out


# --- promote_outline_to_headings ---


def test_cleanup_uses_new_outline_promote_and_strips_markers() -> None:
    from pagespeak.services._cleanup import cleanup_markdown

    src = (
        "* + 1. **Left pump**\n"
        "       1. left chamber\n"
        "    2. **Right pump**\n"
        "    3. **Primary circuit**\n"
    )
    out = cleanup_markdown(src, level="basic")
    assert "* +" not in out
    # emphasis stripped from headings by strip_emphasis_from_heading
    assert "# 1. Left pump" in out
    assert "## 1. left chamber" in out
