"""The LLM-mode gather behind `gather_normalize_levels`: the question asked once
or, past `PAGESPEAK_NORMALIZE_CHUNK_HEADINGS` headings, in chunks that each open
on the previous chunk's last headings (their levels set the chunk's scale); then
the guards that decide which verdicts survive. Types from `_heading_normalize`
are imported under TYPE_CHECKING only, to avoid an import cycle.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pw_foundation.log import get_logger
from pw_foundation.utils.env import resolve_positive_int

from ._normalize_ask import _Asker, _read_cached_response
from ._normalize_coverage import is_low_coverage
from ._normalize_llm import (
    _extract_body_anchors,
    _guard_body_drops,
    _guard_parent_drops,
    _parse_dehead_response,
    _parse_response,
    _resolve_model,
)

if TYPE_CHECKING:
    from ._heading_normalize import NormalizeMode, _HeadingRecord

logger = get_logger(__name__)

_CHUNK_HEADINGS_DEFAULT = 1500
_CHUNK_HEADINGS_ENV_VAR = "PAGESPEAK_NORMALIZE_CHUNK_HEADINGS"
_CHUNK_OVERLAP_MAX = 50
# Enough shared headings that one read as a title doesn't set the median shift.
_CHUNK_OVERLAP_MIN = 3
# A cut moves back at most this share of a chunk to land on a top-level heading.
_BOUNDARY_LOOKBACK = 0.5


def _chunk_headings() -> int:
    n: int = resolve_positive_int(
        None,
        _CHUNK_HEADINGS_ENV_VAR,
        default=_CHUNK_HEADINGS_DEFAULT,
        min_value=_CHUNK_OVERLAP_MIN + 1,
    )
    return n


def gather_llm_levels(
    md: str,
    headings: list[_HeadingRecord],
    *,
    mode: NormalizeMode,
    invoke: Callable[[str], str] | None,
    cache_dir: Path | None,
    model: str | None,
    max_input_tokens: int | None,
) -> dict[int, int] | None:
    """Ask the model to level (or, `llm_dehead`, drop) `headings`.

    Returns the 1-based verdict map that survives the guards. `{}` is
    `llm_dehead`'s "nothing to drop"; None is a failed call, an unparseable
    response, or an `llm` / `llm_full` response covering too few headings
    (with chunks, any one of them).
    """
    asker = _Asker(md, mode, invoke, cache_dir, _resolve_model(model, mode=mode), max_input_tokens)
    size = _chunk_headings()
    # A cached whole-list answer replays, refused or not: `--rerun-from normalize`
    # clears it, and only then is the list asked in chunks.
    if len(headings) > size and _read_cached_response(asker.cache_path(headings)) is None:
        return _gather_chunked(asker, headings, size)
    got = asker.ask(headings)
    if got is None:
        return None
    response, cached = got
    levels = {i: lv for i, lv in _parse(response, mode).items() if 1 <= i <= len(headings)}
    return _surviving_levels(levels, headings, md, mode=mode, cached=cached, size=len(response))


def _chunk_bounds(levels: list[int], size: int) -> list[tuple[int, int]]:
    """`[start, end)` runs of at most `size` headings, each cut moved back onto a
    top-level heading when one is near, so a chapter stays in one chunk. The top
    level is the shallowest that recurs: a lone title above its chapters is not it."""
    recurring = [lv for lv, n in Counter(levels).items() if n > 1]
    top = min(recurring) if recurring else min(levels)
    bounds: list[tuple[int, int]] = []
    start = 0
    while len(levels) - start > size:
        cut = start + size
        floor = max(cut - int(size * _BOUNDARY_LOOKBACK), start + 1)
        cut = next((i for i in range(cut, floor - 1, -1) if levels[i] == top), cut)
        bounds.append((start, cut))
        start = cut
    bounds.append((start, len(levels)))
    return bounds


def _gather_chunked(
    asker: _Asker, headings: list[_HeadingRecord], size: int
) -> dict[int, int] | None:
    anchors = _extract_body_anchors(asker.md, headings)
    overlap = min(_CHUNK_OVERLAP_MAX, max(_CHUNK_OVERLAP_MIN, size // 10))
    bounds = _chunk_bounds([h.level for h in headings], size)
    logger.info(
        "heading_normalize_chunked chunks=%d headings=%d size=%d overlap=%d",
        len(bounds),
        len(headings),
        size,
        overlap,
    )
    merged: dict[int, int] = {}
    answered = 0
    for start, end in bounds:
        lo = max(0, start - overlap)
        got = asker.ask(headings[lo:end], anchors[lo:end], at=lo)
        if got is None:
            return None
        response, cached = got
        # An index outside the chunk would land on another chunk's heading.
        local = {i: lv for i, lv in _parse(response, asker.mode).items() if 1 <= i <= end - lo}
        if asker.mode != "llm_dehead" and is_low_coverage(
            len(local), end - lo, mode=asker.mode, cached=cached
        ):
            return None
        own = _aligned({lo + i: lv for i, lv in local.items()}, start, merged, asker.mode)
        answered += len(own)
        merged.update(own)
    return _surviving_levels(
        merged, headings, asker.md, mode=asker.mode, cached=False, size=answered, answered=answered
    )


def _aligned(
    levels: dict[int, int], start: int, merged: dict[int, int], mode: NormalizeMode
) -> dict[int, int]:
    """A chunk's verdicts for its own headings (1-based index past `start`), its
    levels shifted onto the previous chunk's scale by the headings both judged."""
    own = {i: lv for i, lv in levels.items() if i > start}
    if mode == "llm_dehead" or not start:
        return own
    shifts = [merged[i] - lv for i, lv in levels.items() if i <= start and lv and merged.get(i)]
    if not shifts:
        logger.warning(
            "heading_normalize_chunk_unaligned start=%d "
            "(no shared heading levelled in both chunks; its levels are kept as answered)",
            start,
        )
        return own
    shift = round(statistics.median(shifts))
    return {i: lv if lv == 0 else min(6, max(1, lv + shift)) for i, lv in own.items()}


