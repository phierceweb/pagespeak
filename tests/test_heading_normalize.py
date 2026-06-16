"""Tests for pagespeak._heading_normalize."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.services._heading_normalize import (
    _CLAUDE_CODE_TIMEOUT_S_DEFAULT,
    NormalizeData,
    _apply_normalization,
    _build_prompt,
    _cache_key,
    _claude_code_timeout_s,
    _extract_headings,
    _HeadingRecord,
    _heuristic_level_for,
    _is_structural_heading,
    _parse_response,
    _resolve_model,
    _select_structural_headings,
    _strip_marker_pollution,
    apply_normalization,
    gather_normalize_levels,
    normalize_heading_levels,
)


def test_extract_headings_finds_all_levels() -> None:
    md = "# H1\nbody\n## H2\nmore body\n#### H4\n###### H6\nregular paragraph\n## H2 again\n"
    headings = _extract_headings(md)
    assert [(h.level, h.text) for h in headings] == [
        (1, "H1"),
        (2, "H2"),
        (4, "H4"),
        (6, "H6"),
        (2, "H2 again"),
    ]
    # Line indices are 0-based.
    assert headings[0].line_index == 0
    assert headings[1].line_index == 2


def test_extract_headings_ignores_seven_hashes() -> None:
    """Markdown only allows 1-6 hashes for headings; `####### Foo` is text."""
    md = "# Real\n####### Not a heading\n## Another\n"
    headings = _extract_headings(md)
    assert [h.text for h in headings] == ["Real", "Another"]


def test_parse_response_picks_up_level_lines() -> None:
    response = "1: 3\n2: 4\n3: 4\n4: 3\n"
    levels = _parse_response(response)
    assert levels == {1: 3, 2: 4, 3: 4, 4: 3}


def test_parse_response_skips_garbage_lines() -> None:
    """LLM occasionally includes commentary; we ignore non-matching lines."""
    response = "Here are the levels:\n1: 3\nthinking...\n2: 4\nDone!\n"
    levels = _parse_response(response)
    assert levels == {1: 3, 2: 4}


def test_parse_response_ignores_out_of_range_levels() -> None:
    """Levels outside 0..6 are dropped. `0` is the v4 de-headify sentinel
    (apply step strips the `#` prefix entirely), `7+` is invalid markdown."""
    response = "1: 0\n2: 7\n3: 4\n4: -1\n"
    levels = _parse_response(response)
    assert levels == {1: 0, 3: 4}


def test_apply_normalization_de_headifies_on_level_zero() -> None:
    """v4: `level == 0` strips the `#` prefix, leaving the text as a paragraph."""
    md = "## Real Section\nbody\n## Important note:\ninline callout body\n## Another Real\nmore\n"
    headings = _extract_headings(md)
    out = _apply_normalization(md, headings, {1: 2, 2: 0, 3: 2})
    lines = out.splitlines()
    # Item 1 unchanged, item 2 de-headified, item 3 unchanged.
    assert lines[0] == "## Real Section"
    assert lines[2] == "Important note:"
    assert lines[4] == "## Another Real"


def test_apply_normalization_de_headify_treats_zero_distinct_from_missing() -> None:
    """`levels.get(idx) is None` means "no rewrite"; `0` means "de-headify".
    The two must not collapse."""
    md = "## Keep me\nbody\n## Strip me\nmore\n"
    headings = _extract_headings(md)
    # Item 1 missing from dict → untouched. Item 2 set to 0 → de-headified.
    out = _apply_normalization(md, headings, {2: 0})
    lines = out.splitlines()
    assert lines[0] == "## Keep me"
    assert lines[2] == "Strip me"


def test_apply_normalization_rewrites_levels() -> None:
    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nmore\n"
    headings = _extract_headings(md)
    out = _apply_normalization(md, headings, {1: 3, 2: 4})
    assert out == "### Chapter 1 Intro\nbody\n#### 1.1 Foo\nmore"


def test_apply_normalization_skips_unchanged_levels() -> None:
    md = "## Foo\nbody\n## Bar\nmore\n"
    headings = _extract_headings(md)
    # 1: same level, 2: missing → both untouched.
    out = _apply_normalization(md, headings, {1: 2})
    assert "## Foo" in out
    assert "## Bar" in out


def test_normalize_promotes_chapter_above_subsections() -> None:
    """End-to-end: the flattened shape — chapter and subsections at the
    same level — gets the chapter promoted one shallower."""
    md = (
        "#### Chapter 1 Introduction\n"
        "intro\n"
        "#### 1.1 Foo\n"
        "foo body\n"
        "#### 1.2 Bar\n"
        "bar body\n"
        "#### Chapter 2 Methods\n"
        "methods body\n"
    )

    def fake_invoke(prompt: str) -> str:
        # Mock LLM response: promote chapters from 4 to 3.
        return "1: 3\n2: 4\n3: 4\n4: 3\n"

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke)
    assert "### Chapter 1 Introduction" in out
    assert "### Chapter 2 Methods" in out
    assert "#### 1.1 Foo" in out
    assert "#### 1.2 Bar" in out


def test_normalize_no_op_when_response_empty() -> None:
    md = "## Foo\nbody\n## Bar\nmore\n"

    def fake_invoke(prompt: str) -> str:
        return ""

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke)
    # Nothing to apply → return original.
    assert out == md


def test_normalize_no_op_when_invoke_raises() -> None:
    """A backend error must not break the pipeline — we log and return
    the original markdown."""
    md = "## Foo\nbody\n## Bar\nmore\n"

    def fake_invoke(prompt: str) -> str:
        raise RuntimeError("backend exploded")

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke)
    assert out == md


def test_normalize_skips_when_too_few_headings() -> None:
    """Single heading → no renormalization to do; skip the LLM call."""
    md = "## Only heading\nbody\n"
    calls = 0

    def fake_invoke(prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "1: 3\n"

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke)
    assert calls == 0
    assert out == md


def test_normalize_caches_response_on_disk(tmp_path: Path) -> None:
    """First call shells out (mock); second call reads cache and skips
    the invoker."""
    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nmore\n"
    cache_dir = tmp_path / "cache"
    invoke_count = 0

    def fake_invoke(prompt: str) -> str:
        nonlocal invoke_count
        invoke_count += 1
        return "1: 3\n2: 4\n"

    out1 = normalize_heading_levels(md, mode="llm", invoke=fake_invoke, cache_dir=cache_dir)
    assert invoke_count == 1
    assert "### Chapter 1 Intro" in out1
    # Cache file exists with response payload.
    cache_files = list(cache_dir.glob("*.json"))
    assert len(cache_files) == 1
    cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cached["response"] == "1: 3\n2: 4\n"

    # Second call hits the cache, no extra invoke.
    out2 = normalize_heading_levels(md, mode="llm", invoke=fake_invoke, cache_dir=cache_dir)
    assert invoke_count == 1
    assert out2 == out1


def test_cache_key_changes_when_headings_change() -> None:
    md_a = "## Foo\nbody\n## Bar\nmore\n"
    md_b = "## Foo\nbody\n## Baz\nmore\n"
    headings_a = _extract_headings(md_a)
    headings_b = _extract_headings(md_b)
    assert _cache_key(headings_a, model=None) != _cache_key(headings_b, model=None)


def test_cache_key_changes_when_model_changes() -> None:
    md = "## Foo\nbody\n## Bar\nmore\n"
    headings = _extract_headings(md)
    assert _cache_key(headings, model="haiku") != _cache_key(headings, model="sonnet")


# --- Marker TOC-pollution stripping ------------------------------


def test_strip_marker_pollution_removes_span_anchor_tags() -> None:
    """Marker injects `<span id="page-X-Y"></span>` before heading text
    when the source PDF has a TOC. Strip these so the LLM sees clean
    title text, not anchor wrapping."""
    assert _strip_marker_pollution('<span id="page-48-0"></span>The Widget') == "The Widget"
    # Self-closing-style with whitespace.
    assert _strip_marker_pollution('<span id="page-123-0" ></span>  Casing') == "Casing"


def test_strip_marker_pollution_unwraps_page_link_syntax() -> None:
    """Marker wraps chapter titles in `[label](#page-X-Y)` cross-reference
    links pointing back at the TOC. Strip the link, keep the label."""
    assert _strip_marker_pollution("[The Hydraulics](#page-26-0) System") == "The Hydraulics System"
    assert (
        _strip_marker_pollution("[Chapter 5](#page-23-0) Widget Assembly")
        == "Chapter 5 Widget Assembly"
    )


def test_strip_marker_pollution_handles_real_widgetry_example() -> None:
    """A dense Marker pollution shape: span anchor + link wrapping +
    chapter-number link, all on one heading."""
    raw = '<span id="page-462-0"></span>**The Hydraulics](#page-26-0) 15 System: Fluid Lines'
    # Note: the input has unbalanced markdown — pollution stripping is
    # best-effort. We still get the readable title out.
    result = _strip_marker_pollution(raw)
    assert "Hydraulics" in result
    assert "15 System" in result
    assert "span id=" not in result
    assert "#page-" not in result


def test_strip_marker_pollution_preserves_bold_italic_markers() -> None:
    """Markdown formatting markers (`**`, `_`) are semantic — keep them."""
    assert (
        _strip_marker_pollution("**Chapter 5** Widget Assembly") == "**Chapter 5** Widget Assembly"
    )
    assert _strip_marker_pollution("_emphasized_ heading") == "_emphasized_ heading"


def test_strip_marker_pollution_collapses_whitespace_runs() -> None:
    """Stripping leaves whitespace runs where tags/links were; collapse them."""
    assert _strip_marker_pollution('<span id="page-1-0"></span>    Chapter   1') == "Chapter 1"


def test_strip_marker_pollution_is_idempotent() -> None:
    """Cleaning a clean string should produce the same clean string."""
    clean = "Chapter 5 Widget Assembly"
    assert _strip_marker_pollution(clean) == clean


def test_heading_record_clean_text_property() -> None:
    """`clean_text` property returns the pollution-stripped view; the
    original `text` field stays unchanged so apply-step rewrites still
    match the markdown source."""
    h = _HeadingRecord(
        line_index=0,
        level=4,
        text='<span id="page-23-0"></span>[Chapter 5](#page-23-0) Widget Assembly',
    )
    assert h.text.startswith("<span")  # original preserved
    assert h.clean_text == "Chapter 5 Widget Assembly"


def test_is_structural_heading_works_on_polluted_chapter_title() -> None:
    """`_select_structural_headings` now feeds `clean_text` into
    the structural filter, so chapter titles wrapped in Marker's TOC
    link syntax are correctly detected as 'Chapter N' patterns."""
    polluted = '<span id="page-23-0"></span>[Chapter 5](#page-23-0) Widget Assembly'
    # Cleaned version IS structural.
    assert _is_structural_heading(_strip_marker_pollution(polluted))
    # Raw version is NOT structural (doesn't match `^Chapter N`).
    assert not _is_structural_heading(polluted)


def test_select_structural_headings_handles_polluted_titles() -> None:
    """Integration: `_select_structural_headings` correctly picks up
    chapter titles even when Marker has wrapped them in span+link syntax."""
    md = (
        '#### <span id="page-23-0"></span>[Chapter 5](#page-23-0) Widget Assembly\n'
        "body\n"
        '#### <span id="page-48-0"></span>[Chapter 6](#page-24-0) Thermal System\n'
        "body\n"
        "#### Not a chapter\n"
    )
    headings = _extract_headings(md)
    structural = _select_structural_headings(headings)
    # Both polluted chapter headings should be picked up.
    assert len(structural) == 2
    assert "Chapter 5" in structural[0].clean_text
    assert "Chapter 6" in structural[1].clean_text


def test_build_prompt_renders_clean_text_not_raw_text() -> None:
    """The LLM sees `Chapter 5 Widget Assembly`, not
    `<span...>[Chapter 5](#page-X)` etc."""
    md = '## <span id="page-23-0"></span>[Chapter 5](#page-23-0) Widget Assembly\nbody\n'
    headings = _extract_headings(md)
    prompt = _build_prompt(headings)
    assert "Chapter 5 Widget Assembly" in prompt
    assert "span id=" not in prompt
    assert "#page-" not in prompt


def test_cache_key_invalidates_when_pollution_stripping_changes_text() -> None:
    """Cache key now hashes `clean_text`, so two headings whose
    cleaned forms differ produce different keys — even if their raw text
    is similar. The corollary: changing the strip helper's regex set in
    a future version auto-invalidates existing cache."""
    h_raw = _HeadingRecord(0, 2, "Chapter 5 Widget Assembly")
    h_polluted = _HeadingRecord(
        0, 2, '<span id="page-23-0"></span>[Chapter 5](#page-23-0) Widget Assembly'
    )
    # Both clean to the same thing → same cache key.
    assert _cache_key([h_raw], model="m") == _cache_key([h_polluted], model="m")


def test_is_structural_heading_detects_chapter_pattern() -> None:
    assert _is_structural_heading("Chapter 1 Introduction to Widgetry")
    assert _is_structural_heading("chapter 5 The Thermal System")
    assert _is_structural_heading("Chapter 14")  # No subtitle is fine
    assert not _is_structural_heading("Chapters 1-3 Overview")  # Plural — not "Chapter N"
    assert not _is_structural_heading("In Chapter 1 we covered...")


def test_is_structural_heading_detects_numbered_subsections() -> None:
    assert _is_structural_heading("1.1 Organization of the System")
    assert _is_structural_heading("2.5.7 Bank Account Validation")
    assert _is_structural_heading("12.3 Foo bar baz")
    assert not _is_structural_heading("1 Introduction")  # Single number, no dot
    assert not _is_structural_heading("Foo 1.1 bar")  # Number not at start


def test_is_structural_heading_filters_toc_page_entries() -> None:
    """TOC page-number entries pollute the LLM's signal — skip them."""
    assert not _is_structural_heading("1.1 Organization of the System, p. 32")
    assert not _is_structural_heading("Foo, p. 100")
    # Trailing standalone page numbers (Marker emits these for TOC entries).
    assert not _is_structural_heading("1 Introduction to Widgetry 31")
    assert not _is_structural_heading("Core Processing 86")


