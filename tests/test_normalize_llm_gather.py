"""Tests for services._normalize_llm_gather — chunking a heading list too long
for one answer, and stitching the chunks' levels."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from pagespeak.services._heading_normalize import (
    _extract_headings,
    apply_normalization,
    gather_normalize_levels,
)
from pagespeak.services._normalize_llm import _cache_key, _resolve_model
from pagespeak.services._normalize_llm_gather import _aligned, _chunk_bounds

_ENTRY_RE = re.compile(r"^(\d+): \d (.+)$")


def _entries(prompt: str) -> list[tuple[int, str]]:
    """The heading entries a prompt asks about (its own examples excluded)."""
    block = prompt.rsplit("Now process this document:", 1)[-1]
    return [(int(m[1]), m[2]) for line in block.splitlines() if (m := _ENTRY_RE.match(line))]


def _flattened_doc(chapters: int, sections: int) -> str:
    parts = []
    for c in range(1, chapters + 1):
        parts.append(f"#### Chapter {c}\n\nChapter {c} opens here.\n")
        parts += [f"#### {c}.{s} Topic\n\nBody of {c}.{s}.\n" for s in range(1, sections + 1)]
    return "\n".join(parts)


def _leveler(shift_after_first: int = 0) -> tuple[Callable[[str], str], list[str]]:
    """A fake model: chapters at 1, sections at 2; later calls shifted deeper."""
    prompts: list[str] = []

    def invoke(prompt: str) -> str:
        shift = shift_after_first if prompts else 0
        prompts.append(prompt)
        return "\n".join(
            f"{i}: {(1 if text.startswith('Chapter') else 2) + shift}"
            for i, text in _entries(prompt)
        )

    return invoke, prompts


def _levels(md: str) -> list[tuple[int, str]]:
    return [(h.level, h.text) for h in _extract_headings(md)]


def test_a_long_heading_list_is_asked_in_chunks_and_stitched(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)  # 24 headings
    invoke, prompts = _leveler()
    out = apply_normalization(md, gather_normalize_levels(md, mode="llm_full", invoke=invoke))
    assert len(prompts) == 3
    assert all(lv == (1 if text.startswith("Chapter") else 2) for lv, text in _levels(out))


def test_a_chunk_levelled_on_a_deeper_scale_is_brought_back_in_line(monkeypatch) -> None:
    """A chunk that reads its first heading as the document's root nests everything
    one level deeper; the headings it shares with the chunk before set it right."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    invoke, _ = _leveler(shift_after_first=1)
    out = apply_normalization(md, gather_normalize_levels(md, mode="llm_full", invoke=invoke))
    assert all(lv == (1 if text.startswith("Chapter") else 2) for lv, text in _levels(out))


def test_one_short_chunk_answer_refuses_the_whole_document(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    full, prompts = _leveler()

    def invoke(prompt: str) -> str:
        answer = full(prompt)
        return answer if len(prompts) == 1 else answer.splitlines()[0]

    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke) is None


def test_chunk_answers_are_cached(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    invoke, prompts = _leveler()
    first = gather_normalize_levels(md, mode="llm_full", invoke=invoke, cache_dir=tmp_path)
    assert len(prompts) == 3

    def must_not_run(_prompt: str) -> str:
        raise AssertionError("every chunk should come from the cache")

    again = gather_normalize_levels(md, mode="llm_full", invoke=must_not_run, cache_dir=tmp_path)
    assert first is not None and again is not None and again.levels == first.levels


def test_a_usable_whole_document_answer_is_kept(monkeypatch, tmp_path: Path) -> None:
    """A list with a cached whole-list answer keeps it."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    headings = _extract_headings(md)
    whole = "\n".join(
        f"{i}: {1 if h.text.startswith('Chapter') else 2}" for i, h in enumerate(headings, 1)
    )
    key = _cache_key(headings, _resolve_model(None, mode="llm_full"), mode="llm_full")
    (tmp_path / f"{key}.json").write_text(json.dumps({"response": whole}), encoding="utf-8")

    def must_not_run(_prompt: str) -> str:
        raise AssertionError("the cached whole-document answer should be used")

    data = gather_normalize_levels(md, mode="llm_full", invoke=must_not_run, cache_dir=tmp_path)
    assert data is not None and len(data.levels) == len(headings)


def test_dehead_never_drops_a_chunk_opening_heading_as_a_title(monkeypatch) -> None:
    """Each chunk after the first opens on headings the chunk before already
    judged, so a model reading item 1 as the document's title drops nothing."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = "#### Guide\n\nAbout this guide.\n\n" + _flattened_doc(4, 5)

    def invoke(prompt: str) -> str:
        return "\n".join(f"{i}: {'DROP' if i == 1 else 'KEEP'}" for i, _t in _entries(prompt))

    data = gather_normalize_levels(md, mode="llm_dehead", invoke=invoke)
    assert data is not None and data.levels == {1: 0}


def test_a_short_list_is_asked_whole() -> None:
    md = _flattened_doc(2, 3)
    invoke, prompts = _leveler()
    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke) is not None
    assert len(prompts) == 1


