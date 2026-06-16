"""Tests for pagespeak.services._normalize_repair.

The post-LLM `repair` stage: a detect→correct engine (same shape as
`_cleanup_diagnose`) that fixes the heading-hierarchy slips the LLM
heading-normalize introduces or leaves, so the split produces
relationship-preserving RAG sections. Each pass is `str -> (text, int)`,
conservative, and a no-op (`count 0`) when its pattern is absent.
"""

from __future__ import annotations

from pagespeak.services._normalize_repair import (
    close_heading_level_gaps,
    dedupe_doubled_heading_text,
    demote_number_only_headings,
    demote_spaced_letter_headings,
    repair_headings,
    strip_heading_spans,
)

# --- demote_number_only_headings (pass 1: stray page-number headings) ----


def test_demotes_number_only_heading() -> None:
    # A Marker page number the LLM left promoted to a heading. Heading
    # text is JUST a number → demote to body (these became their own
    # meaningless section dirs).
    md = "# Real Section\nbody\n# 780\n## Next Real\nmore\n"
    out, n = demote_number_only_headings(md)
    assert n == 1
    assert "# 780" not in out
    assert "\n780\n" in out  # kept as body text, not deleted
    assert "# Real Section" in out
    assert "## Next Real" in out


def test_demotes_multiple_number_only_headings() -> None:
    md = "# A\nx\n## 780\ny\n### 786\nz\n"
    out, n = demote_number_only_headings(md)
    assert n == 2
    assert "780" in out and "786" in out
    assert "## 780" not in out and "### 786" not in out


def test_numbered_section_heading_not_demoted() -> None:
    # `# 12.1 Signal Filtering` is a numbered SECTION, not a stray page
    # number — its text isn't a bare integer. Keep.
    md = "# 12.1 Signal Filtering\nbody\n"
    assert demote_number_only_headings(md) == (md, 0)


def test_bare_numbered_marker_not_demoted() -> None:
    # `# 1.` (trailing dot) is a section marker, not a bare page number.
    md = "# 1.\nbody\n"
    assert demote_number_only_headings(md) == (md, 0)


def test_noop_when_no_number_only_heading() -> None:
    md = "# Intro\nbody\n## Setup\nmore\n"
    assert demote_number_only_headings(md) == (md, 0)


def test_preserves_trailing_newline() -> None:
    md = "# A\nx\n# 780\n"
    out, _ = demote_number_only_headings(md)
    assert out.endswith("\n")


# --- dedupe_doubled_heading_text (pass 3: doubled heading text) -----------


def test_dedupes_doubled_heading_text() -> None:
    # Marker emitted the heading text twice
    # (`## Chapter Summary Chapter Summary`) → dedupe to a clean title.
    md = "## Chapter Summary Chapter Summary\nbody\n"
    out, n = dedupe_doubled_heading_text(md)
    assert n == 1
    assert "## Chapter Summary\n" in out
    assert "Chapter Summary Chapter Summary" not in out


def test_dedupes_multiword_doubled() -> None:
    md = "### Clinical Terms Clinical Terms\nx\n"
    out, n = dedupe_doubled_heading_text(md)
    assert n == 1
    assert out.startswith("### Clinical Terms\n")


def test_non_doubled_heading_kept() -> None:
    md = "## Introduction and Overview\nbody\n"
    assert dedupe_doubled_heading_text(md) == (md, 0)


def test_odd_repetition_kept() -> None:
    # "the the the" is not an exact phrase+phrase doubling → kept.
    md = "## the the the\nx\n"
    assert dedupe_doubled_heading_text(md) == (md, 0)


def test_doubled_preserves_level_and_newline() -> None:
    md = "#### Notes Notes\n"
    out, n = dedupe_doubled_heading_text(md)
    assert n == 1
    assert out == "#### Notes\n"


# --- demote_spaced_letter_headings (pass 4: letter-spaced dividers) -------


def test_demotes_letter_spaced_divider() -> None:
    # A front-matter divider `## F R A M E W O R K S Y S T E M` — a
    # decorative letter-spaced part label, not a real section.
    md = "# Real\nbody\n## F R A M E W O R K S Y S T E M\nmore\n"
    out, n = demote_spaced_letter_headings(md)
    assert n == 1
    assert "## F R A M E W O R K" not in out
    assert "F R A M E W O R K S Y S T E M" in out  # kept as body text
    assert "# Real" in out


def test_normal_heading_kept_by_spaced_pass() -> None:
    md = "## Introduction to Toolcraft\nbody\n"
    assert demote_spaced_letter_headings(md) == (md, 0)


def test_few_single_letters_kept() -> None:
    # "A B testing" has only 2 single-char tokens (< threshold) → kept.
    md = "## A B testing\nx\n"
    assert demote_spaced_letter_headings(md) == (md, 0)


def test_spaced_preserves_trailing_newline() -> None:
    md = "## E L E C T R I C A L S Y S T E M\n"
    out, n = demote_spaced_letter_headings(md)
    assert n == 1
    assert out.endswith("\n")


# --- strip_heading_spans (pass: clean leftover page-anchor spans) ---------