def test_is_structural_heading_skips_quiz_answer_sentences() -> None:
    """`# 1. Periodic changes in state. Each cycle...` style headings
    are quiz-answer noise from Marker — they have a single number with
    a sentence body. Filter them out."""
    assert not _is_structural_heading("Periodic changes in state. Each cycle the unit")
    assert not _is_structural_heading("Closed but capable of opening. At rest the interlock")


def test_select_structural_headings_pulls_only_eligible() -> None:
    headings = _extract_headings(
        "#### Chapter 1 Intro\nbody\n"
        "#### 1.1 Foo\nbody\n"
        "#### 1.1 Foo, p. 32\nbody\n"  # TOC entry — skipped
        "# 1. Some random sentence with no nested numbering\nbody\n"  # noise — skipped
        "#### 2.1 Bar\nbody\n"
    )
    structural = _select_structural_headings(headings)
    texts = [h.text for h in structural]
    assert texts == ["Chapter 1 Intro", "1.1 Foo", "2.1 Bar"]


def test_normalize_with_filter_only_rewrites_structural() -> None:
    """When filter_structural=True, only structural headings see the
    LLM and only those get rewritten. Quiz-answer noise is left alone."""
    md = (
        "#### Chapter 1 Intro\nbody\n"
        "#### 1.1 Foo\nbody\n"
        "# 1. Quiz answer that should not be touched.\nbody\n"
        "#### Chapter 2 Methods\nbody\n"
    )

    def fake_invoke(prompt: str) -> str:
        # Only 3 structural headings sent. Promote the chapters.
        return "1: 3\n2: 4\n3: 3\n"

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke)
    assert "### Chapter 1 Intro" in out
    assert "### Chapter 2 Methods" in out
    assert "#### 1.1 Foo" in out
    # Quiz answer untouched (still level 1).
    assert "# 1. Quiz answer that should not be touched." in out


