from __future__ import annotations

from pagespeak.services._toc import regenerate_toc


def test_regenerate_toc_replaces_broken_table() -> None:
    """Marker emits structurally broken pipe-table TOCs on real docs.
    Stitch should swap in a clean bullet list of the actual headings."""
    raw = (
        "## Table of Contents\n"
        "\n"
        "| 1. | PLAT | FORM | 4 |\n"
        "| --- | --- | --- | --- |\n"
        "|  | 1.1. | CACHE |  |\n"
        "\n"
        "# 1. PLATFORM\n"
        "intro\n"
        "## 1.1. SERVICES\n"
        "services body\n"
        "### 1.1.1. CACHE\n"
        "cache body\n"
    )
    out = regenerate_toc(raw)
    # Original broken pipe-table cells gone (would split words mid-character).
    assert "| PLAT |" not in out
    assert "| --- |" not in out
    # Generated bullets present, with anchors.
    assert "## Table of Contents" in out
    assert "- [1. PLATFORM](#1-platform)" in out
    assert "  - [1.1. SERVICES](#11-services)" in out
    assert "    - [1.1.1. CACHE](#111-cache)" in out
    # Body content preserved.
    assert "services body" in out
    assert "cache body" in out


def test_regenerate_toc_indents_by_depth() -> None:
    raw = "## Table of Contents\n\nold broken table here\n\n# A\n## B\n### C\n#### D\n"
    out = regenerate_toc(raw)
    # depth 1 = no indent, depth 2 = 2 spaces, depth 3 = 4, depth 4 = 6.
    assert "- [A](#a)" in out
    assert "  - [B](#b)" in out
    assert "    - [C](#c)" in out
    assert "      - [D](#d)" in out


def test_regenerate_toc_no_op_without_toc_heading() -> None:
    raw = "# Just a doc\nbody\n## Section\nmore\n"
    out = regenerate_toc(raw)
    assert out == raw


def test_regenerate_toc_excludes_self() -> None:
    """A second `Table of Contents` heading deeper in the doc shouldn't
    appear in the generated list."""
    raw = "## Table of Contents\n\nold\n\n# Real Heading\n## Table of Contents\n## Other\n"
    out = regenerate_toc(raw)
    bullets = [line for line in out.splitlines() if line.lstrip().startswith("-")]
    assert any("Real Heading" in b for b in bullets)
    assert not any("Table of Contents" in b for b in bullets)


def test_regenerate_toc_handles_empty_body_gracefully() -> None:
    """A doc with TOC but no following headings produces a TOC with empty body."""
    raw = "## Table of Contents\n\nold body\n"
    out = regenerate_toc(raw)
    assert "old body" not in out
    assert "## Table of Contents" in out


def test_regenerate_toc_normalizes_indent_when_shallowest_is_h2() -> None:
    """A doc with no H1: the shallowest heading (H2) must be a top-level TOC
    bullet (indent 0), not indented under a nonexistent H1."""
    raw = "## Table of Contents\n\nold broken table\n\n## Overview\nbody\n### Details\nbody\n"
    out = regenerate_toc(raw)
    lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("-")]
    overview = next(ln for ln in lines if "Overview" in ln)
    details = next(ln for ln in lines if "Details" in ln)
    assert overview.startswith("- ")  # top-level, no indent
    assert details.startswith("  - ")  # one level deeper


def test_regenerate_toc_preserves_anchor_slug_format() -> None:
    """The anchors in the generated TOC must match the slugs the cleanup
    pipeline produces (so links actually resolve)."""
    raw = "## Table of Contents\n\nold\n\n## Quick Start Guide\n"
    out = regenerate_toc(raw)
    assert "[Quick Start Guide](#quick-start-guide)" in out


def test_regenerate_toc_strips_trailing_emphasis_markers() -> None:
    """Marker sometimes emits headings with bold markers like `# **Title**`.
    The bullet should show the title, not the asterisks."""
    raw = "## Table of Contents\n\nold\n\n# **TITLE**\n"
    out = regenerate_toc(raw)
    # Title text should appear cleanly (heading_slug also strips the bolds).
    assert "TITLE" in out


