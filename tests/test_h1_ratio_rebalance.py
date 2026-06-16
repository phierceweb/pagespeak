"""Tests for the orphan-H1 rebalance structure-phase pass.

Catches the flat-publish pattern of a machine-flattened help-site export:
every help article is published as `# Title` — a childless leaf, not a
chapter. The signal that distinguishes it from a healthy-pyramid doc (or a
real section with an under-built hierarchy) is **whether each H1 owns any
child heading (H2-H6) between it and the next H1**.

- Healthy book / real section: `# Chapter N` is followed by a sub-heading
  — a `## Section`, or even just a `###` — before the next H1. Orphan
  ratio ≈ low.
- Flat-source: many H1s are childless leaf articles with no sub-heading
  of any level before the next H1. Orphan ratio ≈ high.

When the orphan ratio exceeds the threshold, every childless H1 gets
demoted to H2. An H1 that owns even an H3 child is kept (real structure,
not a leaf). The first H1 in the doc (typically the document title) is
always kept at H1.
"""

from __future__ import annotations

import pytest

from pagespeak.services._h1_ratio_rebalance import (
    _ORPHAN_H1_RATIO_THRESHOLD_DEFAULT,
    _orphan_h1_ratio_threshold,
    rebalance_orphan_h1s,
)


def test_healthy_book_no_rebalance() -> None:
    """Every H1 has H2 children → orphan ratio 0 → no rebalance."""
    md = (
        "# Title\nbody\n"
        "# Chapter 1\n## Section 1.1\nbody\n## Section 1.2\nbody\n"
        "# Chapter 2\n## Section 2.1\nbody\n## Section 2.2\nbody\n"
        "# Chapter 3\n## Section 3.1\nbody\n"
    )
    out = rebalance_orphan_h1s(md)
    assert out == md


def test_flat_publish_pattern_demotes_orphans() -> None:
    """Flat-source: lots of H1 articles, only the title H1 has H2 child."""
    md = (
        "# Doc Title\nbody\n## Real subtitle\nbody\n"  # title with H2 sub
        "# Article 1\nbody\n"
        "# Article 2\nbody\n"
        "# Article 3\nbody\n"
        "# Article 4\nbody\n"
        "# Article 5\nbody\n"
        "# Article 6\nbody\n"
    )
    out = rebalance_orphan_h1s(md)
    h1s = [ln for ln in out.splitlines() if ln.startswith("# ")]
    h2s = [ln for ln in out.splitlines() if ln.startswith("## ")]
    # Title kept at H1; 6 orphan articles demoted to H2.
    assert h1s == ["# Doc Title"]
    assert "## Article 1" in h2s
    assert "## Article 6" in h2s


def test_first_h1_always_kept() -> None:
    """The first H1 (typically document title) is always preserved
    regardless of whether it has an H2 child — title slot is sacred."""
    md = (
        "# Title without H2 sub\nbody\n"  # title but no H2 child
        "# Article A\nbody\n"
        "# Article B\nbody\n"
        "# Article C\nbody\n"
        "# Article D\nbody\n"
    )
    out = rebalance_orphan_h1s(md)
    lines = out.splitlines()
    assert lines[0] == "# Title without H2 sub"
    # Other 4 H1s are orphans → demoted.
    h1_count = sum(1 for ln in lines if ln.startswith("# ") and not ln.startswith("## "))
    assert h1_count == 1


def test_authored_flat_pattern_unchanged() -> None:
    """an authored-flat doc uses H1/H2 interleaved 1:1 by design — every H1 has
    an H2 child → no orphans → no rebalance (the source is authored
    flat by design)."""
    md = (
        "# Lab 1\n## Objectives\nbody\n## Procedure\nbody\n"
        "# Lab 2\n## Objectives\nbody\n## Procedure\nbody\n"
        "# Lab 3\n## Objectives\nbody\n## Procedure\nbody\n"
        "# Lab 4\n## Objectives\nbody\n## Procedure\nbody\n"
        "# Lab 5\n## Objectives\nbody\n## Procedure\nbody\n"
    )
    out = rebalance_orphan_h1s(md)
    assert out == md


def test_below_threshold_no_rebalance() -> None:
    """If the orphan ratio is below threshold (default 70%), leave alone."""
    md = (
        "# Title\n## sub\nbody\n"
        "# Real chapter\n## sub\nbody\n"
        "# Real chapter 2\n## sub\nbody\n"
        "# Real chapter 3\n## sub\nbody\n"
        "# Orphan article\nbody\n"  # 1 orphan / 4 candidates = 25% — under 70%
    )
    out = rebalance_orphan_h1s(md)
    # Below threshold: nothing changes.
    assert out == md


def test_authored_flat_orphan_ratio_below_default_spared() -> None:
    """An authored-flat doc with an orphan ratio below the 70% default
    threshold must be spared."""
    md = (
        "# Title\n## sub\nbody\n"
        "# Chapter 1\n## sub\nbody\n"  # not orphan
        "# Chapter 2\n## sub\nbody\n"  # not orphan
        "# Activity A\nbody\n"  # orphan
        "# Activity B\nbody\n"  # orphan
        "# Activity C\nbody\n"  # orphan — 3/5 candidates = 60% — under 70%
    )
    out = rebalance_orphan_h1s(md)
    assert out == md