def test_normalize_with_filter_disabled_sends_everything() -> None:
    """`filter_structural=False` falls back to the legacy behavior of
    sending every heading."""
    md = "## Foo\nbody\n## Bar\nbody\n## Baz\nbody\n"
    seen_prompts: list[str] = []

    def fake_invoke(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "1: 3\n2: 3\n3: 3\n"

    out = normalize_heading_levels(md, mode="llm", invoke=fake_invoke, filter_structural=False)
    assert len(seen_prompts) == 1
    assert "Foo" in seen_prompts[0]
    assert "Bar" in seen_prompts[0]
    assert "Baz" in seen_prompts[0]
    assert "### Foo" in out


def test_resolve_model_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit `model=` kwarg is still the highest-precedence
    selector and beats YAML + hardcoded default."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_HEADINGS_MODEL", "haiku-from-env")
    assert _resolve_model("explicit-model", mode="llm") == "explicit-model"


def test_resolve_model_llm_full_uses_full_agent_slug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`mode='llm_full'` resolves through the `heading_normalize_full`
    YAML agent block so the two modes can use different models if
    needed (e.g. larger-context model for the big-payload mode)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        """agents:
  heading_normalize:
    backends:
      claude_code:
        model: haiku-for-llm
  heading_normalize_full:
    backends:
      claude_code:
        model: gemini-for-llm-full
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGESPEAK_HEADING_NORMALIZE_BACKEND", "claude_code")
    monkeypatch.setenv("PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND", "claude_code")
    assert _resolve_model(None, mode="llm") == "haiku-for-llm"
    assert _resolve_model(None, mode="llm_full") == "gemini-for-llm-full"


def test_normalize_records_resolved_yaml_model_in_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache file's `model` field reflects the YAML-resolved model so
    cache invalidation kicks in when the YAML config changes.
    legacy `PAGESPEAK_NORMALIZE_HEADINGS_MODEL` env var is ignored —
    only YAML edits invalidate the cache."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        """agents:
  heading_normalize:
    backends:
      claude_code:
        model: haiku-from-yaml
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGESPEAK_HEADING_NORMALIZE_BACKEND", "claude_code")
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_HEADINGS_MODEL", "ignored-env-value")
    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nmore\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n"

    cache_dir = tmp_path / "cache"
    normalize_heading_levels(md, mode="llm", invoke=fake_invoke, cache_dir=cache_dir)
    cache_files = list(cache_dir.glob("*.json"))
    assert len(cache_files) == 1
    cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cached["model"] == "haiku-from-yaml"


