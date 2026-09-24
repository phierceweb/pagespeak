"""LLM heading-normalize machinery: prompt building, response parsing,
model/token resolution, and the response cache key.

`_heading_normalize.py` re-exports `_build_prompt_full` /
`_estimate_tokens` / `_extract_body_anchors` / `_resolve_max_input_tokens`
for `_normalize_decision`. Helpers only duck-type `_HeadingRecord`, so it's
imported under TYPE_CHECKING only — no import cycle.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import TYPE_CHECKING

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

from ..prompts._heading_normalize import (
    HEADING_NORMALIZE_PROMPT_VERSION as NORMALIZE_PROMPT_VERSION,
)
from ..prompts._heading_normalize import (
    build_normalize_prompt as _build_full_prompt_text,
)
from ..prompts._heading_normalize_dehead import (
    HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION,
)
from ..prompts._heading_normalize_full import (
    HEADING_NORMALIZE_FULL_PROMPT_VERSION,
    build_full_prompt,
)

if TYPE_CHECKING:
    from ._heading_normalize import NormalizeMode, _HeadingRecord

logger = get_logger(__name__)


DEFAULT_NORMALIZE_MAX_INPUT_TOKENS = 150_000

_ANCHOR_MAX_CHARS = 800

_LEVEL_LINE_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
# `<idx>: KEEP|DROP` — the llm_dehead verdict line.
_DEHEAD_LINE_RE = re.compile(r"^\s*(\d+)\s*:\s*(KEEP|DROP)\s*$", re.IGNORECASE)

_PROMPT_VERSION_BY_MODE: dict[str, int] = {
    "llm": NORMALIZE_PROMPT_VERSION,
    "llm_full": HEADING_NORMALIZE_FULL_PROMPT_VERSION,
    "llm_dehead": HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION,
}

_BODY_GUARD_MIN_WORDS_DEFAULT = 10
_BODY_GUARD_MIN_WORDS_ENV_VAR = "PAGESPEAK_DEHEAD_GUARD_MIN_BODY_WORDS"
# Above this many identical headings the line is running furniture, not a section.
_BODY_GUARD_MAX_RECURRENCE_DEFAULT = 25
_BODY_GUARD_MAX_RECURRENCE_ENV_VAR = "PAGESPEAK_DEHEAD_GUARD_MAX_RECURRENCE"


DEFAULT_NORMALIZE_MODEL = "claude-haiku-4-5-20251001"

# Must match the slugs `_heading_normalize` passes to `invoke_agent`: this
# model goes in as `model_override`, which outranks the agent block's own.
_AGENT_SLUG_FOR_MODE = {
    "llm": "heading_normalize",
    "llm_full": "heading_normalize_full",
    "llm_dehead": "heading_normalize_dehead",
}


def _build_prompt(headings: list[_HeadingRecord]) -> str:
    # render with clean_text so the LLM sees a chapter title as
    # `Chapter 5 Chemical Messengers` rather than the TOC-link-wrapped
    # `<[span...]**Chapter 5](#page-26-0) Chemical Messengers`.
    lines = [f"{idx + 1}: {h.level} {h.clean_text}" for idx, h in enumerate(headings)]
    return _build_full_prompt_text("\n".join(lines))


def _extract_body_anchors(
    md: str,
    headings: list[_HeadingRecord],
    *,
    max_chars: int = _ANCHOR_MAX_CHARS,
) -> list[str]:
    """For each heading, extract the body text up to the next heading or
    `max_chars`, whichever comes first.

    Returns a parallel list (same length as `headings`). Empty string for
    headings with no following body text or whose next non-blank line is
    another heading.
    """
    lines = md.splitlines()
    anchors: list[str] = []
    n_lines = len(lines)
    for i, h in enumerate(headings):
        next_heading_line = headings[i + 1].line_index if i + 1 < len(headings) else n_lines
        body_lines = lines[h.line_index + 1 : next_heading_line]
        # Strip leading blank lines.
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        body = "\n".join(body_lines).strip()
        if len(body) > max_chars:
            body = body[:max_chars].rstrip()
        anchors.append(body)
    return anchors


def _build_prompt_full(
    headings: list[_HeadingRecord],
    anchors: list[str],
    *,
    include_anchors: bool,
) -> str:
    """Render the `llm_full` prompt.

    Each heading entry is `<idx>: <level> <text>`, followed (when
    `include_anchors=True` and the anchor is non-empty) by the body
    preview indented 4 spaces. The headings block is then plugged into
    the YAML-rendered system+user template.
    """
    blocks: list[str] = []
    for idx, h in enumerate(headings, start=1):
        # clean_text for the LLM view; see `_build_prompt`.
        line = f"{idx}: {h.level} {h.clean_text}"
        if include_anchors and anchors[idx - 1]:
            # Indent the anchor 4 spaces under the heading.
            indented = "\n".join("    " + ln for ln in anchors[idx - 1].splitlines())
            line = f"{line}\n{indented}"
        blocks.append(line)
    headings_block = "\n".join(blocks)
    return build_full_prompt(headings_block)


def _estimate_tokens(text: str) -> int:
    """Cheap token estimator: chars÷4. Anthropic's tokenizer is close to
    4 chars per token for English. Off by ~20% in either direction; fine
    for a context-window gate with 50K headroom.
    """
    return len(text) // 4


def _resolve_max_input_tokens(
    override: int | None = None, *, agent: str = "heading_normalize_full"
) -> int:
    """Resolve a normalize mode's token-budget threshold.

    Precedence (highest first):

    1. Explicit ``override`` arg (passed through from
       ``to_markdown(max_input_tokens=…)`` / library callers).
    2. YAML ``agents.<agent>`` — the active backend's
       ``max_input_tokens`` entry, then the agent-level one (a
       ``non_chat_keys`` option, read via ``_agent_runtime.agent_option``).
    3. :data:`DEFAULT_NORMALIZE_MAX_INPUT_TOKENS` (150,000).

    The threshold is a payload-shaping knob (not a per-call kwarg), so it
    lives in the YAML, not env.
    """
    if isinstance(override, int) and override > 0:
        return override

    from pf_core.exceptions import ConfigurationError

    from .._agent_runtime import agent_option

    try:
        val = agent_option(agent, "max_input_tokens")
    except ConfigurationError:
        val = None  # custom YAML without the agent → default below
    if isinstance(val, int) and val > 0:
        return val
    return DEFAULT_NORMALIZE_MAX_INPUT_TOKENS


def _parse_response(response: str) -> dict[int, int]:
    """Parse `<idx>: <level>` lines. Returns `{1-based-idx: new_level}`.

    Accepts `level ∈ 0..6` (v4 prompt schema). `level == 0` means
    "this isn't a real heading; the apply step strips the `#` prefix
    entirely, leaving the text as a paragraph" — see the v4
    heading_normalize_full prompt changelog. Lines that don't match the
    regex are ignored — the
    LLM occasionally adds commentary despite the prompt instruction.
    """
    out: dict[int, int] = {}
    for line in response.splitlines():
        m = _LEVEL_LINE_RE.match(line)
        if m:
            idx = int(m.group(1))
            level = int(m.group(2))
            if 0 <= level <= 6:
                out[idx] = level
    return out


def _parse_dehead_response(response: str) -> dict[int, int]:
    """Parse `<idx>: KEEP|DROP` lines into the level map the apply step takes.

    Only DROP verdicts produce an entry, mapped to level 0 (the de-headify
    sentinel). A KEEP is deliberately absent from the map: `_apply_normalization`
    skips any index it has no entry for, so a kept heading retains the level it
    arrived with — the property that makes this mode safe on a document whose
    hierarchy is already correct. Unmatched lines are ignored (the model
    occasionally adds commentary despite the instruction).
    """
    out: dict[int, int] = {}
    for line in response.splitlines():
        m = _DEHEAD_LINE_RE.match(line)
        if m and m.group(2).upper() == "DROP":
            out[int(m.group(1))] = 0
    return out


def _guard_parent_drops(
    levels: dict[int, int],
    headings: list[_HeadingRecord],
) -> dict[int, int]:
    """Refuse any de-headify verdict on a heading that owns child headings.

    A heading whose next heading is deeper introduced a subtree, so it is a
    real section whatever its own body looks like; junk is always a leaf.
    Constrains the model rather than trusting it — a per-heading judge reads
    a terse reference section as a fragment, and does so for a whole chapter
    at a time.
    """
    if not levels:
        return levels
    kept: dict[int, int] = {}
    for idx, level in levels.items():
        this = headings[idx - 1] if 0 < idx <= len(headings) else None
        nxt = headings[idx] if 0 < idx < len(headings) else None
        if this is not None and nxt is not None and nxt.level > this.level:
            continue  # parent of a subtree — never de-headify
        kept[idx] = level
    return kept


def _guard_body_drops(
    levels: dict[int, int],
    headings: list[_HeadingRecord],
    md: str,
    *,
    min_body_words: int | None = None,
    max_recurrence: int | None = None,
) -> tuple[dict[int, int], int]:
    """Refuse a de-headify verdict on a heading that owns its own body text.

    A heading followed by prose of its own is a section boundary: dropping it
    merges that prose into the section above, so the content stops being
    retrievable on its own even though the words survive. Recurring page
    furniture is exempt — a line repeated across the whole document is a
    running header however much text trails it, and exempting it is what keeps
    the guard from re-admitting every `Note` in a manual.

    Returns the surviving verdict map and the number of drops refused.
    """
    drops = [idx for idx, level in levels.items() if level == 0]
    if not drops:
        return levels, 0
    min_words = resolve_int(
        min_body_words, _BODY_GUARD_MIN_WORDS_ENV_VAR, default=_BODY_GUARD_MIN_WORDS_DEFAULT
    )
    max_recur = resolve_int(
        max_recurrence,
        _BODY_GUARD_MAX_RECURRENCE_ENV_VAR,
        default=_BODY_GUARD_MAX_RECURRENCE_DEFAULT,
    )
    anchors = _extract_body_anchors(md, headings)
    recurrence = Counter(h.clean_text.strip().lower() for h in headings)
    kept = dict(levels)
    for idx in drops:
        if not 0 < idx <= len(headings):
            continue
        heading = headings[idx - 1]
        if recurrence[heading.clean_text.strip().lower()] > max_recur:
            continue
        if len(anchors[idx - 1].split()) >= min_words:
            del kept[idx]
    return kept, len(levels) - len(kept)


def _build_prompt_dehead(
    headings: list[_HeadingRecord],
    anchors: list[str],
    *,
    include_anchors: bool,
) -> str:
    """Render the `llm_dehead` prompt — same headings block as `llm_full`,
    different question."""
    from ..prompts._heading_normalize_dehead import build_dehead_prompt

    blocks: list[str] = []
    for idx, h in enumerate(headings, start=1):
        line = f"{idx}: {h.level} {h.clean_text}"
        if include_anchors and anchors[idx - 1]:
            indented = "\n".join("    " + ln for ln in anchors[idx - 1].splitlines())
            line = f"{line}\n{indented}"
        blocks.append(line)
    return build_dehead_prompt("\n".join(blocks))


def _build_dehead_prompt_with_gate(
    md: str,
    headings: list[_HeadingRecord],
    *,
    max_input_tokens: int | None,
) -> tuple[str, bool]:
    """`_build_llm_full_prompt_with_gate`'s sibling for the de-headify prompt."""
    threshold = _resolve_max_input_tokens(max_input_tokens, agent="heading_normalize_dehead")
    anchors = _extract_body_anchors(md, headings)
    prompt = _build_prompt_dehead(headings, anchors, include_anchors=True)
    estimate = _estimate_tokens(prompt)
    logger.info(
        "normalize_dehead_payload_estimate tokens=%d heading_count=%d threshold=%d",
        estimate,
        len(headings),
        threshold,
    )
    if estimate <= threshold:
        return prompt, True
    prompt = _build_prompt_dehead(headings, anchors, include_anchors=False)
    logger.warning(
        "normalize_dehead_anchors_dropped estimate=%d threshold=%d heading_count=%d",
        estimate,
        threshold,
        len(headings),
    )
    return prompt, False


