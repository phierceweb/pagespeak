"""The structure phase's pass sequence."""

from __future__ import annotations

from pagespeak.services._structure_passes import apply_structure_passes

_FLAT = "# A\n\nbody\n\n# B\n\nbody\n\n# C\n\nbody\n"


def test_trusted_skips_the_level_passes() -> None:
    """A hierarchy the source stated is never re-levelled."""
    assert apply_structure_passes(_FLAT, trusted=True) == _FLAT


def test_untrusted_relevels_a_flat_run() -> None:
    out = apply_structure_passes(_FLAT, trusted=False)
    assert out != _FLAT
    assert "## B" in out


def test_nesting_runs_even_when_trusted() -> None:
    """Enumerated nesting precedes the trust gate — it is not a level pass, so
    a trusted document still gets its `Step (N)` run nested under its parent."""
    src = "# Parent\n\nbody\n\n# Step (1)\n\nb\n\n# Step (2)\n\nb\n\n# Step (3)\n\nb\n"
    out = apply_structure_passes(src, trusted=True)
    assert "## Step (1)" in out and "## Step (3)" in out
    assert "# Parent" in out and "## Parent" not in out


def test_empty_input_is_unchanged() -> None:
    assert apply_structure_passes("", trusted=False) == ""
    assert apply_structure_passes("", trusted=True) == ""