def test_build_prompt_includes_indexed_heading_list() -> None:
    md = "## Foo\nbody\n#### 1.1 Bar\nmore\n"
    headings = _extract_headings(md)
    prompt = _build_prompt(headings)
    assert "1: 2 Foo" in prompt
    assert "2: 4 1.1 Bar" in prompt
    # The example in the prompt should still be there.
    assert "Example INPUT" in prompt
    assert "Example OUTPUT" in prompt


# --- gather + apply split ----------------------------------------


def test_gather_normalize_levels_returns_data_no_md_mutation() -> None:
    """gather_normalize_levels is a pure side-file producer: returns
    NormalizeData (or None) but never touches markdown."""
    md = (
        "#### Chapter 1 Intro\nbody\n"
        "#### 1.1 Foo\nbody\n"
        "#### 1.2 Bar\nbody\n"
        "#### Chapter 2 Methods\nbody\n"
    )

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n3: 4\n4: 3\n"

    data = gather_normalize_levels(md, mode="llm", invoke=fake_invoke)
    assert data is not None
    assert isinstance(data, NormalizeData)
    assert data.levels == {1: 3, 2: 4, 3: 4, 4: 3}
    assert data.target_count == 4
    assert data.filter_structural is True


def test_gather_normalize_levels_returns_none_on_invoke_failure() -> None:
    """A backend exception → returns None. Apply treats None as no-op."""
    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n"

    def fake_invoke(prompt: str) -> str:
        raise RuntimeError("backend down")

    data = gather_normalize_levels(md, mode="llm", invoke=fake_invoke)
    assert data is None


def test_apply_normalization_with_none_is_passthrough() -> None:
    md = "## Foo\nbody\n## Bar\nbody\n"
    assert apply_normalization(md, None) == md


def test_apply_normalization_drift_count_skips_safely() -> None:
    """If the heading count has drifted (e.g. cleanup added/removed
    headings between gather and apply), skip apply and return md
    unchanged. Better to under-apply than mis-apply."""
    md_before = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n#### 1.2 Bar\nbody\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n3: 4\n"

    data = gather_normalize_levels(md_before, mode="llm", invoke=fake_invoke)
    assert data is not None
    # md_after has fewer structural headings — drift!
    md_after = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n"
    out = apply_normalization(md_after, data)
    assert out == md_after  # unchanged — skipped due to drift


