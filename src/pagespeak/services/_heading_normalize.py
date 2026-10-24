"""LLM-driven heading-level renormalization.

Marker (and other PDF backends) sometimes flatten heading hierarchy: chapter
headings and their subsections are emitted at the same depth. The splitter then
can't link descendants to their chapter ancestor. Concrete case:
`#### Chapter 1 <Title>` and `#### 1.1 <Subtitle>` are both level 4, so
`1.1` has no ancestor.

This module orchestrates the gather/apply pass. The deterministic heuristic
leveling lives in `_normalize_heuristic.py`; the LLM-mode gather (cache, call,
guards) in `_normalize_llm_gather.py`, on the prompt/parse helpers in
`_normalize_llm.py`. It re-exports the helpers `_normalize_decision` imports
(`_select_structural_headings`, `_build_prompt_full`, `_estimate_tokens`,
`_extract_body_anchors`, `_resolve_max_input_tokens`) so that surface is
unchanged.

Caller layer is `_dispatch.to_markdown()`; the call is opt-in via the
`normalize_headings=True` parameter.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pw_core.llm.safe_apply import GatherResult, safe_apply
from pw_foundation.log import get_logger

from ..prompts._heading_normalize import HEADING_NORMALIZE_PROMPT_VERSION
from ._cleanup import strip_marker_pollution as _strip_marker_pollution
from ._normalize_heuristic import (
    _heuristic_level_for as _heuristic_level_for,
)
from ._normalize_heuristic import (
    _heuristic_levels,
)
from ._normalize_heuristic import (
    _is_structural_heading as _is_structural_heading,
)
from ._normalize_heuristic import (
    _select_structural_headings as _select_structural_headings,
)
from ._normalize_llm import (
    DEFAULT_NORMALIZE_MAX_INPUT_TOKENS as DEFAULT_NORMALIZE_MAX_INPUT_TOKENS,
)
from ._normalize_llm import (
    _build_prompt_full as _build_prompt_full,
)
from ._normalize_llm import (
    _estimate_tokens as _estimate_tokens,
)
from ._normalize_llm import (
    _extract_body_anchors as _extract_body_anchors,
)
from ._normalize_llm import (
    _resolve_max_input_tokens as _resolve_max_input_tokens,
)
from ._normalize_llm_gather import gather_llm_levels

logger = get_logger(__name__)

NORMALIZE_PROMPT_VERSION = HEADING_NORMALIZE_PROMPT_VERSION

NormalizeMode = Literal["heuristic", "llm", "llm_full", "llm_dehead"]
DEFAULT_NORMALIZE_MODE: NormalizeMode = "heuristic"

ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class _HeadingRecord:
    """One heading line in the document.

    Stored fields are everything we need to rewrite the line in place:
    line index for splicing back, current level for change detection, and
    text for the LLM prompt and the rebuilt heading line.

    `clean_text` property returns the heading text with Marker's
    TOC-wrapping artifacts stripped — used by the prompt builder and the
    cache key. The original `text` field stays untouched for apply-step
    matching.
    """

    line_index: int
    level: int
    text: str

    @property
    def clean_text(self) -> str:
        return _strip_marker_pollution(self.text)


def _extract_headings(md: str) -> list[_HeadingRecord]:
    """Heading records outside fenced code.

    A `#` inside a fence is a comment. Collecting it would show the LLM a
    heading that does not exist and let `_apply_normalization` rewrite the
    code — the same line_index list drives both.
    """
    from ._fences import fence_flags

    lines = md.splitlines()
    out: list[_HeadingRecord] = []
    for i, (line, fenced) in enumerate(zip(lines, fence_flags(lines), strict=True)):
        if fenced:
            continue
        m = ANY_HEADING_RE.match(line)
        if m:
            hashes, text = m.group(1), m.group(2)
            out.append(_HeadingRecord(i, len(hashes), text))
    return out


def _apply_normalization(md: str, headings: list[_HeadingRecord], levels: dict[int, int]) -> str:
    """Rewrite heading lines per `levels`. Indices are 1-based.

    `level == 0` is the v4 de-headify sentinel — the `#` prefix is
    stripped entirely and the original heading text remains as a
    paragraph line. Treats `0` as a distinct value from "no rewrite"
    (which is `levels.get(idx) is None`).
    """
    lines = md.splitlines()
    rewrites = 0
    for idx, h in enumerate(headings, start=1):
        new_level = levels.get(idx)
        if new_level is None or new_level == h.level:
            continue
        if new_level == 0:
            # De-headify: strip the `#` prefix entirely. The heading text
            # becomes a paragraph on the same line.
            lines[h.line_index] = h.text
        else:
            new_hashes = "#" * new_level
            lines[h.line_index] = f"{new_hashes} {h.text}"
        rewrites += 1
    if rewrites:
        logger.info("heading_normalize_rewrites count=%d total=%d", rewrites, len(headings))
    return "\n".join(lines)


@dataclass(frozen=True)
class NormalizeData:
    """Output of `gather_normalize_levels`. Thin wrapper around
    `pw_core.llm.safe_apply.GatherResult[dict[int, int]]` (the plan:
    1-based heading index → new level 1..6) plus pagespeak-specific
    metadata about whether the gather filtered to structural headings
    (apply must use the same filter to align indices).

    Backward-compat attribute access (`.levels`, `.target_count`,
    `.target_texts`) is preserved via properties — `gather` itself is
    the canonical storage, the properties just forward.
    """

    gather: GatherResult[dict[int, int]]
    filter_structural: bool

    @property
    def levels(self) -> dict[int, int]:
        out: dict[int, int] = self.gather.data
        return out

    @property
    def target_count(self) -> int:
        out: int = self.gather.target_count
        return out

    @property
    def target_texts(self) -> tuple[str, ...]:
        out: tuple[str, ...] = self.gather.target_texts
        return out


def gather_normalize_levels(
    md: str,
    *,
    mode: NormalizeMode = DEFAULT_NORMALIZE_MODE,
    invoke: Callable[[str], str] | None = None,
    cache_dir: Path | None = None,
    model: str | None = None,
    filter_structural: bool = True,
    max_input_tokens: int | None = None,
) -> NormalizeData | None:
    """Pure side-file producer for the heading-renormalization pass.

    Three modes:

    - `mode="heuristic"` (default) — deterministic structural rules:
      `Chapter N` → L1, `N.M` → L2, `N.M.O` → L3, etc. Free, fast, no
      LLM call, no cache file, no auth requirement.
    - `mode="llm"` — sends the structural heading list (numbered prefixes
      only) to Claude Code, parses the response, caches it. Best for docs
      with a numbered outline.
    - `mode="llm_full"` — sends ALL headings plus 200-token
      body-context anchors. Use for non-numbered manuals (product manuals,
      install guides) where the structural filter strips everything.
      Token-budget gated: when the assembled prompt exceeds
      `max_input_tokens` (default 150,000), drops body anchors and
      re-sends headings only. `filter_structural` is forced to False in
      this mode regardless of the caller-supplied value.

    Both LLM modes return a `NormalizeData` describing what to apply
    later; the apply step is mode-agnostic. Does NOT mutate any markdown.

    Returns None if there are too few headings to bother, or (LLM modes
    only) the call fails / response has no parseable levels. Apply
    treats None as a no-op.

    See `normalize_heading_levels` for the wrapper that chains gather +
    apply (legacy API, kept for backward compatibility).
    """
    all_headings = _extract_headings(md)
    if len(all_headings) < 2:
        return None

    # `llm_full` always operates on the full heading list — the whole
    # point of the mode is to bypass the structural-only filter.
    # Both full-document modes see EVERY heading: llm_full to rebuild the
    # hierarchy, llm_dehead because the junk it must catch (admonitions,
    # page furniture, bare labels) is exactly what the structural filter
    # would strip from its view.
    effective_filter_structural = filter_structural and mode not in ("llm_full", "llm_dehead")

    target_headings = (
        _select_structural_headings(all_headings) if effective_filter_structural else all_headings
    )
    if len(target_headings) < 2:
        logger.info(
            "heading_normalize_skipped reason=too_few_structural_headings n=%d",
            len(target_headings),
        )
        return None

    if mode == "heuristic":
        levels = _heuristic_levels(target_headings)
        logger.info(
            "heading_normalize_heuristic rewrites=%d target=%d",
            len(levels),
            len(target_headings),
        )
    else:
        llm_levels = gather_llm_levels(
            md,
            target_headings,
            mode=mode,
            invoke=invoke,
            cache_dir=cache_dir,
            model=model,
            max_input_tokens=max_input_tokens,
        )
        if llm_levels is None:
            return None
        levels = llm_levels

    return NormalizeData(
        gather=GatherResult(
            target_count=len(target_headings),
            target_texts=tuple(h.text for h in target_headings),
            data=levels,
        ),
        filter_structural=effective_filter_structural,
    )


def apply_normalization(md: str, data: NormalizeData | None) -> str:
    """Pure markdown transform: apply gathered level rewrites to `md`.

    Re-extracts the structural heading list from the *current* markdown
    (so callers can run cleanup or other transforms between gather and
    apply) and pairs it with the cached `levels` by 1-based index. If
    the heading list has drifted since gather (different count, or the
    text at the same index doesn't match), logs a warning and returns
    `md` unchanged — never silently mis-apply.

    A `None` `data` means gather decided there was nothing to do (too
    few headings, LLM failure, etc.) — passes through unchanged.
    """
    if data is None:
        return md
    current_all = _extract_headings(md)
    current_target = (
        _select_structural_headings(current_all) if data.filter_structural else current_all
    )
    result = safe_apply(
        data.gather,
        current_texts=[h.text for h in current_target],
        apply_fn=lambda levels: _apply_normalization(md, current_target, levels),
        label="heading_normalize",
    )
    return result if result is not None else md


def normalize_heading_levels(
    md: str,
    *,
    mode: NormalizeMode = DEFAULT_NORMALIZE_MODE,
    invoke: Callable[[str], str] | None = None,
    cache_dir: Path | None = None,
    model: str | None = None,
    filter_structural: bool = True,
    max_input_tokens: int | None = None,
) -> str:
    """Backward-compat wrapper: gather levels, apply them in one shot.

    New code should prefer the gather + apply pair so the gather can
    run concurrently with `gather_diagrams()` while apply waits for
    other transforms (cleanup, decoration strip) to settle.

    Returns the original `md` if anything in the gather pipeline fails
    (no LLM, parse error, drift), so this never raises and is safe to
    drop into a flow that doesn't require headings to actually change.

    `mode`: `"heuristic"` (default — fast, free),
    `"llm"` (Claude Code call on numbered structural headings only),
    or `"llm_full"` (Claude Code call on all headings + body-context
    anchors, for non-numbered manuals).
    """
    data = gather_normalize_levels(
        md,
        mode=mode,
        invoke=invoke,
        cache_dir=cache_dir,
        model=model,
        filter_structural=filter_structural,
        max_input_tokens=max_input_tokens,
    )
    return apply_normalization(md, data)