def _parse(response: str, mode: NormalizeMode) -> dict[int, int]:
    return _parse_dehead_response(response) if mode == "llm_dehead" else _parse_response(response)


def _surviving_levels(
    levels: dict[int, int],
    headings: list[_HeadingRecord],
    md: str,
    *,
    mode: NormalizeMode,
    cached: bool,
    size: int,
    answered: int | None = None,
) -> dict[int, int] | None:
    """The verdicts the guards keep. `size`: the response's length, for the log;
    `answered`: the headings answered, when not `len(levels)`."""
    if answered is None:
        answered = len(levels)  # before the guards drop refused verdicts
    if levels:
        # Both modes can emit the level-0 sentinel, so both need the guard.
        levels, body_refused = _guard_body_drops(levels, headings, md)
        if body_refused:
            logger.warning(
                "heading_normalize_body_guard_kept count=%d "
                "(a heading owning its own body is a section boundary)",
                body_refused,
            )
    if mode == "llm_dehead" and levels is not None:
        # Belt and braces: the parser only emits 0s, but a future prompt
        # edit must never be able to make this mode re-level a document.
        levels = {idx: lv for idx, lv in levels.items() if lv == 0}
        proposed = len(levels)
        levels = _guard_parent_drops(levels, headings)
        refused = proposed - len(levels)
        if refused:
            logger.warning(
                "heading_normalize_dehead_parents_kept count=%d proposed=%d "
                "(a heading owning child headings is a real section)",
                refused,
                proposed,
            )
        logger.info("heading_normalize_dehead_drops count=%d target=%d", len(levels), len(headings))
        # An empty verdict map is a legitimate "nothing to drop" — distinct
        # from the parse failure the shared guard below treats it as.
        if not levels:
            return {}
    if not levels:
        logger.warning("heading_normalize_no_levels_parsed response_len=%d", size)
        return None

    if mode == "llm_full":
        logger.info(
            "heading_normalize_full_rewrites count=%d target=%d", len(levels), len(headings)
        )
    if mode in ("llm", "llm_full") and is_low_coverage(
        answered, len(headings), mode=mode, cached=cached
    ):
        return None
    return levels