def test_apply_normalization_drift_text_skips_safely() -> None:
    """Same heading count but text changed at gather-time index 1 →
    skip apply. Defends against silent re-ordering."""
    md_before = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n#### 1.2 Bar\nbody\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n3: 4\n"

    data = gather_normalize_levels(md_before, mode="llm", invoke=fake_invoke)
    assert data is not None
    # Same count but Chapter 1 text differs.
    md_after = "#### Chapter 1 Different Title\nbody\n#### 1.1 Foo\nbody\n#### 1.2 Bar\nbody\n"
    out = apply_normalization(md_after, data)
    assert out == md_after  # unchanged — skipped due to text drift


def test_apply_normalization_clean_apply_no_drift() -> None:
    """When the heading list matches what was gathered, apply rewrites
    levels per the LLM's response."""
    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n#### 1.2 Bar\nbody\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n3: 4\n"

    data = gather_normalize_levels(md, mode="llm", invoke=fake_invoke)
    assert data is not None
    out = apply_normalization(md, data)
    assert "### Chapter 1 Intro" in out  # promoted
    assert "#### 1.1 Foo" in out  # unchanged
    assert "#### 1.2 Bar" in out  # unchanged


def test_apply_normalization_with_filter_disabled() -> None:
    """When gather used `filter_structural=False`, apply must use the
    same setting to align indices against the unfiltered heading list."""
    md = "## Foo\nbody\n## Bar\nbody\n## Baz\nbody\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 3\n3: 3\n"

    data = gather_normalize_levels(md, mode="llm", invoke=fake_invoke, filter_structural=False)
    assert data is not None
    assert data.filter_structural is False
    out = apply_normalization(md, data)
    assert "### Foo" in out
    assert "### Bar" in out
    assert "### Baz" in out


# --- heuristic mode -----------------------------------------------


def test_heuristic_chapter_prefix_promotes_to_l1() -> None:
    """`Chapter N <title>` patterns get promoted to L1, regardless of
    Marker's emitted depth (the textbook flatness case)."""
    assert _heuristic_level_for("Chapter 1 Introduction to Widgetry") == 1
    assert _heuristic_level_for("Chapter 14 Calibration") == 1
    assert _heuristic_level_for("CHAPTER 22 Methods") == 1  # case-insensitive


def test_heuristic_multi_part_numbered_depth_from_dots() -> None:
    """Numbered subsections get level = dot count + 1."""
    assert _heuristic_level_for("1.1 Foo Bar") == 2
    assert _heuristic_level_for("1.1.1 Deeper") == 3
    assert _heuristic_level_for("1.1.1.1 Even Deeper") == 4
    assert _heuristic_level_for("2.5.7.3.1 Way Down") == 5


def test_heuristic_caps_at_level_six() -> None:
    """Markdown only goes to L6; deeper numbering caps."""
    assert _heuristic_level_for("1.1.1.1.1.1.1.1 Beyond H6") == 6


def test_heuristic_bare_numbered_chapter_promotes_to_l1() -> None:
    """`14. Title` (no further dots) is treated as a chapter equivalent."""
    assert _heuristic_level_for("14. Widget Calibration") == 1
    assert _heuristic_level_for("1. Introduction") == 1


def test_heuristic_returns_none_for_non_matching() -> None:
    """Non-numbered, non-Chapter headings return None — leave at current level."""
    assert _heuristic_level_for("Introduction") is None
    assert _heuristic_level_for("Quick Start") is None
    assert _heuristic_level_for("References") is None  # backmatter is out of scope
    assert _heuristic_level_for("") is None


def test_heuristic_does_not_invoke_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heuristic mode must NEVER fire the Claude Code subprocess. Patches
    `_claude_code_invoke` and asserts it's never called."""
    md = (
        "#### Chapter 1 Introduction\n"
        "intro body\n\n"
        "#### 1.1 Foo\n"
        "foo body\n\n"
        "#### 1.2 Bar\n"
        "bar body\n"
    )

    invoke_calls: list[str] = []

    def boom(prompt: str, *, model: str | None = None) -> str:
        invoke_calls.append(prompt)
        raise RuntimeError("LLM should not have been invoked")

    monkeypatch.setattr(
        "pagespeak.services._heading_normalize._claude_code_invoke",
        boom,
    )

    data = gather_normalize_levels(md, mode="heuristic")
    assert data is not None
    assert invoke_calls == []
    # Heuristic produced the chapter promotion (L4 → L1).
    out = apply_normalization(md, data)
    assert "# Chapter 1 Introduction" in out
    assert "## 1.1 Foo" in out
    assert "## 1.2 Bar" in out


def test_heuristic_no_cache_writes(tmp_path: Path) -> None:
    """Heuristic mode is fast enough not to need a cache. Asserts no
    cache file is written even when a `cache_dir` is provided."""
    md = "#### Chapter 1 Foo\nbody\n\n#### 1.1 Bar\nbody\n\n#### 1.2 Baz\nbody\n"
    cache_dir = tmp_path / "cache"
    data = gather_normalize_levels(md, mode="heuristic", cache_dir=cache_dir)
    assert data is not None
    # No cache file: directory is either missing or empty.
    if cache_dir.exists():
        assert list(cache_dir.iterdir()) == []


def test_heuristic_returns_none_when_too_few_headings() -> None:
    """Same minimum-heading guard as LLM mode — apply treats None as no-op."""
    md = "# Just one heading\nbody\n"
    assert gather_normalize_levels(md, mode="heuristic") is None