@pytest.mark.parametrize(
    ("levels", "size", "bounds"),
    [
        ([1, 2, 2, 1, 2, 2, 2, 2], 5, [(0, 3), (3, 8)]),  # cut at the chapter start
        ([4, 4, 4, 4, 4, 4, 4], 3, [(0, 3), (3, 6), (6, 7)]),  # flat: plain cuts
        ([1, 2, 2], 5, [(0, 3)]),
        ([1, 2, 1] + [2] * 22, 10, [(0, 10), (10, 20), (20, 25)]),  # no chapter within reach
    ],
)
def test_chunk_bounds(levels: list[int], size: int, bounds: list[tuple[int, int]]) -> None:
    assert _chunk_bounds(levels, size) == bounds


def test_a_refused_whole_document_answer_replays_until_rerun(monkeypatch, tmp_path: Path) -> None:
    """A cached short whole-list answer is refused on replay, with no new call:
    a deterministic re-run must not spend. Clearing the cache
    (`--rerun-from normalize`) is what asks again, in chunks."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    headings = _extract_headings(md)
    key = _cache_key(headings, _resolve_model(None, mode="llm_full"), mode="llm_full")
    whole = tmp_path / f"{key}.json"
    whole.write_text(json.dumps({"response": "1: 1\n2: 2\n3: 2\n"}), encoding="utf-8")
    invoke, prompts = _leveler()
    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke, cache_dir=tmp_path) is None
    assert prompts == []

    whole.unlink()
    data = gather_normalize_levels(md, mode="llm_full", invoke=invoke, cache_dir=tmp_path)
    assert len(prompts) == 3
    assert data is not None and len(data.levels) == len(headings)


def test_one_short_chunk_refuses_even_when_the_total_would_pass(monkeypatch) -> None:
    """Nine full chunks and a short tenth clear 90% overall; the short chunk's
    headings would still keep their extracted levels, so nothing is applied."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(20, 4)  # 100 headings, ten chunks
    full, prompts = _leveler()

    def invoke(prompt: str) -> str:
        answer = full(prompt)
        return "\n".join(answer.splitlines()[:5]) if len(prompts) == 10 else answer

    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke) is None
    assert len(prompts) == 10


def test_an_index_past_the_chunk_is_not_a_verdict(monkeypatch) -> None:
    """Chunk 1 answering an index it was never shown must not level the next
    chunk's heading."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    full, prompts = _leveler()

    def invoke(prompt: str) -> str:
        lines = full(prompt).splitlines()
        if len(prompts) == 1:
            return "\n".join([*lines, "11: 1"])
        if len(prompts) == 2:  # leaves heading 11 (its local 4, past 3 shared) unanswered
            return "\n".join(line for line in lines if not line.startswith("4: "))
        return "\n".join(lines)

    data = gather_normalize_levels(md, mode="llm_full", invoke=invoke)
    assert data is not None and 11 not in data.levels


def test_small_chunks_still_share_a_heading_to_align_on(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "5")
    md = _flattened_doc(4, 5)
    invoke, _ = _leveler(shift_after_first=1)
    out = apply_normalization(md, gather_normalize_levels(md, mode="llm_full", invoke=invoke))
    assert all(lv == (1 if text.startswith("Chapter") else 2) for lv, text in _levels(out))


def test_identical_heading_runs_keep_their_own_answers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "4")
    md = "\n".join(f"#### Same\n\nBody {i}.\n" for i in range(12))
    prompts: list[str] = []

    def invoke(prompt: str) -> str:
        prompts.append(prompt)
        return "\n".join(f"{i}: 2" for i, _t in _entries(prompt))

    gather_normalize_levels(md, mode="llm_full", invoke=invoke, cache_dir=tmp_path)
    assert len(prompts) == len(list(tmp_path.glob("*.json"))) == 3


def test_a_lone_title_does_not_set_where_chunks_are_cut() -> None:
    levels = [1] + [2, 3, 3, 3] * 5
    bounds = _chunk_bounds(levels, 6)
    assert all(levels[start] == 2 for start, _end in bounds[1:])


def _scripted(answer: Callable[[int, int, str], int | None]) -> Callable[[str], str]:
    """A fake model answering `answer(call, local index, text)`; None leaves it out."""
    calls: list[str] = []

    def invoke(prompt: str) -> str:
        calls.append(prompt)
        given = [(i, answer(len(calls), i, text)) for i, text in _entries(prompt)]
        return "\n".join(f"{i}: {lv}" for i, lv in given if lv is not None)

    return invoke


def _base(text: str) -> int:
    return 1 if text.startswith("Chapter") else 2


def test_a_shift_never_turns_a_heading_into_body_text(monkeypatch) -> None:
    """A chunk whose shared headings sit one level deeper shifts its own up one;
    its level-1 chapters stay level 1, not the level-0 drop sentinel."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    invoke = _scripted(lambda call, i, text: _base(text) + (call > 1 and i <= 3))
    data = gather_normalize_levels(md, mode="llm_full", invoke=invoke)
    assert data is not None and min(data.levels.values()) == 1


