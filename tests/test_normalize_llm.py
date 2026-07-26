# --- de-headify-only mode ----------------------------------------------------
#
# `llm_dehead` asks one question per heading (real section or extractor junk)
# and never reassigns levels.


def test_parse_dehead_response_maps_drop_to_level_zero() -> None:
    from pagespeak.services._normalize_llm import _parse_dehead_response

    out = _parse_dehead_response("1: KEEP\n2: DROP\n3: KEEP\n4: DROP\n")
    assert out == {2: 0, 4: 0}


def test_parse_dehead_response_ignores_commentary_and_case() -> None:
    from pagespeak.services._normalize_llm import _parse_dehead_response

    out = _parse_dehead_response("Here you go:\n1: keep\n2: drop\n```\nnonsense\n")
    assert out == {2: 0}


def test_parse_dehead_response_empty_when_nothing_dropped() -> None:
    from pagespeak.services._normalize_llm import _parse_dehead_response

    assert _parse_dehead_response("1: KEEP\n2: KEEP\n") == {}


def test_dehead_prompt_carries_headings_and_forbids_leveling() -> None:
    from pagespeak.services._heading_normalize import _HeadingRecord
    from pagespeak.services._normalize_llm import _build_prompt_dehead

    hs = [
        _HeadingRecord(line_index=0, level=2, text="Real Section"),
        _HeadingRecord(line_index=4, level=3, text="Note"),
    ]
    prompt = _build_prompt_dehead(hs, ["body about the section", ""], include_anchors=True)
    assert "1: 2 Real Section" in prompt
    assert "body about the section" in prompt
    assert "KEEP" in prompt and "DROP" in prompt
    # The contract that makes this mode safe.
    assert "never change heading levels" in prompt.lower()


# --- parent guard -------------------------------------------------------------
#
# A heading owning child headings is a real section whatever its own body
# looks like; junk is always a leaf.


def _rec(level: int, text: str, line: int):
    from pagespeak.services._heading_normalize import _HeadingRecord

    return _HeadingRecord(line_index=line, level=level, text=text)


def test_parent_guard_refuses_to_drop_a_heading_with_children() -> None:
    from pagespeak.services._normalize_llm import _guard_parent_drops

    heads = [_rec(2, "Zone output", 0), _rec(3, "Multi-zone output", 10)]
    # The model asked to drop both parent and child.
    out = _guard_parent_drops({1: 0, 2: 0}, heads)
    assert 1 not in out, "parent must survive"
    assert out == {2: 0}, "the leaf child may still drop"


def test_parent_guard_allows_leaf_drops() -> None:
    from pagespeak.services._normalize_llm import _guard_parent_drops

    heads = [_rec(2, "Real Section", 0), _rec(2, "Note", 10), _rec(2, "Also Real", 20)]
    assert _guard_parent_drops({2: 0}, heads) == {2: 0}


def test_parent_guard_allows_dropping_the_last_heading() -> None:
    from pagespeak.services._normalize_llm import _guard_parent_drops

    heads = [_rec(1, "Doc", 0), _rec(6, "Trailing furniture", 40)]
    assert _guard_parent_drops({2: 0}, heads) == {2: 0}


def test_parent_guard_ignores_a_shallower_successor() -> None:
    """A sibling or an uncle is not a child — such a heading is still a leaf."""
    from pagespeak.services._normalize_llm import _guard_parent_drops

    heads = [_rec(2, "Chapter A", 0), _rec(3, "Note", 10), _rec(2, "Chapter B", 20)]
    assert _guard_parent_drops({2: 0}, heads) == {2: 0}


def test_parent_guard_is_a_noop_when_nothing_is_dropped() -> None:
    from pagespeak.services._normalize_llm import _guard_parent_drops

    heads = [_rec(1, "A", 0), _rec(2, "B", 5)]
    assert _guard_parent_drops({}, heads) == {}


# ── body guard ──────────────────────────────────────────────────────────
#
# A heading owning its own body is a section boundary: dropping it merges the
# prose into the section above and the content stops being independently
# retrievable. Recurring furniture is exempt so the guard cannot re-admit
# every `Note` in a manual.


def _doc(blocks: list[tuple[int, str, str]]):
    """Build (markdown, headings) from (level, text, body) triples.

    Keeps each record's `line_index` honest against the rendered markdown,
    which is what `_extract_body_anchors` slices on.
    """
    lines: list[str] = []
    heads = []
    for level, text, body in blocks:
        heads.append(_rec(level, text, len(lines)))
        lines.append(f"{'#' * level} {text}")
        lines.extend(body.splitlines())
    return "\n".join(lines), heads