def test_heuristic_default_is_heuristic_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default `gather_normalize_levels(md)` (no `mode=`) MUST be
    heuristic. Cost-protection regression: LLM should be opt-in only."""

    def boom(prompt: str, *, model: str | None = None) -> str:
        raise RuntimeError("default mode must be heuristic, not llm")

    monkeypatch.setattr(
        "pagespeak.services._heading_normalize._claude_code_invoke",
        boom,
    )
    md = "#### Chapter 1 Foo\nbody\n\n#### 1.1 Bar\nbody\n\n#### 1.2 Baz\nbody\n"
    data = gather_normalize_levels(md)  # no mode= — default applies
    assert data is not None
    assert data.target_count == 3


def test_heuristic_filter_structural_off_includes_unfiltered_headings() -> None:
    """When the structural filter is disabled, the heuristic still only
    rewrites headings whose shape matches a rule. Non-matching headings
    pass through unchanged (no level rewrite)."""
    md = "## Chapter 1 Intro\n## Just A Heading\n## 1.1 Foo\n"
    data = gather_normalize_levels(md, mode="heuristic", filter_structural=False)
    assert data is not None
    # Three target headings (all of them, since filter is off).
    assert data.target_count == 3
    # Rewrites only for the two that match a rule (Chapter and 1.1).
    # The bare "Just A Heading" returns None from heuristic and gets no rewrite.
    out = apply_normalization(md, data)
    assert "# Chapter 1 Intro" in out
    assert "## 1.1 Foo" in out
    assert "## Just A Heading" in out  # untouched


def test_claude_code_invoke_constructs_pf_core_client_with_retry_1() -> None:
    """Contract test: `_claude_code_invoke` must construct pf-core's
    `ClaudeCodeClient` with `retry=1` so transient session blips don't
    cause heading normalization to silently drop. Cross-call parity
    with the vision backends (which also adopted retry=1)."""
    from unittest.mock import MagicMock, patch

    from pagespeak.services._heading_normalize import _claude_code_invoke

    with patch("pf_core.clients.claude_code.ClaudeCodeClient") as ctor:
        instance = MagicMock()
        instance.chat.return_value = ("response", {})
        ctor.return_value = instance
        _claude_code_invoke("prompt", model="haiku")

    assert ctor.call_count == 1
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("retry") == 1, (
        f"`_claude_code_invoke` must construct pf-core's ClaudeCodeClient "
        f"with retry=1; got kwargs={kwargs}"
    )


# ============================================================================
# `llm_full` mode
# ============================================================================


def test_extract_body_anchors_returns_text_following_each_heading() -> None:
    from pagespeak.services._heading_normalize import _extract_body_anchors

    md = (
        "# Intro\n"
        "Intro body paragraph one.\n"
        "Intro body paragraph two.\n"
        "## Setup\n"
        "Setup body line.\n"
        "## Usage\n"
        "Usage body line.\n"
    )
    headings = _extract_headings(md)
    anchors = _extract_body_anchors(md, headings)
    assert len(anchors) == 3
    assert "Intro body paragraph one." in anchors[0]
    assert "Intro body paragraph two." in anchors[0]
    assert anchors[1] == "Setup body line."
    assert anchors[2] == "Usage body line."


def test_extract_body_anchors_truncates_at_max_chars() -> None:
    from pagespeak.services._heading_normalize import _extract_body_anchors

    long_body = "x" * 2000
    md = f"# H\n{long_body}\n"
    headings = _extract_headings(md)
    anchors = _extract_body_anchors(md, headings, max_chars=800)
    assert len(anchors) == 1
    assert len(anchors[0]) == 800


def test_extract_body_anchors_truncates_at_next_heading() -> None:
    """Body anchor stops at the next heading, not just at max_chars."""
    from pagespeak.services._heading_normalize import _extract_body_anchors

    md = "# A\nshort.\n# B\nirrelevant.\n"
    headings = _extract_headings(md)
    anchors = _extract_body_anchors(md, headings, max_chars=800)
    assert anchors[0] == "short."
    assert anchors[1] == "irrelevant."


def test_extract_body_anchors_returns_empty_string_when_no_body() -> None:
    """Two consecutive headings with no body between them → first
    heading's anchor is empty."""
    from pagespeak.services._heading_normalize import _extract_body_anchors

    md = "# A\n# B\nbody.\n"
    headings = _extract_headings(md)
    anchors = _extract_body_anchors(md, headings)
    assert anchors[0] == ""
    assert anchors[1] == "body."


def test_build_prompt_full_includes_anchors_when_flag_set() -> None:
    from pagespeak.services._heading_normalize import _build_prompt_full

    headings = _extract_headings("# A\nbody a.\n# B\nbody b.\n")
    anchors = ["body a.", "body b."]
    prompt = _build_prompt_full(headings, anchors, include_anchors=True)
    assert "1: 1 A" in prompt
    assert "    body a." in prompt
    assert "2: 1 B" in prompt
    assert "    body b." in prompt


def test_build_prompt_full_omits_anchors_when_flag_unset() -> None:
    from pagespeak.services._heading_normalize import _build_prompt_full

    headings = _extract_headings("# A\nbody a.\n# B\nbody b.\n")
    anchors = ["body a.", "body b."]
    prompt = _build_prompt_full(headings, anchors, include_anchors=False)
    assert "1: 1 A" in prompt
    assert "2: 1 B" in prompt
    assert "body a." not in prompt
    assert "body b." not in prompt


