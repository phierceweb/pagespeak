"""Auto-select the heading-normalize engine for a document, $0, no LLM.

Heading-normalize (services/_heading_normalize.py) has three engines:
heuristic ($0 numbering rules), llm (headers-only), llm_full (body
context). This module picks between them from the cleaned markdown's
heading SHAPE, instead of a manual per-document flag.

The decision is two-way: heuristic (skip the LLM) vs llm_full (needs the
body-context LLM). `llm` (headers-only) is NOT an auto target — it is
llm_full's own internal payload fallback (_build_llm_full_prompt_with_gate)
for oversized docs; headers-only under-fits a flattened hierarchy.

Signal: a doc needs llm_full when MANY headings pile at one level (a
*collapsed* hierarchy, by absolute count — flat share alone fails: a small
flat document looks as flat as a large collapsed one) AND numbering can't
drive a free fix. Numbered docs and small or well-shaped docs route to the
heuristic. The llm_full branch is then GATED on whether the configured
backend can fit the payload — a doc that needs it but exceeds the configured
`max_input_tokens` is surfaced (reason `needs_full_but_oversized_for_config`)
rather than silently degrading to headers-only.

Thresholds are document-relative ratios plus one absolute count, never
content phrase lists — a general converter keys on structural shape, not
wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pf_core.log import get_logger

from ._heading_normalize import (
    NormalizeMode,
    _extract_headings,
    _select_structural_headings,
)

logger = get_logger(__name__)

# Caller-facing mode option: "auto" is resolved to a concrete NormalizeMode
# by `resolve_normalize_mode` (below) before gather_normalize_levels runs;
# gather itself never sees "auto".
NormalizeModeOption = Literal["heuristic", "llm", "llm_full", "auto"]

# Below this many headings, structure is too thin to renormalize.
MIN_HEADINGS = 6
# >= this many headings piled at the single most-common level marks a
# *collapsed* hierarchy that needs body-context leveling. The trigger is the
# ABSOLUTE count, not the dominant-level SHARE: a healthy pyramid is also
# leaf-heavy (high share), so share can't separate a flattened doc from a
# healthy one — the size of the pile does. A small genuinely-flat doc stays
# under the bar; a collapsed textbook or mis-leveled manual clears it.
COLLAPSE_MIN = 40
# >= this share are Chapter/numbered headings -> numbering encodes the
# hierarchy and the $0 heuristic (+ cleanup lock_numbered_section_depth)
# levels it deterministically; no LLM needed.
NUMBERED_SHARE = 0.40


@dataclass(frozen=True)
class NormalizeDecision:
    """The chosen mode plus the metrics behind it (logged + read in
    validation; a metric is not a verdict — the chosen mode's OUTPUT must
    still be read by eye on representative docs).

    `full_payload_tokens` / `full_payload_budget` are populated only when
    shape said llm_full: the estimated body-anchor payload vs the
    configured `max_input_tokens`. 0 otherwise.
    """

    mode: NormalizeMode
    reason: str
    n_headings: int
    dominant_count: int
    dominant_share: float
    numbered_share: float
    full_payload_tokens: int = 0
    full_payload_budget: int = 0


def _estimate_full_payload(md: str) -> tuple[int, int]:
    """(estimated llm_full prompt tokens, configured max_input_tokens).

    Reuses the exact assembly + budget the llm_full gate uses, so the
    viability check matches what gather would actually do. The budget is
    read from `config/model_router.yaml`
    (`agents.heading_normalize_full.max_input_tokens`) — i.e. the config
    decides what "fits". Re-extracts headings (cheap) to avoid importing
    the private `_HeadingRecord` type across modules.
    """
    from ._heading_normalize import (
        _build_prompt_full,
        _estimate_tokens,
        _extract_body_anchors,
        _resolve_max_input_tokens,
    )

    headings = _extract_headings(md)
    anchors = _extract_body_anchors(md, headings)
    prompt = _build_prompt_full(headings, anchors, include_anchors=True)
    return _estimate_tokens(prompt), _resolve_max_input_tokens()


def classify_normalize_mode(md: str) -> NormalizeDecision:
    """Return `heuristic` or `llm_full` for `md` from heading shape, GATED
    by whether the configured llm_full backend can fit the payload.

    Never returns `llm` (headers-only) — that is llm_full's internal
    payload fallback, not an up-front auto choice (see module docstring).
    A doc whose shape needs llm_full but whose payload exceeds the
    configured budget is returned as `heuristic` with reason
    `needs_full_but_oversized_for_config` — surfacing that the config
    needs a larger context window rather than silently degrading.
    """
    headings = _extract_headings(md)
    n = len(headings)
    if n < MIN_HEADINGS:
        return NormalizeDecision("heuristic", "too_few_headings", n, n, (1.0 if n else 0.0), 0.0)

    histogram: dict[int, int] = {}
    for h in headings:
        histogram[h.level] = histogram.get(h.level, 0) + 1
    dominant_count = max(histogram.values())
    dominant_share = dominant_count / n
    numbered_share = len(_select_structural_headings(headings)) / n

    if numbered_share >= NUMBERED_SHARE:
        return NormalizeDecision(
            "heuristic", "numbered", n, dominant_count, dominant_share, numbered_share
        )

    if dominant_count < COLLAPSE_MIN:
        return NormalizeDecision(
            "heuristic", "shape_ok", n, dominant_count, dominant_share, numbered_share
        )

    # Shape needs llm_full — select it only if the configured backend can
    # fit the payload; else surface the gap instead of degrading silently.
    est_tokens, budget = _estimate_full_payload(md)
    if est_tokens <= budget:
        return NormalizeDecision(
            "llm_full",
            "collapsed_non_numbered",
            n,
            dominant_count,
            dominant_share,
            numbered_share,
            est_tokens,
            budget,
        )
    return NormalizeDecision(
        "heuristic",
        "needs_full_but_oversized_for_config",
        n,
        dominant_count,
        dominant_share,
        numbered_share,
        est_tokens,
        budget,
    )


def resolve_normalize_mode(md: str) -> NormalizeMode:
    """Classify `md` and return the concrete engine to run, logging the
    decision + metrics. The normalize phase calls this when the configured
    mode is `auto`."""
    d = classify_normalize_mode(md)
    logger.info(
        "normalize_auto_decision mode=%s reason=%s n=%d dom_count=%d "
        "dom_share=%.2f num_share=%.2f payload_tok=%d budget=%d",
        d.mode,
        d.reason,
        d.n_headings,
        d.dominant_count,
        d.dominant_share,
        d.numbered_share,
        d.full_payload_tokens,
        d.full_payload_budget,
    )
    return d.mode


__all__ = [
    "COLLAPSE_MIN",
    "MIN_HEADINGS",
    "NUMBERED_SHARE",
    "NormalizeDecision",
    "NormalizeModeOption",
    "classify_normalize_mode",
    "resolve_normalize_mode",
]
