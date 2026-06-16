"""Tests for pagespeak.services._fragments.

The orphan-fragment detector demotes body-less page-margin codes at the
document's max heading depth to plain text. Its pass API is the
cleanup-pass shape ``str -> (text, count)``.
"""

from __future__ import annotations

from pagespeak.services._fragments import (
    _has_substantive_body,
    _is_short_fragment,
    demote_orphan_fragments,
)

# --- demote_orphan_fragments (the public pass) ---------------------------


def test_demotes_body_less_codes() -> None:
    # Real-world shape: a page-margin code with NO body (next line is
    # another heading) and isolated (a real heading sits between
    # successive codes → run length 1) → demoted.
    md = (
        "# Title\nintro\n## Chapter\nbody\n"
        "###### EN\n# 1. Operational Overview\nch1 body\n"
        "###### E\n## Effects\nfx body\n"
    )
    out, n = demote_orphan_fragments(md)
    assert n == 2
    assert "######" not in out  # both EN / E codes demoted
    assert "\nEN\n" in out
    assert "# 1. Operational Overview" in out  # real heading kept


def test_noop_single_depth() -> None:
    md = "# A\nx\n# B\ny\n"
    assert demote_orphan_fragments(md) == (md, 0)


def test_noop_when_deep_heading_is_real() -> None:
    md = "# T\na\n## S\nb\n### Detailed Configuration Steps\nc\n"
    assert demote_orphan_fragments(md) == (md, 0)


def test_targets_only_fragments_at_max_depth() -> None:
    # Two headings at max depth (H6): one real, one fragment. Only the
    # fragment is demoted.
    md = "# T\n## C\n###### Real Section Name\n###### EN\n"
    out, n = demote_orphan_fragments(md)
    assert n == 1
    assert "###### Real Section Name" in out
    assert "###### EN" not in out


def test_spares_glossary_term_with_body() -> None:
    # `#### DAT` / `#### VHS` are real glossary entries with a definition
    # paragraph. The body signal spares them.
    md = (
        "# Glossary\n## Terms\n"
        "#### Balanced Audio Signals\nThree-conductor cable signals.\n"
        "#### DAT\nDigital Audio Tape recorder format.\n"
        "#### Digital I/O\nDigital input/output connections.\n"
        "#### VHS\nVideo Home System consumer format.\n"
    )
    assert demote_orphan_fragments(md) == (md, 0)


def test_spares_index_letter_run() -> None:
    # A run of >= FRAGMENT_INDEX_RUN_MIN single-letter dividers is an
    # alphabetical index → spared.
    body = "\nentry text for this letter.\n"
    md = "# Index\n## Front\nintro\n" + "".join(f"## {c}{body}" for c in "ABCDEFGH")
    assert demote_orphan_fragments(md) == (md, 0)


def test_scattered_junk_still_demoted() -> None:
    # Many body-less codes, each separated by a real shallower heading →
    # every run length 1 (< threshold) → ALL still demoted (a cluster
    # signal must not spare scattered junk).
    parts = ["# Doc\n"]
    for k in range(6):
        parts.append(f"## Chapter {k}\nchapter {k} body\n###### EN\n")
    out, n = demote_orphan_fragments("".join(parts))
    assert n == 6
    assert "######" not in out


def test_run_exactly_at_threshold() -> None:
    # Run of exactly 5 short body-less max-depth headings (>= 5) → spared
    # as an index run; a run of 4 (< 5) → demoted. A non-fragment H2
    # establishes >= 2 depths without joining the run.
    five = "# D\n## Real Heading\nx\n" + "".join(f"## {c}\n" for c in "ABCDE")
    assert demote_orphan_fragments(five) == (five, 0)
    four = "# D\n## Real Heading\nx\n" + "".join(f"## {c}\n" for c in "ABCD")
    out4, n4 = demote_orphan_fragments(four)
    assert n4 == 4


def test_demote_preserves_following_anchor_line() -> None:
    # In cleanup the per-line loop has already moved the heading's anchor
    # onto the next line. The pass sees `#### EN` + a span-only line
    # (non-body) → demotes EN; the anchor survives on its own line.
    md = '# Title\na\n## Sec\nb\n#### EN\n<span id="page-9-0"></span>\n## Next\nc\n'
    out, n = demote_orphan_fragments(md)
    assert n == 1
    assert "#### EN" not in out
    assert '<span id="page-9-0"></span>' in out


def test_preserves_trailing_newline() -> None:
    md = "# T\n## C\n###### EN\n"
    out, _ = demote_orphan_fragments(md)
    assert out.endswith("\n")


# --- _is_short_fragment --------------------------------------------------


def test_is_short_fragment_true_for_codes() -> None:
    assert _is_short_fragment("EN") is True
    assert _is_short_fragment("ABC") is True  # len <= 3
    assert _is_short_fragment("") is True
    assert _is_short_fragment("•") is True  # no word char


def test_is_short_fragment_false_for_real_text() -> None:
    assert _is_short_fragment("ABCD") is False  # 4 chars, has word char
    assert _is_short_fragment("Real Section Name") is False


# --- _has_substantive_body -----------------------------------------------


def test_body_true_for_paragraph() -> None:
    lines = ["#### DAT", "", "Digital Audio Tape recorder.", "#### Next"]
    assert _has_substantive_body(lines, 0, 3) is True


def test_body_false_when_next_line_is_heading() -> None:
    lines = ["###### EN", "# 1. Operational Overview", "body"]
    assert _has_substantive_body(lines, 0, 1) is False


def test_body_false_for_blank_only() -> None:
    lines = ["###### E", "", "## Effects Processing"]
    assert _has_substantive_body(lines, 0, 2) is False


def test_body_false_for_image_only() -> None:
    lines = ["## 13", "", "![](images/x.png)", "## 14"]
    assert _has_substantive_body(lines, 0, 3) is False


def test_body_false_for_pagespan_only() -> None:
    lines = ["###### EN", '<span id="page-4-0"></span>', "# Next"]
    assert _has_substantive_body(lines, 0, 2) is False


def test_body_handles_eof_end_idx() -> None:
    lines = ["###### E", ""]
    assert _has_substantive_body(lines, 0, len(lines)) is False


def test_body_scans_past_skipped_lines() -> None:
    lines = [
        "#### X",
        "",
        "## Heading In Range",
        "![](images/y.png)",
        "real definition text.",
        "#### Next",
    ]
    assert _has_substantive_body(lines, 0, 5) is True
