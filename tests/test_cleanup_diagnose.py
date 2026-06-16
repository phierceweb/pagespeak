from __future__ import annotations

from pagespeak.services._cleanup import (
    demote_recurring_scaffold_headings,
    demote_toc_phantom_headings,
)
from pagespeak.services._cleanup_diagnose import (
    HEADING_DEMOTE_PASSES,
    apply_heading_demotions,
    demote_empty_shell_headings,
    demote_listish_bare_int_headings,
    demote_prose_headings,
    lock_numbered_section_depth_pass,
    strip_heading_emphasis_pass,
)


def test_lock_numbered_section_depth_pass_relevels_only_numbered() -> None:
    src = "#### 1.2 Database\n# 1.2.3 API\n## Introduction\n1.2 plain body\n"
    out, n = lock_numbered_section_depth_pass(src)
    assert n == 2
    assert "## 1.2 Database" in out  # 1 dot -> depth 2
    assert "### 1.2.3 API" in out  # 2 dots -> depth 3
    assert "## Introduction" in out  # non-N.M heading untouched
    assert "1.2 plain body" in out  # non-heading untouched


def test_lock_pass_runs_first_and_unconditionally() -> None:
    src = "#### 1.2 Database\n"
    out, counts = apply_heading_demotions(src)
    assert counts["cleanup_locked_numbered_section_depth"] == 1
    assert "## 1.2 Database" in out
    out2, counts2 = apply_heading_demotions(src, is_outline_doc=True)
    assert counts2["cleanup_locked_numbered_section_depth"] == 1  # unconditional


def test_strip_heading_emphasis_pass_strips_only_headings() -> None:
    src = "# **Bold Title**\n\nBody with **kept bold**.\n## Plain\n"
    out, n = strip_heading_emphasis_pass(src)
    assert n == 1
    assert "# Bold Title" in out  # heading markers gone
    assert "Body with **kept bold**." in out  # body emphasis preserved
    assert "## Plain" in out  # clean heading untouched


def test_emphasis_pass_runs_unconditionally_and_first() -> None:
    # Unconditional (even on outline docs) AND ordered before
    # prose-demote: a bold prose-shaped heading is emphasis-stripped
    # then (non-outline) prose-demoted — proves the load-bearing order.
    src = "# **If you're new to this tool, here's an overview of the typical workflow.**\n"
    out, counts = apply_heading_demotions(src)
    assert counts["cleanup_stripped_heading_emphasis"] == 1
    assert "# If you're new to this tool" not in out  # emphasis-stripped THEN demoted

    out2, counts2 = apply_heading_demotions(src, is_outline_doc=True)
    assert counts2["cleanup_stripped_heading_emphasis"] == 1  # still runs
    # outline doc: prose-demote skipped, but emphasis still stripped
    assert "# If you're new to this tool, here's an overview of the typical workflow." in out2


# A non-numbered prose-shaped heading (>40 chars, terminal period,
# not all-caps) — _heading_sanity.demote_prose_heading demotes it.
_PROSE_H = "## If you're new to this tool, here's an overview of the typical workflow.\n"
_REAL_H = "## Ventilation and lung mechanics\n"


def test_demote_prose_headings_demotes_prose_keeps_real() -> None:
    out, n = demote_prose_headings(_PROSE_H + "\n" + _REAL_H)
    assert n == 1
    assert "## If you're new to this tool" not in out  # demoted to plain text
    assert "## Ventilation and lung mechanics" in out  # real heading kept


def test_apply_runs_prose_pass_by_default() -> None:
    out, counts = apply_heading_demotions(_PROSE_H + "\n" + _REAL_H)
    assert counts["cleanup_demoted_prose_headings"] == 1
    assert "## If you're new to this tool" not in out
    assert "## Ventilation and lung mechanics" in out


def test_apply_skips_prose_pass_on_outline_doc() -> None:
    # Outline-promoted docs: reconstructed section titles are
    # legitimately sentence-shaped — the prose pass MUST be skipped so
    # they are not wrongly demoted (the invariant).
    out, counts = apply_heading_demotions(_PROSE_H + "\n" + _REAL_H, is_outline_doc=True)
    assert "cleanup_demoted_prose_headings" not in counts
    assert "## If you're new to this tool" in out  # NOT demoted


def test_registry_order_and_events() -> None:
    # Order is load-bearing (each pass runs on the previous output).
    assert [event for event, _ in HEADING_DEMOTE_PASSES] == [
        "cleanup_demoted_front_matter_headings",
        "cleanup_demoted_toc_outline_headings",
        "cleanup_demoted_toc_phantom_headings",
        "cleanup_demoted_empty_shell_headings",
        "cleanup_demoted_recurring_scaffold",
        "cleanup_demoted_listish_bare_int_headings",
        "cleanup_demoted_listish_dotted_int_headings",
        "cleanup_demoted_orphan_fragments",
    ]