def test_strips_span_anchor_from_heading() -> None:
    # The LLM left page-anchor spans polluting heading titles.
    md = '# <span id="page-31-0"></span>Introduction to Widgetry\nbody\n'
    out, n = strip_heading_spans(md)
    assert n == 1
    assert out.startswith("# Introduction to Widgetry\n")
    assert "<span" not in out


def test_strips_span_keeps_glued_number() -> None:
    # span removed; the glued chapter number (a Marker dual-column artifact)
    # is NOT this pass's job — left verbatim.
    md = '## <span id="page-48-0"></span>The Unit 2 Structure\n'
    out, n = strip_heading_spans(md)
    assert n == 1
    assert out == "## The Unit 2 Structure\n"


def test_span_strip_ignores_body_spans() -> None:
    # only heading lines are cleaned; body spans stay (they are link targets).
    md = '# Real\ntext with <span id="x"></span> anchor\n'
    assert strip_heading_spans(md) == (md, 0)


def test_span_strip_noop_when_clean() -> None:
    md = "# Clean Heading\nbody\n"
    assert strip_heading_spans(md) == (md, 0)


# --- close_heading_level_gaps (pass: promote orphan over-deep headings) --


def test_close_gaps_promotes_orphan_deep_heading() -> None:
    # H2 -> H4 with no H3: the orphan H4 becomes H3; the H2 baseline stays.
    out, n = close_heading_level_gaps("## Topic\n#### Task\n")
    assert out == "## Topic\n### Task\n"
    assert n == 1


def test_close_gaps_keeps_siblings_consistent() -> None:
    out, n = close_heading_level_gaps("## Topic\n#### A\n#### B\n")
    assert out == "## Topic\n### A\n### B\n"
    assert n == 2


def test_close_gaps_cascades_subtree() -> None:
    out, n = close_heading_level_gaps("## Topic\n#### Task\n##### Step\n")
    assert out == "## Topic\n### Task\n#### Step\n"
    assert n == 2


def test_close_gaps_preserves_baseline_level() -> None:
    # The first/shallowest heading is NOT forced to H1 — only gaps close.
    out, n = close_heading_level_gaps("## Contents\n# Chapter\n")
    assert out == "## Contents\n# Chapter\n"
    assert n == 0


def test_close_gaps_noop_on_clean_hierarchy() -> None:
    md = "# A\n## B\n### C\n## D\n"
    out, n = close_heading_level_gaps(md)
    assert out == md
    assert n == 0


def test_close_gaps_idempotent() -> None:
    md = "## Topic\n#### A\n##### B\n#### C\n"
    once, _ = close_heading_level_gaps(md)
    twice, n2 = close_heading_level_gaps(once)
    assert twice == once
    assert n2 == 0


def test_close_gaps_ignores_code_fence_headings() -> None:
    md = "## Topic\n```\n#### not a heading\n```\n#### Real Task\n"
    out, n = close_heading_level_gaps(md)
    assert "```\n#### not a heading\n```" in out  # fenced line untouched
    assert "### Real Task" in out
    assert n == 1


# --- repair_headings (orchestrator) --------------------------------------


def test_repair_runs_leveling_and_artifact_passes() -> None:
    md = "# Title\n## 13\nbody\n### 1.1 Real Sub\nx\n"
    out, counts = repair_headings(md)
    assert "## 13" not in out  # number_only demoted
    assert "## 1.1 Real Sub" in out  # numbered_depth: ### 1.1 -> ## 1.1
    assert counts["repair_locked_numbered_section_depth"] >= 1
    assert counts["repair_demoted_number_only_headings"] == 1


def test_repair_outline_doc_skips_artifact_passes() -> None:
    # structure-faithful reader output: artifact passes are skipped (its
    # reconstructed headings are trusted), but the universal depth lock runs.
    md = "# Deck Title\n## 13\n### 1.1 Sub\nx\n"
    out, counts = repair_headings(md, is_outline_doc=True)
    assert "## 13" in out  # number-only demote SKIPPED on outline doc
    assert "repair_demoted_number_only_headings" not in counts
    assert "## 1.1 Sub" in out  # numbered-depth still runs


def test_repair_noop_on_clean_doc() -> None:
    md = "# 1 Introduction\n## 1.1 Background\nbody\n# 2 Method\nbody\n"
    out, counts = repair_headings(md)
    assert out == md
    assert all(v == 0 for v in counts.values())


def test_repair_closes_level_gaps_on_pdf_doc() -> None:
    # A PDF (non-outline) doc whose LLM-normalize left an H2->H4 skip.
    md = "# Chapter\n## Topic\n#### Task\nbody\n"
    out, counts = repair_headings(md)
    assert "### Task" in out  # gap closed: orphan H4 -> H3
    assert "#### Task" not in out
    assert counts["repair_closed_heading_level_gaps"] == 1


def test_repair_outline_doc_preserves_author_level_skip() -> None:
    # DOCX outlines are sacrosanct: a Word author's intentional H1->H3 skip
    # must NOT be "closed" on a structure-faithful (outline) doc.
    md = "# Deck Title\n### Intentional Sub\nx\n"
    out, counts = repair_headings(md, is_outline_doc=True)
    assert "### Intentional Sub" in out  # skip preserved
    assert "repair_closed_heading_level_gaps" not in counts
