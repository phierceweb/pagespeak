"""Tests for services._cleanup_front_matter — the TOC-phantom, front-matter and
TOC-outline heading demotes."""

from __future__ import annotations

from pagespeak.services._cleanup_front_matter import (
    demote_front_matter_headings,
    demote_toc_phantom_headings,
)


def test_toc_phantom_leaves_a_fenced_comment_alone() -> None:
    """A shell comment shaped like a TOC entry, with a real heading twin, is code."""
    text = "# Setup\n\nbody\n\n```bash\n# Setup 12\necho hi\n```\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_toc_phantom_twin_must_be_outside_a_fence() -> None:
    """A fenced `# Setup` comment is not the real section a TOC entry points at."""
    text = "## Setup 12\n\nbody\n\n```bash\n# Setup\n```\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_front_matter_headings_book() -> None:
    """In a multi-chapter book, headings before the first chapter (first H1)
    are title-page / copyright / TOC boilerplate — demote them; body kept."""
    text = (
        "## Quick Start Guide\n"
        "## JANE Q AUTHOR\n"
        "### 1 Widget Primer 9\n"
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
    assert "1 Widget Primer 9" in lines  # the TOC entry demoted too
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


def test_demote_toc_outline_headings_book() -> None:
    """A book's detailed Contents lists each chapter heading above bulleted
    `- N.N <title> <page>` section lines. Those are TOC headings — demote
    them. A real chapter heading (prose body) is kept untouched."""
    from pagespeak.services._cleanup_front_matter import demote_toc_outline_headings

    text = (
        "# Chapter 1\n"
        "Introduction to the Subject 1\n"
        "- 1.1 Origins of the Field 2\n"
        "- 1.2 Definition of Toolcraft 3\n"
        "# Chapter 2\n"
        "The Module 23\n"
        "- 2.1 The Study of Modules 24\n"
        "- 2.3 Widget Housings 30\n"
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
    from pagespeak.services._cleanup_front_matter import demote_toc_outline_headings

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
    from pagespeak.services._cleanup_front_matter import demote_toc_outline_headings

    text = "# Only Chapter\n- 1.1 First Topic 2\n- 1.2 Second Topic 3\nbody\n"
    out, n = demote_toc_outline_headings(text)
    assert n == 0
    assert out == text


def test_demote_toc_outline_noop_single_toc_line() -> None:
    """One section-number line under a heading is below the >=2 threshold —
    not enough signal to call it a TOC heading."""
    from pagespeak.services._cleanup_front_matter import demote_toc_outline_headings

    text = (
        "# Chapter 1\n"
        "- 1.1 History 2\n"
        "Then real prose about the history of toolcraft follows here.\n"
        "# Chapter 2\nprose\n# Chapter 3\nprose\n"
    )
    out, n = demote_toc_outline_headings(text)
    assert n == 0
    assert out == text


def test_demote_toc_phantom_with_body_match() -> None:
    """TOC entry with page-num suffix + matching body heading → demote."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## 1.1 Origins of the Field 2\n\n## 1.1 Origins of the Field\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "1.1 Origins of the Field 2\n\n## 1.1 Origins of the Field\n"


def test_demote_toc_phantom_keeps_the_line_indent() -> None:
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "  ## Widget Basics 4\n\n## Widget Basics\n"
    assert demote_toc_phantom_headings(text) == ("  Widget Basics 4\n\n## Widget Basics\n", 1)


def test_demote_toc_phantom_no_body_match_preserves() -> None:
    """Heading with trailing digit but no body match → preserve (signal 2 protection)."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## Section 2020\n\nsome body text\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_body_only_preserves() -> None:
    """Body heading with no TOC entry → preserve."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## 1.1 Origins of the Field\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_multiple_toc_entries() -> None:
    """Brief + Detailed Contents both pointing at same body heading → demote both."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## 1.1 History 2\n\n## 1.1 History 2\n\n## 1.1 History\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 2
    assert out == "1.1 History 2\n\n1.1 History 2\n\n## 1.1 History\n"


def test_demote_toc_phantom_multi_digit_pagenum() -> None:
    """Page number can be 1-4 digits."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## 14.3 Signal Pulses 412\n\n## 14.3 Signal Pulses\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "14.3 Signal Pulses 412\n\n## 14.3 Signal Pulses\n"


def test_demote_toc_phantom_non_numbered() -> None:
    """Non-numbered TOC entries also fire when signal 2 matches."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## Introduction 5\n\n## Introduction\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "Introduction 5\n\n## Introduction\n"


def test_demote_toc_phantom_bullet_list_immune() -> None:
    """Bullet items with page numbers are not headings; preserved unchanged."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "- 1.1 Origins of the Field 2\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_no_suffix_unaffected() -> None:
    """A heading whose text matches a later heading but lacks a page suffix
    on EITHER side is not a phantom — preserved verbatim."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## 1.1 History\n\n## 1.1 History\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_five_digit_number_preserves() -> None:
    """5+ digit trailing number is unlikely to be a page number; don't fire."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## Section 12345\n\n## Section\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text


def test_demote_toc_phantom_preserves_depth_of_body_heading() -> None:
    """When demoting, the body heading's depth marker is untouched."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "### 1.2b Gross Toolcraft 4\n\n### 1.2b Gross Toolcraft\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert out == "1.2b Gross Toolcraft 4\n\n### 1.2b Gross Toolcraft\n"


def test_demote_toc_phantom_numbering_insensitive_twin() -> None:
    """The dominant textbook case. The front-matter TOC prints
    `Layout of the Widget 32` (no section number); the body heading
    is `## 1.1 Layout of the Widget` (numbered, no page num). The
    match key strips BOTH the page number and the leading `1.1`
    section-number prefix, so the TOC line is recognised and demoted
    while the real numbered heading is kept untouched."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = (
        "#### Layout of the Widget 32\n\n"
        "blurb line\n\n"
        "## 1.1 Layout of the Widget\n\n"
        "Real section body content.\n"
    )
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert "#### Layout of the Widget 32" not in out  # TOC demoted
    assert "Layout of the Widget 32" in out  # text preserved as prose
    assert "## 1.1 Layout of the Widget" in out  # real heading kept


def test_demote_toc_phantom_case_insensitive_twin() -> None:
    """Match key is casefolded — a SHOUTED TOC entry matches its
    title-case real heading twin."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## MODULE STRUCTURE 59\n\n## 2.1 Module Structure\n\nBody.\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 1
    assert "## MODULE STRUCTURE 59" not in out
    assert "## 2.1 Module Structure" in out


def test_demote_toc_phantom_no_twin_still_preserved() -> None:
    """Safety unchanged: a page-numbered heading with NO same-core clean
    twin elsewhere is NOT demoted (could be a real heading that happens
    to end in a number)."""
    from pagespeak.services._cleanup_front_matter import demote_toc_phantom_headings

    text = "## Appendix Table 7\n\nsome content\n\n## Glossary\n\nmore\n"
    out, count = demote_toc_phantom_headings(text)
    assert count == 0
    assert out == text