def test_clean_doc_is_untouched_all_counts_zero() -> None:
    src = "# Real Title\n\nProse body with no demotable pattern.\n\n## A Section\n"
    out, counts = apply_heading_demotions(src)
    assert out == src
    assert set(counts.values()) == {0}


def test_parity_with_registry_sequence() -> None:
    # The engine must apply the registry's demote fns in registry
    # order. Input exercises TOC-phantom.
    src = "## Introduction 5\n\n## Introduction\n\nReal introduction body text.\n"
    expected, _ = demote_toc_phantom_headings(src)
    expected, _ = demote_empty_shell_headings(expected)
    expected, _ = demote_recurring_scaffold_headings(expected)

    out, counts = apply_heading_demotions(src)
    assert out == expected
    assert counts["cleanup_demoted_toc_phantom_headings"] >= 1


def test_dispatch_demotes_toc_phantom_end_to_end() -> None:
    src = "## Methods 12\n\n## Methods\n\nThe real methods section body.\n"
    out, counts = apply_heading_demotions(src)
    assert "## Methods 12" not in out  # phantom demoted to plain text
    assert "## Methods" in out  # the real heading kept
    assert counts["cleanup_demoted_toc_phantom_headings"] >= 1


# --- general empty-shell-heading demote ---


def test_empty_shell_demoted_real_same_level_title_kept() -> None:
    # The flat-source shape: a bodyless `# Chapter 1` directly above the
    # real same-level chapter title. The shell demotes to plain text;
    # the real title stays a heading. No English-"Chapter" word needed.
    src = "# Chapter 1\n\n# Getting Started with the Tool\n\nReal body.\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 1
    lines = out.splitlines()
    assert "Chapter 1" in lines  # demoted to plain text (kept verbatim)
    assert "# Chapter 1" not in lines
    assert "# Getting Started with the Tool" in lines  # real title kept


def test_empty_shell_strictly_deeper_successor_parent_not_touched() -> None:
    # SAFETY: a real section parent introduces a STRICTLY DEEPER child
    # with no preamble. `# Part I` → `## Chapter 1` (and `## 1.1` →
    # `### 1.1.1`) is legitimate nesting — must be preserved. Only a
    # strictly-deeper successor is the protected case.
    src = "# Part I\n\n## Chapter 1\n\nBody under chapter 1.\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 0
    assert out == src
    src2 = "## 1.1\n\n### 1.1.1\n\nLeaf body.\n"
    out2, n2 = demote_empty_shell_headings(src2)
    assert n2 == 0
    assert out2 == src2


def test_empty_shell_shallower_successor_orphan_demoted() -> None:
    # The other flat-source shape: Marker sized the shell DEEPER than the
    # real title (`#### Chapter 10` then `# Working …`). The bodyless
    # deep heading's structure moves UP, not down — it introduced no
    # section, so it is an orphan shell → demote. A real parent is never
    # deeper than what it precedes.
    src = "#### Chapter 10\n\n# Working with Components\n\nReal body.\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 1
    lines = out.splitlines()
    assert "Chapter 10" in lines  # demoted to plain text
    assert "#### Chapter 10" not in lines
    assert "# Working with Components" in lines  # real title kept


def test_empty_shell_heading_with_body_not_touched() -> None:
    # A heading with real body before the next heading is a real
    # section, not a shell.
    src = "# A\n\nsome real content here\n\n# B\n\nmore.\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 0
    assert out == src


def test_empty_shell_run_demotes_all_but_bodied_one() -> None:
    # `# A` / `# B` / `# C(body)` — A and B are same-level shells, C is
    # the real section. A and B demote; C is kept.
    src = "# A\n\n# B\n\n# C\n\nThe real content lives here.\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 2
    lines = out.splitlines()
    assert "# A" not in lines and "A" in lines
    assert "# B" not in lines and "B" in lines
    assert "# C" in lines  # the only one with a body — kept


def test_empty_shell_noop_on_single_heading_reader_shape() -> None:
    # The structure-faithful reader emits ONE `#` title then a nested
    # list — no second heading, so the pass cannot fire (it never
    # touches the structure-faithful deck corpus).
    src = "# Cell Metabolism\n\n1. item\n  1. nested\n2. item\n"
    out, n = demote_empty_shell_headings(src)
    assert n == 0
    assert out == src


def test_empty_shell_demote_runs_end_to_end_in_registry() -> None:
    src = "# Chapter 1\n\n# Getting Started\n\nReal chapter body text.\n"
    out, counts = apply_heading_demotions(src)
    assert counts["cleanup_demoted_empty_shell_headings"] == 1
    assert "# Chapter 1" not in out
    assert "# Getting Started" in out


