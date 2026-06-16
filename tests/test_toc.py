from __future__ import annotations

from pagespeak.services._toc import regenerate_toc


def test_regenerate_toc_replaces_broken_table() -> None:
    """Marker emits structurally broken pipe-table TOCs on real docs.
    Stitch should swap in a clean bullet list of the actual headings."""
    raw = (
        "## Table of Contents\n"
        "\n"
        "| 1. | ARCHIT | ECTURE | 4 |\n"
        "| --- | --- | --- | --- |\n"
        "|  | 1.1. | API |  |\n"
        "\n"
        "# 1. ARCHITECTURE\n"
        "intro\n"
        "## 1.1. STACK\n"
        "stack body\n"
        "### 1.1.1. API\n"
        "api body\n"
    )
    out = regenerate_toc(raw)
    # Original broken pipe-table cells gone (would split words mid-character).
    assert "| ARCHIT |" not in out
    assert "| --- |" not in out
    # Generated bullets present, with anchors.
    assert "## Table of Contents" in out
    assert "- [1. ARCHITECTURE](#1-architecture)" in out
    assert "  - [1.1. STACK](#11-stack)" in out
    assert "    - [1.1.1. API](#111-api)" in out
    # Body content preserved.
    assert "stack body" in out
    assert "api body" in out


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