_LONG = "This section explains the procedure in enough words to clear the guard threshold."
_SHORT = "See above."


def test_body_guard_refuses_to_drop_a_heading_owning_a_body() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(2, "Connecting a digital optical cable", _LONG)])
    kept, refused = _guard_body_drops({1: 0}, heads, md)
    assert kept == {}, "a heading with its own prose must survive"
    assert refused == 1


def test_body_guard_allows_dropping_a_bodyless_heading() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(2, "Contents", ""), (2, "Real Section", _LONG)])
    kept, refused = _guard_body_drops({1: 0}, heads, md)
    assert kept == {1: 0}, "a heading owning nothing may still drop"
    assert refused == 0


def test_body_guard_allows_dropping_a_thin_body() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(2, "Note", _SHORT), (2, "Real Section", _LONG)])
    assert _guard_body_drops({1: 0}, heads, md) == ({1: 0}, 0)


def test_body_guard_exempts_recurring_furniture() -> None:
    """Running headers repeat; a section title does not. The exemption is what
    keeps the guard from protecting every admonition in a manual."""
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(3, "Note", _LONG)] * 30)
    kept, refused = _guard_body_drops({i: 0 for i in range(1, 31)}, heads, md)
    assert refused == 0, "30 identical headings are furniture, body or not"
    assert len(kept) == 30


def test_body_guard_protects_a_heading_recurring_below_the_cap() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(3, "Overview", _LONG)] * 5)
    _, refused = _guard_body_drops({i: 0 for i in range(1, 6)}, heads, md)
    assert refused == 5, "a handful of repeats is a per-chapter section, not furniture"


def test_body_guard_leaves_relevel_verdicts_untouched() -> None:
    """`llm_full` re-levels as well as drops; only the level-0 sentinel is ours."""
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(4, "Antenna jacks", _LONG), (4, "Spec table", _LONG)])
    kept, refused = _guard_body_drops({1: 2, 2: 0}, heads, md)
    assert kept == {1: 2}, "a re-level must pass through unchanged"
    assert refused == 1


def test_body_guard_is_a_noop_when_nothing_is_dropped() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(1, "A", _LONG), (2, "B", _LONG)])
    assert _guard_body_drops({}, heads, md) == ({}, 0)


def test_body_guard_thresholds_are_env_tunable(monkeypatch) -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(2, "Note", _SHORT)])
    assert _guard_body_drops({1: 0}, heads, md) == ({1: 0}, 0)
    monkeypatch.setenv("PAGESPEAK_DEHEAD_GUARD_MIN_BODY_WORDS", "2")
    assert _guard_body_drops({1: 0}, heads, md) == ({}, 1)
    monkeypatch.setenv("PAGESPEAK_DEHEAD_GUARD_MAX_RECURRENCE", "0")
    assert _guard_body_drops({1: 0}, heads, md) == ({1: 0}, 0)


def test_body_guard_ignores_an_out_of_range_index() -> None:
    from pagespeak.services._normalize_llm import _guard_body_drops

    md, heads = _doc([(2, "A", _LONG)])
    assert _guard_body_drops({9: 0}, heads, md) == ({9: 0}, 0)


# ── every mode keys its cache on its OWN prompt version ─────────────────
#
# A mode that falls back to another's constant cannot be invalidated by
# bumping its prompt — a fixed prompt would silently replay old verdicts,
# and a dehead DROP verdict deletes a heading.


def test_each_mode_keys_on_its_own_prompt_version(monkeypatch) -> None:
    import importlib

    import pagespeak.prompts._heading_normalize_dehead as dh
    import pagespeak.services._normalize_llm as nl

    heads = [_rec(1, "A", 0), _rec(2, "B", 4)]
    before = nl._cache_key(heads, "model", mode="llm_dehead")
    monkeypatch.setattr(
        dh,
        "HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION",
        dh.HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION + 1,
    )
    importlib.reload(nl)
    try:
        after = nl._cache_key(heads, "model", mode="llm_dehead")
        assert before != after, "bumping the dehead prompt must invalidate its cache"
    finally:
        monkeypatch.undo()
        importlib.reload(nl)


def test_modes_do_not_share_a_cache_key() -> None:
    from pagespeak.services._normalize_llm import _cache_key

    heads = [_rec(1, "A", 0)]
    keys = {m: _cache_key(heads, "model", mode=m) for m in ("llm", "llm_full", "llm_dehead")}
    assert len(set(keys.values())) == 3, f"modes share a key: {keys}"