def test_estimate_tokens_chars_over_four() -> None:
    from pagespeak.services._heading_normalize import _estimate_tokens

    assert _estimate_tokens("abcd") == 1
    assert _estimate_tokens("a" * 1000) == 250
    assert _estimate_tokens("") == 0


def test_resolve_max_input_tokens_explicit_arg_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit `override=` still wins (highest precedence)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        "agents:\n  heading_normalize_full:\n    max_input_tokens: 999\n",
        encoding="utf-8",
    )
    from pagespeak.services._heading_normalize import _resolve_max_input_tokens

    assert _resolve_max_input_tokens(override=42) == 42


def test_resolve_max_input_tokens_falls_back_to_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no override, the YAML value is used. The env var
    `PAGESPEAK_NORMALIZE_HEADINGS_MAX_INPUT_TOKENS` is no longer
    consulted."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        "agents:\n  heading_normalize_full:\n    max_input_tokens: 7777\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_HEADINGS_MAX_INPUT_TOKENS", "ignored-env-value")
    from pagespeak.services._heading_normalize import _resolve_max_input_tokens

    assert _resolve_max_input_tokens() == 7777


def test_resolve_max_input_tokens_default_when_yaml_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No override, no config resolving (MODEL_ROUTER_CONFIG points at a
    missing file, so neither cwd nor the packaged default is read) →
    DEFAULT_NORMALIZE_MAX_INPUT_TOKENS."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_ROUTER_CONFIG", str(tmp_path / "missing.yaml"))
    from pagespeak.services._heading_normalize import (
        DEFAULT_NORMALIZE_MAX_INPUT_TOKENS,
        _resolve_max_input_tokens,
    )

    assert _resolve_max_input_tokens() == DEFAULT_NORMALIZE_MAX_INPUT_TOKENS


def test_build_llm_full_prompt_with_gate_under_threshold_keeps_anchors() -> None:
    from pagespeak.services._heading_normalize import _build_llm_full_prompt_with_gate

    md = "# A\nshort body.\n# B\nanother short body.\n"
    headings = _extract_headings(md)
    prompt, included = _build_llm_full_prompt_with_gate(md, headings, max_input_tokens=100_000)
    assert included is True
    assert "short body." in prompt
    assert "another short body." in prompt


def test_build_llm_full_prompt_with_gate_over_threshold_drops_anchors() -> None:
    """Force the gate to fire by setting a tiny threshold. Output should
    NOT include the body anchors (fallback to headings-only)."""
    from pagespeak.services._heading_normalize import _build_llm_full_prompt_with_gate

    md = "# A\n" + ("x" * 800) + "\n# B\n" + ("y" * 800) + "\n"
    headings = _extract_headings(md)
    prompt, included = _build_llm_full_prompt_with_gate(md, headings, max_input_tokens=100)
    assert included is False
    # Anchor strings (the "x"*800 / "y"*800 walls) must not appear.
    assert "x" * 50 not in prompt
    assert "y" * 50 not in prompt
    # Headings themselves are still in the prompt.
    assert "1: 1 A" in prompt
    assert "2: 1 B" in prompt


def test_gather_normalize_levels_llm_full_mode_happy_path() -> None:
    """End-to-end happy path: mode=llm_full sends all headings (no
    structural filter) + anchors to a mocked LLM, parses the response,
    returns a NormalizeData."""
    md = (
        "# Front Panel Controls\n"
        "The device's front panel has controls grouped by function.\n"
        "# Front Panel Knob\n"
        "Press to access input settings.\n"
        "# Volume Knob\n"
        "Adjust output volume.\n"
    )

    captured_prompt: list[str] = []

    def fake_invoke(prompt: str) -> str:
        captured_prompt.append(prompt)
        # LLM correctly identifies that the front-panel and volume
        # knobs are children of the front-panel section.
        return "2: 2\n3: 2\n"

    data = gather_normalize_levels(md, mode="llm_full", invoke=fake_invoke)
    assert data is not None
    assert data.levels == {2: 2, 3: 2}
    # filter_structural is forced False in llm_full mode.
    assert data.filter_structural is False
    # Prompt must include anchors (under-threshold).
    assert "The device's front panel" in captured_prompt[0]


def test_gather_normalize_levels_llm_full_forces_filter_structural_false() -> None:
    """Even if the caller passes `filter_structural=True`, mode=llm_full
    forces it to False internally so the LLM sees all headings."""
    md = "# Unnumbered Title\nbody.\n# Another Unnumbered\nmore.\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 2\n"

    data = gather_normalize_levels(
        md,
        mode="llm_full",
        invoke=fake_invoke,
        filter_structural=True,  # caller asks for filter; mode wins.
    )
    assert data is not None
    assert data.filter_structural is False


def test_cache_key_changes_when_mode_changes() -> None:
    """Same headings + model, different mode → different cache key.
    Prevents llm vs llm_full cache collisions when both have run on
    the same document."""
    md = "## Foo\nbody\n## Bar\nmore\n"
    headings = _extract_headings(md)
    k_llm = _cache_key(headings, model="haiku", mode="llm")
    k_llm_full = _cache_key(headings, model="haiku", mode="llm_full")
    assert k_llm != k_llm_full