def test_at_threshold_rebalances() -> None:
    """When orphan ratio crosses threshold, all orphans demote."""
    md = (
        "# Title\n## sub\nbody\n"
        "# Real chapter\n## sub\nbody\n"  # has H2 child
        "# Orphan 1\nbody\n"
        "# Orphan 2\nbody\n"
        "# Orphan 3\nbody\n"
        "# Orphan 4\nbody\n"
        "# Orphan 5\nbody\n"  # 5 orphans / 6 candidates = 83% — over 70%
    )
    out = rebalance_orphan_h1s(md)
    h1s = [ln for ln in out.splitlines() if ln.startswith("# ") and not ln.startswith("## ")]
    h2s = [ln for ln in out.splitlines() if ln.startswith("## ")]
    # Title + "Real chapter" kept at H1; 5 orphans demoted.
    assert "# Title" in h1s
    assert "# Real chapter" in h1s
    assert "## Orphan 1" in h2s
    assert "## Orphan 5" in h2s


def test_body_content_preserved_byte_for_byte() -> None:
    """Rebalance touches only heading prefixes — body lines verbatim."""
    md = (
        "# Title\n## sub\nbody for title section\n"
        "# Article A\nbody for A with special chars: < > & \" '\n"
        "# Article B\nbody for B\n"
        "# Article C\nbody for C\n"
        "# Article D\nbody for D\n"
        "# Article E\nbody for E\n"
    )
    out = rebalance_orphan_h1s(md)
    for line in [
        "body for title section",
        "body for A with special chars: < > & \" '",
        "body for B",
        "body for E",
    ]:
        assert line in out


def test_no_h1_no_change() -> None:
    """Doc with no H1 → unchanged."""
    md = "## A\nbody\n## B\nbody\n### C\nbody\n"
    out = rebalance_orphan_h1s(md)
    assert out == md


def test_single_h1_no_change() -> None:
    """One H1 (the title) → no ratio to compute → no change."""
    md = "# Title\nbody\n## A\nbody\n## B\nbody\n"
    out = rebalance_orphan_h1s(md)
    assert out == md


def test_env_var_default_is_documented_value() -> None:
    """Sanity: default threshold matches what the docstring promises.

    70% is the default: high enough that a flat-publish export (mostly
    orphan H1s) is caught, while an authored-flat doc (H1/H2 interleaved
    by design) stays below it and is spared.
    """
    assert _ORPHAN_H1_RATIO_THRESHOLD_DEFAULT == 70  # percent
    assert _orphan_h1_ratio_threshold() == 70


def test_invalid_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD", "not-an-int")
    assert _orphan_h1_ratio_threshold() == _ORPHAN_H1_RATIO_THRESHOLD_DEFAULT


def test_env_var_override_lowers_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """A threshold of 20% should fire on a 25%-orphan doc."""
    monkeypatch.setenv("PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD", "20")
    md = (
        "# Title\n## sub\nbody\n"
        "# Real chapter\n## sub\nbody\n"
        "# Real chapter 2\n## sub\nbody\n"
        "# Orphan\nbody\n"  # 1 orphan / 4 = 25%
    )
    out = rebalance_orphan_h1s(md)
    # Orphan demoted.
    h1s = [ln for ln in out.splitlines() if ln.startswith("# ") and not ln.startswith("## ")]
    assert "# Orphan" not in h1s
    assert "## Orphan" in [ln for ln in out.splitlines() if ln.startswith("## ")]


def test_child_means_any_deeper_heading_not_just_h2() -> None:
    """A 'child' is ANY deeper heading (H2-H6), not only an H2. An H1 that
    owns an H3/H4 child has real structure and is kept; only truly
    childless H1s are orphans. Here the childless ones dominate, so the
    rebalance fires and demotes exactly them — sparing the deep-child
    sections."""
    md = (
        "# Title\n## sub\nbody\n"
        "# A\nbody\n### deep, no H2 first\nbody\n"  # H3 child — kept (real section)
        "# B\nbody\n#### even deeper\nbody\n"  # H4 child — kept (real section)
        "# C\nbody\n"  # childless — orphan
        "# D\nbody\n"  # childless — orphan
        "# E\nbody\n"  # childless — orphan
        "# F\nbody\n"  # childless — orphan
        "# G\nbody\n"  # childless — 5 orphans / 7 candidates = 71% > 70%
    )
    out = rebalance_orphan_h1s(md)
    lines = out.splitlines()
    h1s = [ln for ln in lines if ln.startswith("# ") and not ln.startswith("## ")]
    h2s = [ln for ln in lines if ln.startswith("## ")]
    assert "# Title" in h1s
    assert "# A" in h1s  # kept — owns a deeper (H3) child
    assert "# B" in h1s  # kept — owns a deeper (H4) child
    assert "## A" not in h2s  # NOT demoted
    assert "## C" in h2s  # childless orphan → demoted
    assert "## G" in h2s


def test_h1_with_deeper_child_no_h2_is_not_orphan() -> None:
    """A section with a deeper child (H3/H4) but no H2 is a real section
    with an under-built hierarchy — NOT a flat-publish leaf article. It
    must NOT be flattened. Only a TRULY childless H1 (no sub-heading at any
    level before the next H1) counts as an orphan. This is the flat-2-level
    case (under-leveled manuals, numbered-section papers): a bare 'no H2
    child' test would wrongly collapse it, so orphan means childless at
    every level."""
    md = (
        "# Title\n## sub\nbody\n"
        "# Section A\nbody\n### Detail A1\nbody\n### Detail A2\nbody\n"  # H3 child, no H2
        "# Section B\nbody\n### Detail B1\nbody\n"  # H3 child, no H2
        "# Section C\nbody\n#### Deep C1\nbody\n"  # H4 child, no H2
        "# Section D\nbody\n### Detail D1\nbody\n"  # H3 child, no H2
    )
    out = rebalance_orphan_h1s(md)
    # Every section owns a deeper child → none are orphans → no rebalance.
    assert out == md
