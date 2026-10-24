"""One heading-normalize question: the response cache, the mode's prompt, and
the call. `_normalize_llm_gather` asks it once for a short list, once per chunk
for a long one.

`_HeadingRecord` and `NormalizeMode` are imported under TYPE_CHECKING only, so
there is no import cycle with `_heading_normalize`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pw_foundation.log import get_logger
from pw_foundation.utils.io import atomic_write_json

from ..prompts._heading_normalize import (
    HEADING_NORMALIZE_PROMPT,
    HEADING_NORMALIZE_PROMPT_VERSION,
)
from ..prompts._heading_normalize_dehead import (
    HEADING_NORMALIZE_DEHEAD_PROMPT,
    HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION,
)
from ..prompts._heading_normalize_full import (
    HEADING_NORMALIZE_FULL_PROMPT,
    HEADING_NORMALIZE_FULL_PROMPT_VERSION,
)
from ._normalize_llm import (
    _build_dehead_prompt_with_gate,
    _build_llm_full_prompt_with_gate,
    _build_prompt,
    _cache_key,
)

if TYPE_CHECKING:
    from ._heading_normalize import NormalizeMode, _HeadingRecord

logger = get_logger(__name__)


@dataclass(frozen=True)
class _ModeRequest:
    """One mode's call. `system_prompt` is the unrendered YAML system text,
    registered in `llm_prompts`."""

    prompt: str
    include_anchors: bool
    prompt_version: int
    agent_slug: str
    system_prompt: str


@dataclass(frozen=True)
class _Asker:
    """One mode's question about a run of headings: cache, prompt, call."""

    md: str
    mode: NormalizeMode
    invoke: Callable[[str], str] | None
    cache_dir: Path | None
    model: str
    max_input_tokens: int | None

    def cache_path(self, headings: list[_HeadingRecord], at: int | None = None) -> Path | None:
        """`at`: a chunk's first index, so identical heading runs keep their own answers."""
        if self.cache_dir is None:
            return None
        key = _cache_key(headings, self.model, mode=self.mode)
        return self.cache_dir / (f"{key}.json" if at is None else f"{key}-at{at}.json")

    def ask(
        self,
        headings: list[_HeadingRecord],
        anchors: list[str] | None = None,
        *,
        at: int | None = None,
    ) -> tuple[str, bool] | None:
        """`(response, came from the cache)`, or None when the call failed."""
        cache_path = self.cache_path(headings, at)
        response = _read_cached_response(cache_path)
        if response is not None:
            return response, True
        request = _mode_request(
            self.md,
            headings,
            mode=self.mode,
            max_input_tokens=self.max_input_tokens,
            anchors=anchors,
        )
        try:
            response = _call(
                request, mode=self.mode, invoke=self.invoke, model=self.model, headings=headings
            )
        except Exception as e:  # any backend failure is non-fatal
            logger.warning("heading_normalize_invoke_failed: %s", e)
            return None
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                cache_path,
                {
                    "model": self.model,
                    "mode": self.mode,
                    "prompt_version": request.prompt_version,
                    "anchors_included": request.include_anchors,
                    "response": response,
                },
            )
        return response, False


def _read_cached_response(cache_path: Path | None) -> str | None:
    if cache_path is None or not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        response: str | None = data.get("response")
        logger.info("heading_normalize_cache_hit path=%s", cache_path)
    except (OSError, ValueError) as e:
        logger.warning("heading_normalize_cache_read_failed: %s", e)
        return None
    return response


def _mode_request(
    md: str,
    headings: list[_HeadingRecord],
    *,
    mode: NormalizeMode,
    max_input_tokens: int | None,
    anchors: list[str] | None = None,
) -> _ModeRequest:
    if mode == "llm_full":
        prompt, include_anchors = _build_llm_full_prompt_with_gate(
            md, headings, max_input_tokens=max_input_tokens, anchors=anchors
        )
        return _ModeRequest(
            prompt,
            include_anchors,
            HEADING_NORMALIZE_FULL_PROMPT_VERSION,
            "heading_normalize_full",
            HEADING_NORMALIZE_FULL_PROMPT,
        )
    if mode == "llm_dehead":
        prompt, include_anchors = _build_dehead_prompt_with_gate(
            md, headings, max_input_tokens=max_input_tokens, anchors=anchors
        )
        return _ModeRequest(
            prompt,
            include_anchors,
            HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION,
            "heading_normalize_dehead",
            HEADING_NORMALIZE_DEHEAD_PROMPT,
        )
    return _ModeRequest(
        _build_prompt(headings),
        False,
        HEADING_NORMALIZE_PROMPT_VERSION,
        "heading_normalize",
        HEADING_NORMALIZE_PROMPT,
    )


def _call(
    request: _ModeRequest,
    *,
    mode: NormalizeMode,
    invoke: Callable[[str], str] | None,
    model: str,
    headings: list[_HeadingRecord],
) -> str:
    """`invoke=` (test injection) bypasses `invoke_agent`, which records the
    call in `llm_runs` and resolves the model the same way vision does."""
    if invoke is not None:
        return invoke(request.prompt)
    from .._agent_runtime import invoke_agent

    return invoke_agent(
        request.agent_slug,
        messages=[{"role": "user", "content": request.prompt}],
        prompt_version=request.prompt_version,
        system_prompt_text=request.system_prompt,
        model_override=model,
        metadata={
            "mode": mode,
            "heading_count": len(headings),
            "anchors_included": request.include_anchors,
        },
    ).content
