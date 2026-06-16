"""Tests for the flat-source H1 demote cleanup pass.

Detects "N+ consecutive H1s with no H2 between them" — the signature of
an HTML-export PDF where every published article became a top-level
heading in the source. Demotes the trailing H1s in each run to H2 so
normalize sees plausible hierarchy.
"""

from __future__ import annotations

import pytest

from pagespeak.services._flat_source_demote import (
    _FLAT_H1_THRESHOLD_DEFAULT,
    _flat_h1_threshold,
    demote_flat_h1_runs,
)


def test_below_threshold_unchanged() -> None:
    """4 consecutive H1s (under default threshold of 5) → no change."""
    md = "# A\nbody\n# B\nbody\n# C\nbody\n# D\nbody\n"
    out = demote_flat_h1_runs(md)
    assert out == md


def test_at_threshold_first_kept_rest_demoted() -> None:
    """5 consecutive H1s (= threshold) → first stays H1, rest become H2."""
    md = "# A\nbody\n# B\nbody\n# C\nbody\n# D\nbody\n# E\nbody\n"
    out = demote_flat_h1_runs(md)
    lines = out.splitlines()
    headings = [ln for ln in lines if ln.startswith("#")]
    assert headings == ["# A", "## B", "## C", "## D", "## E"]


def test_long_run_demotes_all_after_first() -> None:
    """10 H1s in a row → 1 kept, 9 demoted."""
    md = "\n".join(f"# H{i}\nbody{i}\n" for i in range(10))
    out = demote_flat_h1_runs(md)
    h1 = sum(1 for ln in out.splitlines() if ln.startswith("# ") and not ln.startswith("## "))
    h2 = sum(1 for ln in out.splitlines() if ln.startswith("## "))
    assert h1 == 1
    assert h2 == 9


def test_interleaved_h1_h2_unchanged() -> None:
    """authored-flat pattern: H1 always followed by H2 → no run, no change."""
    md = (
        "# Chapter 1\n## Section 1.1\nbody\n"
        "# Chapter 2\n## Section 2.1\nbody\n"
        "# Chapter 3\n## Section 3.1\nbody\n"
        "# Chapter 4\n## Section 4.1\nbody\n"
        "# Chapter 5\n## Section 5.1\nbody\n"
        "# Chapter 6\n## Section 6.1\nbody\n"
    )
    out = demote_flat_h1_runs(md)
    assert out == md


def test_h2_between_h1s_resets_run() -> None:
    """An H2 between H1s ends the current run; next H1 starts fresh."""
    md = (
        "# A\nbody\n"
        "# B\nbody\n"
        "# C\nbody\n"  # 3 H1s — under threshold
        "## sub\nbody\n"  # H2 ends the run
        "# D\nbody\n"
        "# E\nbody\n"  # only 2 H1s in this new run — under threshold
    )
    out = demote_flat_h1_runs(md)
    assert out == md


def test_h3_between_h1s_also_resets_run() -> None:
    """Any heading deeper than H1 should reset the H1 run, not just H2."""
    md = "# A\nbody\n# B\nbody\n### deep\nbody\n# C\nbody\n# D\n"
    out = demote_flat_h1_runs(md)
    # Both runs are 2 H1s — below threshold, no change.
    assert out == md


def test_body_content_preserved_byte_for_byte() -> None:
    """De-headifying must touch ONLY the heading prefix — never the body."""
    md = (
        "# A\nbody line for A with details\n"
        "another body line\n"
        "# B\nbody for B\n"
        "# C\nbody for C with special chars: < > & \" '\n"
        "# D\nbody for D\n"
        "# E\nbody for E\n"
    )
    out = demote_flat_h1_runs(md)
    # Body lines should match exactly.
    for line in [
        "body line for A with details",
        "another body line",
        "body for B",
        "body for C with special chars: < > & \" '",
        "body for D",
        "body for E",
    ]:
        assert line in out


def test_below_default_threshold_with_env_lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env-var override lowers the threshold so a 3-H1 run gets demoted."""
    monkeypatch.setenv("PAGESPEAK_FLAT_H1_THRESHOLD", "3")
    md = "# A\nbody\n# B\nbody\n# C\nbody\n"
    out = demote_flat_h1_runs(md)
    headings = [ln for ln in out.splitlines() if ln.startswith("#")]
    assert headings == ["# A", "## B", "## C"]


def test_env_var_default_is_five() -> None:
    """Sanity: the in-code default matches the documented value."""
    assert _FLAT_H1_THRESHOLD_DEFAULT == 5
    assert _flat_h1_threshold() == 5


def test_invalid_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed env values should not crash — pf-core's resolve_int warns + defaults."""
    monkeypatch.setenv("PAGESPEAK_FLAT_H1_THRESHOLD", "not-an-int")
    assert _flat_h1_threshold() == _FLAT_H1_THRESHOLD_DEFAULT


def test_no_h1_no_change() -> None:
    """Doc with no H1 → unchanged."""
    md = "## A\nbody\n## B\nbody\n## C\nbody\n## D\nbody\n## E\nbody\n"
    out = demote_flat_h1_runs(md)
    assert out == md


def test_explicit_threshold_arg_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit kwarg beats env var, beats default. Threshold = 100 → 6 H1s untouched."""
    monkeypatch.setenv("PAGESPEAK_FLAT_H1_THRESHOLD", "2")
    md = "# A\n\n# B\n\n# C\n\n# D\n\n# E\n\n# F\n"
    out = demote_flat_h1_runs(md, threshold=100)
    assert out == md


def test_heading_text_with_trailing_whitespace_preserved() -> None:
    """The pass changes only the leading `#` count — heading text is preserved."""
    md = "# Apricot — overview\n\n# Banana — sub\n\n# Cherry — sub\n\n# Date — sub\n\n# Elderberry — sub\n\n# Fig — sub\n"
    out = demote_flat_h1_runs(md)
    lines = [ln for ln in out.splitlines() if ln.startswith("#")]
    assert lines[0] == "# Apricot — overview"
    assert lines[1] == "## Banana — sub"
    assert lines[5] == "## Fig — sub"
