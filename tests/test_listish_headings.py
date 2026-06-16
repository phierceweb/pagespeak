"""Tests for pagespeak.services._listish_headings.

Document-relative demotion of integer-prefixed headings that a backend
(Marker) mis-promoted from a plain-text numbered list. Two passes:

- ``demote_listish_bare_int_headings`` — bare integers (``# 19 Pair``).
- ``demote_listish_dotted_int_headings`` — single-dot integers
  (``#### 1. Click the button.``).

Both are document-relative (count heading-form vs plain-form uses of the
convention) and language-agnostic — no word/phrase list.
"""

from __future__ import annotations

from pagespeak.services._cleanup_diagnose import apply_heading_demotions
from pagespeak.services._listish_headings import (
    demote_listish_dotted_int_headings,
)

# --- demote_listish_dotted_int_headings -------------------------------------


def test_dotted_int_demotes_when_plain_majority() -> None:
    # The doc uses `N.` predominantly as a plain-text step list; the two
    # heading-form `N.` lines are mis-promoted steps -> demote them.
    src = (
        "# Editing smart control layouts\n"
        "\n"
        "#### 1. Click the inspector icon.\n"
        "The inspector opens on the left.\n"
        "2. Click the layout name.\n"
        "3. Make a selection.\n"
        "\n"
        "#### 1. Open the file.\n"
        "A dialog appears.\n"
        "2. Choose a location.\n"
        "3. Click Save.\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 2
    # The two `#### 1. …` step headings are now plain list items.
    assert "#### 1. Click the inspector icon." not in out
    assert "1. Click the inspector icon." in out
    assert "#### 1. Open the file." not in out
    assert "1. Open the file." in out
    # The real section heading is untouched.
    assert "# Editing smart control layouts" in out


def test_dotted_int_keeps_consistent_heading_spine() -> None:
    # The doc uses `N.` consistently AS headings (no plain-form steps) —
    # that is its section convention; leave it alone (H >= P).
    src = (
        "#### 1. Connect the unit\n"
        "Body text for section one.\n"
        "#### 2. Power on\n"
        "Body text for section two.\n"
        "#### 3. Configure\n"
        "Body text for section three.\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert out == src


def test_dotted_int_ignores_multidot_sections() -> None:
    # `N.M` / `N.M.O` are real numbered sections — never counted or touched,
    # regardless of how many plain `N.` list items surround them.
    src = "## 1.1 Organization\n1. first\n2. second\n3. third\n## 1.2 Regulation\n"
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert out == src


def test_dotted_int_tie_keeps() -> None:
    # P == H is a tie -> keep (demote only on a strict plain majority).
    src = "#### 1. Do a thing.\nbody\n2. then this\n"
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert out == src


def test_dotted_int_noop_without_dotted_int_headings() -> None:
    src = "# Title\n1. step one\n2. step two\n3. step three\n"
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert out == src


def test_dotted_int_runs_in_registry_and_skips_outline() -> None:
    src = "# Section\n#### 1. Click here.\nbody\n2. then this\n3. then that\n"
    _out, counts = apply_heading_demotions(src, is_outline_doc=False)
    assert counts["cleanup_demoted_listish_dotted_int_headings"] == 1
    # Outline docs (structure-faithful DOCX reader) are trusted — skipped.
    _out2, counts2 = apply_heading_demotions(src, is_outline_doc=True)
    assert "cleanup_demoted_listish_dotted_int_headings" not in counts2