def test_heading_normalize_full_prompt_yaml_loads() -> None:
    """The new prompt YAML must load successfully at import time and
    export the required constants. Catches schema breakage early."""
    from pagespeak.prompts._heading_normalize_full import (
        HEADING_NORMALIZE_FULL_PROMPT,
        HEADING_NORMALIZE_FULL_PROMPT_VERSION,
        build_full_prompt,
    )

    assert HEADING_NORMALIZE_FULL_PROMPT_VERSION >= 1
    assert "heading levels" in HEADING_NORMALIZE_FULL_PROMPT
    rendered = build_full_prompt("1: 1 Test heading\n    test body.")
    assert "1: 1 Test heading" in rendered
    assert "test body." in rendered


def test_heading_normalize_full_prompt_is_general_and_corpus_neutral() -> None:
    """The prompt must stay general — principle-based, with placeholder
    examples, never corpus-specific content (real titles, edition labels,
    product trivia). We assert POSITIVE genericness signals — the examples
    use bracketed placeholders, the rules judge by structure — rather than
    listing real corpus strings, so this guard carries no private content
    of its own. If the prompt were re-specified with real names, the author
    would have to replace these placeholders, and the asserts would fail."""
    from pagespeak.prompts._heading_normalize_full import (
        HEADING_NORMALIZE_FULL_PROMPT as p,
    )
    from pagespeak.prompts._heading_normalize_full import (
        HEADING_NORMALIZE_FULL_PROMPT_VERSION as ver,
    )

    assert ver == 8
    low = p.lower()
    # Examples use bracketed placeholders, not real document / product titles.
    assert "[document title]" in low
    assert "[product]" in low
    # Rules are principle-based and cover the three example shapes.
    assert "no level-1 headings" in low  # handles a fully-flat input
    assert "promote" in low  # promotes top-level divisions
    assert "body" in low  # judges structure by body, not by matching labels
    assert "guide" in low  # 2nd example: a single-document guide (title = root)
    assert "inconsistent" in low  # 3rd example: recover from inconsistent chunk levels
    # v7: non-structural demotion names the admonition / step / FAQ shapes by
    # convention (not corpus phrases) and requires them demoted at any depth.
    assert "admonition" in low
    assert "procedure step" in low
    assert "at every depth" in low
    assert "even when the same admonition recurs" in low  # v8: recurring asides still demote
    assert "already placed it correctly" not in p  # the v4 dead assumption stays gone


# ============================================================================
# routing through `_agent_runtime.invoke_agent`
# ============================================================================


def test_normalize_llm_mode_uses_heading_normalize_agent_slug() -> None:
    """`mode="llm"` routes through `invoke_agent("heading_normalize", …)`
    when no `invoke=` test-injection kwarg is supplied. The slug picks
    the matching `config/model_router.yaml` entry."""
    from unittest.mock import patch

    captured_slugs: list[str] = []

    def fake_invoke_agent(slug, *, messages, prompt_version, **kwargs):
        captured_slugs.append(slug)
        return "1: 3\n2: 4\n", None

    md = "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nmore\n"
    with patch("pagespeak._agent_runtime.invoke_agent", side_effect=fake_invoke_agent):
        gather_normalize_levels(md, mode="llm")

    assert captured_slugs == ["heading_normalize"]


def test_normalize_llm_full_mode_uses_heading_normalize_full_agent_slug() -> None:
    """`mode="llm_full"` routes through
    `invoke_agent("heading_normalize_full", …)`."""
    from unittest.mock import patch

    captured_slugs: list[str] = []

    def fake_invoke_agent(slug, *, messages, prompt_version, **kwargs):
        captured_slugs.append(slug)
        return "2: 2\n", None

    md = "# Unnumbered Title\nbody.\n# Another Unnumbered\nmore.\n"
    with patch("pagespeak._agent_runtime.invoke_agent", side_effect=fake_invoke_agent):
        gather_normalize_levels(md, mode="llm_full")

    assert captured_slugs == ["heading_normalize_full"]


def test_normalize_legacy_invoke_kwarg_bypasses_invoke_agent() -> None:
    """When the caller supplies `invoke=`, the legacy direct path is used
    and `invoke_agent` is never called. Preserves the test-injection
    pattern used by ~17 earlier tests."""
    from unittest.mock import patch

    md = "#### Chapter 1\nbody\n#### 1.1 Foo\nmore\n"

    def fake_invoke(prompt: str) -> str:
        return "1: 3\n2: 4\n"

    with patch(
        "pagespeak._agent_runtime.invoke_agent",
        side_effect=AssertionError("invoke_agent must not be called when invoke= set"),
    ):
        gather_normalize_levels(md, mode="llm", invoke=fake_invoke)


def test_claude_code_timeout_returns_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", raising=False)
    assert _claude_code_timeout_s() == _CLAUDE_CODE_TIMEOUT_S_DEFAULT


def test_claude_code_timeout_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", "300")
    assert _claude_code_timeout_s() == 300


def test_claude_code_timeout_falls_back_on_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed env values fall back to the default rather than crashing.
    pf-core's `resolve_int` emits its own structured `env_var_malformed`
    warning (covered by pf-core's tests); we only assert the fall-back
    value here so this test doesn't couple to pf-core's log format."""
    monkeypatch.setenv("PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", "not-an-int")
    assert _claude_code_timeout_s() == _CLAUDE_CODE_TIMEOUT_S_DEFAULT
