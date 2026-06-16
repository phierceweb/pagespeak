"""LLM-driven heading-level renormalization.

Marker (and other PDF backends) sometimes flatten heading hierarchy: chapter
headings and their subsections are emitted at the same depth. The splitter then
can't link descendants to their chapter ancestor. Concrete case:
`#### Chapter 1 <Title>` and `#### 1.1 <Subtitle>` are both level 4, so
`1.1` has no ancestor.

This module orchestrates the gather/apply pass. The deterministic heuristic
leveling lives in `_normalize_heuristic.py`; the LLM prompt/invoke/cache
machinery in `_normalize_llm.py`. It re-exports the helpers
`_normalize_decision` imports (`_select_structural_headings`,
`_build_prompt_full`, `_estimate_tokens`, `_extract_body_anchors`,
`_resolve_max_input_tokens`) so that surface is unchanged.

Caller layer is `_dispatch.to_markdown()`; the call is opt-in via the
`normalize_headings=True` parameter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pf_core.llm.safe_apply import GatherResult, safe_apply
from pf_core.log import get_logger
from pf_core.utils.io import atomic_write_json

from ..prompts._heading_normalize import (
    HEADING_NORMALIZE_PROMPT_VERSION as NORMALIZE_PROMPT_VERSION,
)
from ..prompts._heading_normalize_full import HEADING_NORMALIZE_FULL_PROMPT_VERSION
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
    _CLAUDE_CODE_TIMEOUT_S_DEFAULT as _CLAUDE_CODE_TIMEOUT_S_DEFAULT,
)
from ._normalize_llm import (
    DEFAULT_NORMALIZE_MAX_INPUT_TOKENS as DEFAULT_NORMALIZE_MAX_INPUT_TOKENS,
)
from ._normalize_llm import (
    _build_llm_full_prompt_with_gate,
    _build_prompt,
    _cache_key,
    _parse_response,
    _resolve_model,
)
from ._normalize_llm import (
    _build_prompt_full as _build_prompt_full,
)
from ._normalize_llm import (
    _claude_code_invoke as _claude_code_invoke,
)
from ._normalize_llm import (
    _claude_code_timeout_s as _claude_code_timeout_s,
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

logger = get_logger(__name__)

NormalizeMode = Literal["heuristic", "llm", "llm_full"]
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
    out: list[_HeadingRecord] = []
    for i, line in enumerate(md.splitlines()):
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
    `pf_core.llm.safe_apply.GatherResult[dict[int, int]]` (the plan:
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
    effective_filter_structural = filter_structural and mode != "llm_full"

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
        return NormalizeData(
            gather=GatherResult(
                target_count=len(target_headings),
                target_texts=tuple(h.text for h in target_headings),
                data=levels,
            ),
            filter_structural=effective_filter_structural,
        )

    # === LLM modes ("llm" or "llm_full") =================================
    resolved_model = _resolve_model(model, mode=mode)

    cache_path: Path | None = None
    if cache_dir is not None:
        key = _cache_key(target_headings, resolved_model, mode=mode)
        cache_path = cache_dir / f"{key}.json"

    response: str | None = None
    if cache_path is not None and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            response = data.get("response")
            logger.info("heading_normalize_cache_hit path=%s", cache_path)
        except (OSError, ValueError) as e:
            logger.warning("heading_normalize_cache_read_failed: %s", e)
            response = None

    if response is None:
        if mode == "llm_full":
            prompt, include_anchors = _build_llm_full_prompt_with_gate(
                md, target_headings, max_input_tokens=max_input_tokens
            )
            prompt_version_for_cache = HEADING_NORMALIZE_FULL_PROMPT_VERSION
            agent_slug = "heading_normalize_full"
            # canonical template for `llm_prompts` registration —
            # the unrendered system text from the YAML (sans the per-call
            # heading-list substitution).
            from ..prompts._heading_normalize_full import HEADING_NORMALIZE_FULL_PROMPT

            agent_system_prompt = HEADING_NORMALIZE_FULL_PROMPT
        else:
            prompt = _build_prompt(target_headings)
            include_anchors = False  # not applicable
            prompt_version_for_cache = NORMALIZE_PROMPT_VERSION
            agent_slug = "heading_normalize"
            from ..prompts._heading_normalize import HEADING_NORMALIZE_PROMPT

            agent_system_prompt = HEADING_NORMALIZE_PROMPT

        # route through `_agent_runtime.invoke_agent` so the
        # call captures a tracking row in `llm_runs` (when DB initialized)
        # and goes through the same model-resolution seam as vision.
        # The legacy `invoke=` kwarg path is preserved for test injection
        # — when set, bypasses invoke_agent entirely.
        try:
            if invoke is not None:
                response = invoke(prompt)
            else:
                from .._agent_runtime import invoke_agent

                response, _run_id = invoke_agent(
                    agent_slug,
                    messages=[{"role": "user", "content": prompt}],
                    prompt_version=prompt_version_for_cache,
                    system_prompt_text=agent_system_prompt,
                    model_override=resolved_model,
                    metadata={
                        "mode": mode,
                        "heading_count": len(target_headings),
                        "anchors_included": include_anchors,
                    },
                )
        except Exception as e:  # any backend failure is non-fatal
            logger.warning("heading_normalize_invoke_failed: %s", e)
            return None

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                cache_path,
                {
                    "model": resolved_model,
                    "mode": mode,
                    "prompt_version": prompt_version_for_cache,
                    "anchors_included": include_anchors,
                    "response": response,
                },
            )

    levels = _parse_response(response)
    if not levels:
        logger.warning("heading_normalize_no_levels_parsed response_len=%d", len(response))
        return None

    if mode == "llm_full":
        logger.info(
            "heading_normalize_full_rewrites count=%d target=%d",
            len(levels),
            len(target_headings),
        )

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