def _cache_key(
    headings: list[_HeadingRecord],
    model: str | None,
    *,
    mode: str = "llm",
) -> str:
    """Hash the heading list + model + mode. Cache invalidates when any
    of headings, model, or mode change; cleanup-only edits to the body
    don't bust it. Each mode uses its own prompt version constant so
    prompt-content edits invalidate the matching mode's cache.

    hash on `clean_text` (not `text`) so changes to
    `_strip_marker_pollution`'s regex set auto-invalidate the cache.
    Whether the LLM gets `<[span...]**Chapter 5](#page-X)` or
    `Chapter 5` is a behavior difference; the cache should reflect it.
    """
    h = hashlib.sha256()
    payload = "\n".join(f"{r.level}|{r.clean_text}" for r in headings)
    h.update(payload.encode("utf-8"))
    h.update(b"|")
    h.update((model or "").encode("utf-8"))
    h.update(b"|")
    h.update(mode.encode("utf-8"))
    h.update(b"|")
    # Every mode keys on ITS OWN prompt version: a mode that falls back to
    # another's constant cannot be invalidated by bumping its prompt, so a
    # fixed prompt would silently replay the old verdicts.
    prompt_version = _PROMPT_VERSION_BY_MODE.get(mode, NORMALIZE_PROMPT_VERSION)
    h.update(str(prompt_version).encode("utf-8"))
    return h.hexdigest()[:16]


