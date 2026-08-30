"""Fenced-code awareness: a `#` inside a fence is a comment, never a heading."""

from __future__ import annotations

from pagespeak.services._fences import apply_outside_fences, fence_flags


def test_flags_mark_the_block_and_its_delimiters() -> None:
    lines = ["# H", "```bash", "# comment", "```", "# H2"]
    assert fence_flags(lines) == [False, True, True, True, False]


def test_tilde_fence_is_tracked() -> None:
    lines = ["~~~", "# comment", "~~~", "# H"]
    assert fence_flags(lines) == [True, True, True, False]


def test_a_tilde_does_not_close_a_backtick_block() -> None:
    """Mixed delimiters must not end a block early."""
    lines = ["```", "~~~", "# still code", "```", "# heading"]
    assert fence_flags(lines) == [True, True, True, True, False]


def test_unclosed_fence_swallows_the_rest() -> None:
    """Safer to skip than to rewrite what may be code."""
    assert fence_flags(["# H", "```", "# code", "# more"]) == [False, True, True, True]


def test_indented_fence_is_recognised() -> None:
    assert fence_flags(["  ```", "  # code", "  ```"]) == [True, True, True]


def test_no_module_hand_rolls_its_own_fence_tracker() -> None:
    """`services/_fences.py` is the one fence notion.

    Seven modules once carried five incompatible ones — tilde fences and
    mismatched delimiters were handled differently in each, so a code sample
    was entity-decoded in one pass and preserved in the next. A rule did not
    hold that line; this gate does.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "pagespeak"
    canonical = src / "services" / "_fences.py"
    pattern = re.compile(r"""(?:```|~~~|`\{3,\}|~\{3,\})""")
    offenders = []
    for path in src.rglob("*.py"):
        if path == canonical:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "re.compile" in line and pattern.search(line):
                offenders.append(f"{path.relative_to(src)}:{i}: {line.strip()}")
    assert not offenders, "hand-rolled fence regex — use services/_fences.py:\n" + "\n".join(
        offenders
    )


def test_split_by_fences_round_trips_exactly() -> None:
    from pagespeak.services._fences import split_by_fences

    text = "a\n\n```\ncode\n```\n\nb\n"
    assert "\n".join(seg for seg, _ in split_by_fences(text)) == text


def test_split_by_fences_marks_a_tilde_block() -> None:
    from pagespeak.services._fences import split_by_fences

    segs = split_by_fences("prose\n~~~\ncode\n~~~\nmore\n")
    assert [fenced for _, fenced in segs] == [False, True, False]
    assert "code" in [s for s, f in segs if f][0]


def test_transform_outside_fences_leaves_tilde_blocks_alone() -> None:
    from pagespeak.services._fences import transform_outside_fences

    text = "PROSE\n~~~\nCODE\n~~~\n"
    assert transform_outside_fences(text, str.lower) == "prose\n~~~\nCODE\n~~~\n"


def test_apply_skips_fenced_lines_and_counts_only_real_edits() -> None:
    text = "# a\n```\n# b\n```\n# c\n"
    out, n = apply_outside_fences(text, lambda ln: ln.replace("#", "##"))
    assert out == "## a\n```\n# b\n```\n## c\n"
    assert n == 2


def test_trailing_newline_is_preserved() -> None:
    assert apply_outside_fences("# a\n", lambda ln: ln)[0] == "# a\n"
    assert apply_outside_fences("# a", lambda ln: ln)[0] == "# a"


def test_info_string_on_the_fence_is_handled() -> None:
    lines = ["```python title=foo.py", "# not a heading", "```"]
    assert fence_flags(lines) == [True, True, True]


# ── end-to-end: a fenced code block must survive the whole pipeline ─────


def test_fenced_code_survives_convert_and_split(tmp_path) -> None:
    """The audit's C1 case: shell comments in a bash fence must not become
    headings, must not be re-levelled, and must not split the block."""
    from pagespeak import to_markdown

    src = tmp_path / "guide.md"
    src.write_text(
        "# Prerequisites\n\nInstall the toolchain.\n\n```bash\n"
        "# Update the package index first\nsudo apt update\n"
        "# 2.1 is the minimum supported version\nsudo apt install toolchain=2.1\n"
        "```\n\nThen continue.\n"
    )
    out = tmp_path / "out"
    result = to_markdown(src, output_dir=out, diagrams=False, split_sections=True)
    lines = result.markdown.splitlines()
    for verbatim in (
        "# Update the package index first",
        "sudo apt update",
        "# 2.1 is the minimum supported version",
        "sudo apt install toolchain=2.1",
    ):
        assert verbatim in lines, f"fence body altered: {verbatim!r}"
    assert result.markdown.count("```") % 2 == 0, "unbalanced fence"
    written = {p.name for p in (out / "sections").rglob("*.md")}
    assert "prerequisites.md" in written
    assert not {w for w in written if w.startswith(("update-", "2-1-"))}, (
        f"shell comments became section files: {written}"
    )


def test_parse_sections_ignores_fenced_headings() -> None:
    from pagespeak.services._split_parse import _parse_sections

    doc = "# Real\n\n```bash\n# fake one\n# fake two\n```\n"
    secs = _parse_sections(doc.splitlines(), min_level=1)
    assert [s.title for s in secs] == ["Real"]


# ── nothing that rewrites markdown may touch a fenced line ─────────────
#
# The audit found twelve heading scanners fence-blind while five siblings
# were correct. This sweeps every whole-text transform so a new pass that
# forgets `fence_flags` fails here rather than corrupting a corpus.

_FENCED_LINES = [
    "# 1 Configure the daemon",
    "# 1.2 Tune the buffer",
    "## A very long sentence that certainly reads as prose rather than a heading, yes.",
    "# S K E L E T A L",
    "# 1984",
    "## Notes Notes",
]

_SWEEP_MODULES = [
    "_cleanup",
    "_cleanup_structure",
    "_fragments",
    "_listish_headings",
    "_enumerated_nest",
    "_outline",
    "_cleanup_diagnose",
    "_h1_ratio_rebalance",
    "_flat_source_demote",
    "_normalize_repair",
    "_heading_normalize",
    "_split_parse",
]

# per-line helpers: they take ONE line, so they cannot know about fences —
# their callers are swept instead.
_PER_LINE_HELPERS = {"heading_slug", "strip_emphasis_from_heading"}


def test_no_whole_text_transform_rewrites_fenced_lines() -> None:
    import importlib
    import inspect

    doc = (
        "# Real Heading\n\nSome text.\n\n```bash\n"
        + "\n".join(_FENCED_LINES)
        + "\necho done\n```\n\nMore text.\n\n## Second Real\n"
    )
    offenders: list[str] = []
    for mod_name in _SWEEP_MODULES:
        mod = importlib.import_module(f"pagespeak.services.{mod_name}")
        for fn_name, fn in vars(mod).items():
            if not inspect.isfunction(fn) or fn.__module__ != mod.__name__:
                continue
            if fn_name.startswith("_") or fn_name in _PER_LINE_HELPERS:
                continue
            try:
                params = list(inspect.signature(fn).parameters.values())
                if not params or params[0].annotation not in ("str", str):
                    continue
                result = fn(doc)
            except Exception:
                continue
            out = result[0] if isinstance(result, tuple) else result
            if not isinstance(out, str):
                continue
            lost = [ln for ln in _FENCED_LINES if ln not in out.splitlines()]
            if lost:
                offenders.append(f"{mod_name}.{fn_name} altered {lost[0]!r}")
    assert not offenders, "fence-blind transforms:\n  " + "\n  ".join(offenders)


def test_a_shorter_run_does_not_close_a_longer_fence() -> None:
    """CommonMark: the closing fence must be at least as long as the opener. A
    doc that shows fenced markdown wraps it in a longer fence; closing on the
    inner one leaks the sample out to every fence-aware pass."""
    lines = ["````markdown", "```", "# not a heading", "```", "````", "# H"]
    assert fence_flags(lines) == [True, True, True, True, True, False]


def test_a_shorter_tilde_run_does_not_close_a_longer_one() -> None:
    lines = ["~~~~", "~~~", "# not a heading", "~~~", "~~~~", "# H"]
    assert fence_flags(lines) == [True, True, True, True, True, False]


def test_a_longer_run_does_close_a_shorter_fence() -> None:
    """Only the minimum is specified, so a longer closer is still a closer."""
    lines = ["```", "code", "`````", "# H"]
    assert fence_flags(lines) == [True, True, True, False]


def test_unclosed_fence_warns_because_the_rest_goes_inert(caplog) -> None:
    """A closer shorter than its opener no longer closes, so a malformed
    document can mark everything after the opener fenced. Correct per
    CommonMark, but silent whole-document inertness needs to be visible."""
    lines = ["# Real", "````", "code", "```", "# Swallowed", "more"]
    with caplog.at_level("WARNING"):
        flags = fence_flags(lines)
    assert flags == [False, True, True, True, True, True]
    assert "fence_unclosed_at_eof" in caplog.text
    assert "line=2" in caplog.text


def test_a_closed_fence_does_not_warn(caplog) -> None:
    with caplog.at_level("WARNING"):
        fence_flags(["```", "code", "```", "# H"])
    assert "fence_unclosed_at_eof" not in caplog.text