class TestTocNeverDeletesContent:
    """Entries cap at H4, but the block boundary must not: a document whose only
    later headings are H5/H6 must keep them and their bodies."""

    def test_h5_section_and_its_body_survive(self) -> None:
        from pagespeak.services._toc import regenerate_toc

        doc = (
            "## Table of Contents\n\n"
            "| ARCHIT | ECTURE |\n\n"
            "##### Appendix A\n\n"
            "Body text that must not vanish.\n\n"
            "###### Appendix B\n\n"
            "More body text.\n"
        )
        out = regenerate_toc(doc)
        assert "Body text that must not vanish." in out, f"body deleted:\n{out!r}"
        assert "##### Appendix A" in out
        assert "More body text." in out

    def test_h4_boundary_still_works(self) -> None:
        """The common case must be unchanged: an H2 after the TOC bounds it."""
        from pagespeak.services._toc import regenerate_toc

        doc = "## Table of Contents\n\nbroken table\n\n## Overview\n\nBody.\n"
        out = regenerate_toc(doc)
        assert "broken table" not in out
        assert "## Overview" in out and "Body." in out


class TestTocIsFenceAware:
    """A `#` inside a fenced block is a shell comment, never a heading — the
    rule `services/_fences.py` exists to enforce."""

    def test_fenced_block_between_toc_and_first_heading_survives_intact(self) -> None:
        from pagespeak.services._toc import regenerate_toc

        doc = (
            "## Table of Contents\n\n"
            "```bash\n"
            "# install the tool\n"
            "pip install thing\n"
            "```\n\n"
            "## Real Section\n\n"
            "Body.\n"
        )
        out = regenerate_toc(doc)
        # The block boundary stops at the fence, so a torn fence is impossible —
        # an orphaned delimiter would turn the rest of the doc into code.
        assert out.count("```") % 2 == 0, f"fence delimiters unbalanced:\n{out}"
        assert "pip install thing" in out
        assert "## Real Section" in out and "Body." in out

    def test_body_survives_when_every_later_heading_is_fenced(self) -> None:
        """The boundary scan must not treat "no live heading" as "no content".

        Both a balanced example block and an unterminated fence (a model-emitted
        mermaid payload that opens one) hide every following heading.
        """
        from pagespeak.services._toc import regenerate_toc

        balanced = (
            "# Guide\n\n## Table of Contents\n\n| ARCHIT | ECTURE |\n\n"
            "```markdown\n## Example Heading\n```\n\nClosing prose.\n"
        )
        assert "Closing prose." in regenerate_toc(balanced)

        unterminated = (
            "# Manual\n\n## Table of Contents\n\n```\nstray opener\n\n## Setup\n\nSetup body.\n"
        )
        out = regenerate_toc(unterminated)
        assert "## Setup" in out and "Setup body." in out

    def test_shell_comment_does_not_become_a_toc_entry(self) -> None:
        from pagespeak.services._toc import regenerate_toc

        doc = (
            "## Table of Contents\n\n"
            "## Real Section\n\n"
            "```bash\n"
            "# install the tool\n"
            "```\n\n"
            "## Another Section\n\n"
            "Body.\n"
        )
        out = regenerate_toc(doc)
        toc_block = out.split("## Real Section")[0]
        assert "install the tool" not in toc_block, (
            f"a shell comment was listed as a heading:\n{toc_block}"
        )


def test_regenerate_toc_keeps_prose_between_the_toc_and_the_next_heading() -> None:
    """The block ran to the next HEADING, so unheaded prose after the contents
    table was replaced along with it.

    Manuals routinely place safety text between the contents and the first real
    section; that copy is exactly the kind a converted manual must not lose.
    """
    raw = (
        "# Owner's Manual\n\n"
        "## Table of Contents\n\n"
        "| INTRODUCTION | 3 |\n"
        "| PARTS LIST | 19 |\n\n"
        "Read these instructions.\n\n"
        "Do not use this apparatus near water.\n\n"
        "Clean only with dry cloth.\n\n"
        "# Greetings\n\n"
        "body\n"
    )
    out = regenerate_toc(raw)
    assert "Do not use this apparatus near water." in out
    assert "Clean only with dry cloth." in out
    assert "Read these instructions." in out
    # the broken table is still replaced by a generated list
    assert "| PARTS LIST | 19 |" not in out
    assert "- [Greetings](#greetings)" in out


def test_regenerate_toc_still_consumes_a_list_style_toc() -> None:
    """A TOC written as bullets with page numbers is part of the block and must
    still be replaced — the guard keys on prose, not on 'anything unrecognised'."""
    raw = "## Table of Contents\n\n- Introduction 3\n- Parts List 19\n\n# Introduction\n\nbody\n"
    out = regenerate_toc(raw)
    assert "- Introduction 3" not in out
    assert "- [Introduction](#introduction)" in out