def _resolve_model(model: str | None, *, mode: NormalizeMode) -> str:
    """Pick the model name. Explicit arg > YAML > `DEFAULT_NORMALIZE_MODEL`.

    The YAML is the source of truth for the model; env is reserved for
    backend selection (`PAGESPEAK_HEADING_NORMALIZE_BACKEND` / `_FULL_BACKEND`).

    Mode picks the agent slug via `_AGENT_SLUG_FOR_MODE`, so each mode can use
    its own model (a larger-context one for `llm_full` on very large docs).

    Never returns None or empty — see `DEFAULT_NORMALIZE_MODEL` for the
    cost-protection rationale (without an explicit `--model`, `claude
    --print` uses the user's interactive session model, which on Claude
    Max can silently burn premium usage). The trailing `or
    DEFAULT_NORMALIZE_MODEL` collapses both `None` (YAML unset) and `""`
    (YAML set to empty string) to the default.
    """
    from pf_core.llm.router import get_agent_config

    agent_slug = _AGENT_SLUG_FOR_MODE.get(mode, "heading_normalize")
    cfg = get_agent_config(agent_slug, model_override=model)
    return cfg.get("model") or DEFAULT_NORMALIZE_MODEL


def _build_llm_full_prompt_with_gate(
    md: str,
    headings: list[_HeadingRecord],
    *,
    max_input_tokens: int | None,
) -> tuple[str, bool]:
    """Build the `llm_full` prompt with token-budget gating.

    Returns `(prompt_text, anchors_were_included)`. If the assembled
    prompt-with-anchors exceeds the resolved token budget, retries with
    anchors dropped (which always fits — headings alone are small) and
    logs the fallback.
    """
    threshold = _resolve_max_input_tokens(max_input_tokens)
    anchors = _extract_body_anchors(md, headings)
    prompt = _build_prompt_full(headings, anchors, include_anchors=True)
    estimate = _estimate_tokens(prompt)
    logger.info(
        "normalize_full_payload_estimate tokens=%d heading_count=%d threshold=%d",
        estimate,
        len(headings),
        threshold,
    )
    if estimate <= threshold:
        return prompt, True

    logger.warning(
        "normalize_full_payload_too_big estimated_tokens=%d threshold=%d heading_count=%d",
        estimate,
        threshold,
        len(headings),
    )
    fallback_prompt = _build_prompt_full(headings, anchors, include_anchors=False)
    logger.info(
        "normalize_full_headings_only_fallback heading_count=%d fallback_tokens=%d",
        len(headings),
        _estimate_tokens(fallback_prompt),
    )
    return fallback_prompt, False