def test_shared_headings_answered_as_drops_do_not_set_the_shift(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    invoke = _scripted(lambda call, i, text: 0 if call > 1 and i <= 3 else _base(text))
    data = gather_normalize_levels(md, mode="llm_full", invoke=invoke)
    assert data is not None
    assert all(data.levels[i] == _base(h.text) for i, h in enumerate(_extract_headings(md), 1))


def test_shared_headings_do_not_count_toward_coverage(monkeypatch) -> None:
    """Each chunk clears 90% counting the 50 headings it repeats; its own headings
    (89.7% over the document) do not."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "500")
    md = _flattened_doc(100, 9)  # 1,000 headings, two chunks

    def answer(call: int, i: int, text: str) -> int | None:
        own = i if call == 1 else i - 50
        return None if own > (451 if call == 1 else 446) else _base(text)

    assert gather_normalize_levels(md, mode="llm_full", invoke=_scripted(answer)) is None


def test_one_shared_heading_read_as_a_title_does_not_move_the_chunk(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    invoke = _scripted(lambda call, i, text: 1 if call > 1 and i == 1 else _base(text))
    out = apply_normalization(md, gather_normalize_levels(md, mode="llm_full", invoke=invoke))
    assert all(lv == _base(text) for lv, text in _levels(out))


def test_the_whole_list_answer_ignores_indices_past_the_list() -> None:
    md = _flattened_doc(1, 9)  # 10 headings
    invoke = _scripted(lambda _c, i, text: _base(text) if i <= 8 else None)
    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke) is None

    def padded(prompt: str) -> str:
        return invoke(prompt) + "\n50: 2\n51: 2"

    assert gather_normalize_levels(md, mode="llm_full", invoke=padded) is None


def test_a_chunk_size_too_small_to_align_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "3")
    md = _flattened_doc(4, 5)
    invoke, prompts = _leveler()
    assert gather_normalize_levels(md, mode="llm_full", invoke=invoke) is not None
    assert len(prompts) == 1


def test_a_drop_verdict_survives_the_shift(monkeypatch) -> None:
    """A shifted chunk's level-0 verdict (de-headify) is not a level to move."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_CHUNK_HEADINGS", "10")
    md = _flattened_doc(4, 5)
    target = 15  # a section in the second chunk, local index 8 past 3 shared

    def answer(call: int, i: int, text: str) -> int:
        if call == 2 and i == target - 7:
            return 0
        return _base(text) + (call > 1 and i <= 3)  # shared one deeper: shift -1

    data = gather_normalize_levels(md, mode="llm_full", invoke=_scripted(answer))
    assert data is not None and data.levels[target] == 0


def test_the_shift_is_the_median_of_the_shared_headings() -> None:
    """One shared heading read as a title (level 1) doesn't move the chunk."""
    assert _aligned({1: 1, 2: 3, 3: 3, 4: 3}, 3, {1: 3, 2: 3, 3: 3}, "llm_full") == {4: 3}


def test_a_shifted_level_stops_at_6() -> None:
    assert _aligned({1: 1, 2: 1, 3: 1, 4: 6}, 3, {1: 3, 2: 3, 3: 3}, "llm_full") == {4: 6}
