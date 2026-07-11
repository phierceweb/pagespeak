"""LLM heading-normalize machinery: prompt building, Claude invocation, response
parsing, model/token resolution, and the response cache key.

`_heading_normalize.py` re-exports `_build_prompt_full` /
`_estimate_tokens` / `_extract_body_anchors` / `_resolve_max_input_tokens`
for `_normalize_decision`. Helpers only duck-type `_HeadingRecord`, so it's
imported under TYPE_CHECKING only — no import cycle.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

from ..prompts._heading_normalize import (
    HEADING_NORMALIZE_PROMPT_VERSION as NORMALIZE_PROMPT_VERSION,
)
from ..prompts._heading_normalize import (
    build_normalize_prompt as _build_full_prompt_text,
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

_CLAUDE_CODE_TIMEOUT_S_DEFAULT = 1800

_CLAUDE_CODE_TIMEOUT_ENV_VAR = "PAGESPEAK_CLAUDE_CODE_TIMEOUT_S"


def _claude_code_timeout_s() -> int:
    """Read `PAGESPEAK_CLAUDE_CODE_TIMEOUT_S` at call time; fall back to default.

    Operational tunables live in env, with
    the in-code default as the fallback when the env var is unset or invalid.
    Uses pf-core's `resolve_int`, which emits a structured
    `env_var_malformed` warning on non-integer values rather than crashing.
    """
    n: int = resolve_int(None, _CLAUDE_CODE_TIMEOUT_ENV_VAR, default=_CLAUDE_CODE_TIMEOUT_S_DEFAULT)
    return n


DEFAULT_NORMALIZE_MODEL = "claude-haiku-4-5-20251001"


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


def _resolve_max_input_tokens(override: int | None = None) -> int:
    """Resolve the `llm_full` token-budget threshold.

    Precedence (highest first):

    1. Explicit ``override`` arg (passed through from
       ``to_markdown(max_input_tokens=…)`` / library callers).
    2. YAML ``agents.heading_normalize_full.max_input_tokens`` in
       ``config/model_router.yaml``.
    3. :data:`DEFAULT_NORMALIZE_MAX_INPUT_TOKENS` (150,000).

    env-var step removed. The threshold is a payload-shaping
    knob (not a per-call kwarg), so the YAML is the right home.
    """
    if isinstance(override, int) and override > 0:
        return override

    from .._agent_runtime import resolve_agent_config

    cfg = resolve_agent_config("heading_normalize_full")
    val = cfg.get("max_input_tokens")
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
    prompt_version = (
        HEADING_NORMALIZE_FULL_PROMPT_VERSION if mode == "llm_full" else NORMALIZE_PROMPT_VERSION
    )
    h.update(str(prompt_version).encode("utf-8"))
    return h.hexdigest()[:16]


def _claude_code_invoke(prompt: str, *, model: str | None = None) -> str:
    """Default invoker — delegates to `pf_core.clients.claude_code.ClaudeCodeClient`.

    Free of API charge if the user has a Claude Code subscription.
    Slower than direct API (1-3s setup + LLM time). Tests inject a fake
    via the `invoke=` parameter on `normalize_heading_levels`.

    The transport layer is pf-core's `ClaudeCodeClient`:
    pagespeak retains the prompt + model resolution policy, pf-core owns
    the binary discovery + subprocess machinery + error mapping.
    """
    from pf_core.clients.claude_code import ClaudeCodeClient
    from pf_core.exceptions import AppError

    # retry=1: a failed call makes the caller skip normalization entirely,
    # so one cheap retry is worth it.
    client = ClaudeCodeClient(timeout=_claude_code_timeout_s(), model=model, retry=1)
    try:
        # `model` is already set on the client (constructor above); pf-core's
        # chat() falls back to it (`model or self.model`), so passing it again
        # here is redundant — and chat() now types `model: str`, not `str | None`.
        content, _usage = client.chat(
            messages=[{"role": "user", "content": prompt}],
        )
        assert isinstance(content, str)  # pf-core chat() contract
        return content
    except AppError as e:
        ctx = getattr(e, "context", {}) or {}
        stderr_head = ctx.get("stderr_head", "")
        returncode = ctx.get("returncode", "?")
        raise RuntimeError(
            f"claude --print exited {returncode}: {stderr_head[:300] or str(e)[:300]}"
        ) from e


def _resolve_model(model: str | None, *, mode: NormalizeMode) -> str:
    """Pick the model name. Explicit arg > YAML > `DEFAULT_NORMALIZE_MODEL`.

    env-var step (`PAGESPEAK_NORMALIZE_HEADINGS_MODEL`) removed.
    YAML at `config/model_router.yaml` is the source of truth; env is
    reserved for backend selection (`PAGESPEAK_HEADING_NORMALIZE_BACKEND`
    / `_FULL_BACKEND`).

    Mode picks the agent slug: `llm` → `heading_normalize`, `llm_full` →
    `heading_normalize_full`. Each slug has its own YAML block so the
    two modes can use different models if needed (e.g. larger-context
    model for `llm_full` on very large docs).

    Never returns None or empty — see `DEFAULT_NORMALIZE_MODEL` for the
    cost-protection rationale (without an explicit `--model`, `claude
    --print` uses the user's interactive session model, which on Claude
    Max can silently burn premium usage). The trailing `or
    DEFAULT_NORMALIZE_MODEL` collapses both `None` (YAML unset) and `""`
    (YAML set to empty string) to the default.
    """
    from .._agent_runtime import resolve_agent_config

    agent_slug = "heading_normalize_full" if mode == "llm_full" else "heading_normalize"
    cfg = resolve_agent_config(agent_slug, model_override=model)
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
