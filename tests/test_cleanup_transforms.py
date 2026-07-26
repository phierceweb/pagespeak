"""Per-line cleanup transforms: numbered-section depth locking."""

from __future__ import annotations

# ── fence handling: entities decode OUTSIDE fences, never inside ───────────


def test_entities_decode_in_prose_and_survive_in_a_backtick_fence() -> None:
    """The inversion bug: a lone ``` in prose opened a phantom block, so the
    prose entity stayed encoded and the real code sample got decoded."""
    from pagespeak.services._cleanup_transforms import decode_html_entities

    out = decode_html_entities(
        "Press ``` to open a fence.\n&lt;b&gt;\n\n```\npython &lt;c&gt;\n```\n"
    )
    assert "<b>" in out, f"prose entity did not decode:\n{out}"
    assert "&lt;c&gt;" in out, f"fenced entity was decoded:\n{out}"


def test_entities_survive_in_a_tilde_fence() -> None:
    from pagespeak.services._cleanup_transforms import decode_html_entities

    out = decode_html_entities("prose &lt;a&gt;\n\n~~~\n&lt;b&gt;code&lt;/b&gt;\n~~~\n")
    assert "<a>" in out
    assert "&lt;b&gt;code&lt;/b&gt;" in out, f"tilde-fenced entity was decoded:\n{out}"


def test_entity_inversion_end_to_end_through_cleanup() -> None:
    """The shipping defect, at the level a consumer sees it."""
    from pagespeak.services._cleanup import cleanup_markdown

    out = cleanup_markdown(
        "Spec says T3 &lt; 34F and A &amp; B.\n\n```\ncode &lt;x&gt;\n```\n", level="basic"
    )
    assert "T3 < 34F and A & B" in out, f"prose entity not decoded:\n{out}"
    assert "&lt;x&gt;" in out, f"fenced entity decoded:\n{out}"


def test_shattered_emphasis_is_not_collapsed_inside_a_tilde_fence() -> None:
    from pagespeak.services._cleanup_transforms import collapse_shattered_emphasis

    out = collapse_shattered_emphasis("prose ****x****\n\n~~~\n****literal****\n~~~\n")
    assert "**x**" in out
    assert "****literal****" in out, f"tilde-fenced asterisks collapsed:\n{out}"


# ── uppercase letter-suffixed subsections ───────────────────────────────
#
# `1.3A Transport` is a subsection of `1.3`, one level deeper. Only the
# lowercase form was recognised before, so uppercase-suffixed manuals kept
# whatever (often inverted) level the backend guessed.


def test_uppercase_suffix_is_left_to_the_run_pass() -> None:
    from pagespeak.services._cleanup_transforms import lock_numbered_section_depth

    assert lock_numbered_section_depth("## 1.3 OVERVIEW") == "## 1.3 OVERVIEW"
    assert lock_numbered_section_depth("## 1.3A Transport") == "## 1.3A Transport"


def test_lowercase_letter_suffix_still_works() -> None:
    from pagespeak.services._cleanup_transforms import lock_numbered_section_depth

    assert lock_numbered_section_depth("## 2.3a Buffer") == "### 2.3a Buffer"


def test_a_unit_is_not_a_subsection() -> None:
    """`3.5GHz` / `1.5V` are measurements, not subsections."""
    from pagespeak.services._cleanup_transforms import lock_numbered_section_depth

    for line in ("# 3.5GHz Band", "# 2.3ab Thing", "# 1.5V Rail"):
        assert lock_numbered_section_depth(line) == line, line


def test_uppercase_run_is_levelled_but_a_lone_match_is_not() -> None:
    """A lettered outline arrives as a RUN; `1.5V` arrives alone."""
    from pagespeak.services._cleanup_diagnose import lock_lettered_subsection_runs_pass

    run = "## 1.3A Transport\n## 1.3B Record\n## 1.3C Punch\n"
    out, n = lock_lettered_subsection_runs_pass(run)
    assert n == 3 and all(ln.startswith("### ") for ln in out.splitlines() if ln.strip())
    lone = "# 1.5V Rail\n"
    assert lock_lettered_subsection_runs_pass(lone) == (lone, 0)


def test_inversion_is_repaired_end_to_end() -> None:
    """The parent must end up shallower than its lettered children."""
    from pagespeak.services._cleanup_diagnose import (
        lock_lettered_subsection_runs_pass,
        lock_numbered_section_depth_pass,
    )

    src = "##### 1.3 OVERVIEW\n## 1.3A Transport\n## 1.3B Record\n"
    out, _ = lock_numbered_section_depth_pass(src)
    out, _ = lock_lettered_subsection_runs_pass(out)
    depths = [len(ln) - len(ln.lstrip("#")) for ln in out.splitlines() if ln.startswith("#")]
    assert depths[0] < depths[1], f"parent must be shallower: {out}"
    assert depths[1] == depths[2], "siblings must match"
