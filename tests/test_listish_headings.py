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


def test_dotted_int_keeps_isolated_sections_despite_distant_list() -> None:
    """Real `N.` section headings with bodies, pages away from a plain
    `N.` legend list, are not the list's mis-promoted members. The demote
    requires list continuation: a plain `N.` line near the heading."""
    legend = "\n".join(
        f"{i}. LEGEND ITEM {i} - a labelled control on the panel" for i in range(1, 9)
    )
    filler = "\n".join(f"body paragraph {i}." for i in range(20))
    src = (
        "# THE PANEL\n" + legend + "\n\n" + filler + "\n\n"
        "## 1. Basic setup\n\nProse describing the first setup.\n\n"
        "## 2. Advanced setup\n\nProse describing the second setup.\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert "## 1. Basic setup" in out
    assert "## 2. Advanced setup" in out


def test_dotted_int_still_demotes_embedded_step() -> None:
    # A heading INSIDE its continuing list stays a demote target.
    src = "# Procedure\n1. first step\n#### 2. Click the button.\n3. third step\n4. fourth step\n"
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 1
    assert "#### 2." not in out


def test_dotted_int_demotes_isolated_step_punctuated_heading() -> None:
    """A step-punctuated `N.` heading demotes even far from its list —
    instructions end `.`/`:`, section titles don't."""
    filler = "\n".join(f"paragraph {i}." for i in range(20))
    src = (
        "# Guide\n"
        "1. plain step one\n2. plain step two\n3. plain step three\n\n"
        + filler
        + "\n\n#### 2. Click the export button.\n\nbody\n"
        + "\n#### 6. Set the output format:\n\nbody\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 2
    assert "#### 2." not in out
    assert "#### 6." not in out


def test_dotted_int_keeps_isolated_question_heading() -> None:
    # `?` is not step punctuation — numbered FAQ headings are real.
    filler = "\n".join(f"paragraph {i}." for i in range(20))
    src = (
        "# Guide\n1. plain a\n2. plain b\n3. plain c\n\n"
        + filler
        + "\n\n#### 1. Is the problem with the hardware?\n\nbody\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 0
    assert "#### 1. Is the problem with the hardware?" in out


def test_dotted_int_link_wrapped_step_title_demotes() -> None:
    filler = "\n".join(f"paragraph {i}." for i in range(20))
    src = (
        "# Guide\n1. plain a\n2. plain b\n3. plain c\n\n"
        + filler
        + "\n\n#### 3. [Import the files.](#page-472-0)\n\nbody\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 1
    assert "#### 3." not in out


def test_dotted_int_keeps_parent_heading_near_a_step_list() -> None:
    """A `N.` heading that owns deeper children is a chapter, not a step —
    even sitting right after a plain numbered list (setup steps often end
    where the next chapter begins)."""
    src = (
        "# Guide\n"
        "1. plain a\n2. plain b\n3. plain c\n4. Open your app to continue\n\n"
        "# 5. Fifth Chapter Title\n\n"
        "## 5.1 First Subsection\n\nbody\n\n"
        "## 5.2 Second Subsection\n\nbody\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert "# 5. Fifth Chapter Title" in out
    assert n == 0


def test_dotted_int_punctuated_step_demotes_even_before_deeper_heading() -> None:
    """Punctuation outranks the parent exemption: a `Click OK.`-shaped
    heading is a step even when the next (unrelated) heading is deeper —
    mis-promoted steps land at random levels, so apparent depth is noise."""
    src = (
        "# Guide\n"
        "1. plain a\n2. plain b\n3. plain c\n\n"
        "## 2. Click OK.\n\nbody\n\n"
        "### Real Deeper Section\n\nbody\n"
    )
    out, n = demote_listish_dotted_int_headings(src)
    assert n == 1
    assert "## 2. Click OK." not in out