def test_apply_skips_empty_shell_on_outline_doc() -> None:
    # invariant: a reconstructed flattened-outline doc's section
    # headings were rebuilt from source structure and must be trusted.
    # The empty-shell heuristic (targeting Marker page-header shells)
    # MUST be skipped there — two consecutive same-level reconstructed
    # headings are NOT a backend shell.
    src = "## Section One reconstructed title\n\n## Section Two reconstructed title\n\nbody.\n"
    out, counts = apply_heading_demotions(src, is_outline_doc=True)
    assert "cleanup_demoted_empty_shell_headings" not in counts
    assert "## Section One reconstructed title" in out  # NOT demoted
    # And it DOES fire on the same input when it's a backend doc.
    out2, counts2 = apply_heading_demotions(src, is_outline_doc=False)
    assert counts2["cleanup_demoted_empty_shell_headings"] == 1
    assert "## Section One reconstructed title" not in out2


# --- bare-integer step-heading demotion (numbered-procedure regression) ---


def test_listish_bare_int_demotes_when_plain_majority() -> None:
    # numbered-procedure manual shape: a numbered procedure where most steps are plain text
    # and a few got mis-promoted to headings. plain (3) > headings (2) =>
    # the doc uses bare integers as a step list => demote the headings.
    src = (
        "17 Press and hold Off on dimmer\n"
        "18 Press and hold Off on remote\n"
        "19 Repeat for additional remotes\n"
        "# 7 Remove side sections\n"
        "## 13 Connect the wires\n"
    )
    out, n = demote_listish_bare_int_headings(src)
    assert n == 2
    assert "# 7 Remove side sections" not in out
    assert "7 Remove side sections" in out  # demoted to plain text
    assert "13 Connect the wires" in out
    assert "## 13 Connect the wires" not in out


def test_listish_bare_int_keeps_consistent_heading_spine() -> None:
    # research-paper / quality shape: bare integers used CONSISTENTLY as section
    # headings, no plain-text numbered siblings => the doc's section
    # convention => keep them all.
    src = (
        "# 1 Introduction\n\nbody\n\n# 2 The Algorithm\n\nbody\n\n## 3 Results\n\n# 4 Conclusion\n"
    )
    out, n = demote_listish_bare_int_headings(src)
    assert n == 0
    assert out == src


def test_listish_bare_int_ignores_multidot_sections() -> None:
    # numbered-section shape: N.M.K numbered sections are real; never bare-int.
    src = "1 plain\n2 plain\n3 plain\n### 2.5.5. Step 4 Validate\n#### 3.6.10. Removal Criteria\n"
    out, n = demote_listish_bare_int_headings(src)
    assert n == 0  # multi-dot headings are not bare-int; untouched
    assert "### 2.5.5. Step 4 Validate" in out
    assert "#### 3.6.10. Removal Criteria" in out


def test_listish_bare_int_tie_keeps() -> None:
    # film-stock catalog shape: equal counts is not a plain-majority => keep.
    src = "1 plain step\n2 plain step\n#### 35 mm and 65 mm End Use\n#### 16 mm End Use\n"
    out, n = demote_listish_bare_int_headings(src)
    assert n == 0
    assert out == src


def test_listish_bare_int_noop_without_bare_int_headings() -> None:
    src = "# Real Title\n\n## A Section\n\n1 a plain numbered line\n2 another\n"
    out, n = demote_listish_bare_int_headings(src)
    assert n == 0
    assert out == src


def test_listish_bare_int_runs_in_registry_and_skips_outline() -> None:
    src = "17 Press and hold Off\n18 Press and hold Off\n19 Repeat\n# 7 Remove side sections\n"
    out, counts = apply_heading_demotions(src)
    assert counts["cleanup_demoted_listish_bare_int_headings"] == 1
    assert "# 7 Remove side sections" not in out
    # Outline docs: reconstructed headings are trusted — skip the pass.
    out2, counts2 = apply_heading_demotions(src, is_outline_doc=True)
    assert "cleanup_demoted_listish_bare_int_headings" not in counts2
    assert "# 7 Remove side sections" in out2


# --- orphan-fragment demotion (re-homed from the killed structure stage) ---


def test_orphan_fragments_runs_in_registry_and_skips_outline() -> None:
    # A TRAILING body-less margin code (`EN`) at the deepest level with no
    # successor heading. empty-shell (earlier in the registry) can't catch
    # it — it requires a following heading — so orphan-fragments is the
    # pass that demotes it. demote_prose_heading also leaves it (all-caps
    # guard). This isolates orphan-fragments' additive contribution.
    src = "# Title\n\nintro\n\n## Chapter\n\nbody\n\n###### EN\n"
    out, counts = apply_heading_demotions(src)
    assert counts["cleanup_demoted_empty_shell_headings"] == 0  # no successor heading
    assert counts["cleanup_demoted_orphan_fragments"] == 1
    assert "###### EN" not in out
    assert "## Chapter" in out  # real heading kept
    # Outline docs: reconstructed headings are trusted — skip the pass.
    out2, counts2 = apply_heading_demotions(src, is_outline_doc=True)
    assert "cleanup_demoted_orphan_fragments" not in counts2
    assert "###### EN" in out2
