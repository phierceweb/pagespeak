"""Heading-normalize prompt — rendered at import time from
`heading_normalize.yaml`.

Public exports `HEADING_NORMALIZE_PROMPT` (the static system prompt)
and `HEADING_NORMALIZE_PROMPT_VERSION` mirror the diagram-prompt shape
(see `_diagram.py`). `build_normalize_prompt(headings_block)` returns
the complete prompt string ready to send to the LLM: system guidance
plus the rendered user template with the headings block substituted.
"""

from __future__ import annotations

from pf_core.llm.prompts import load_prompt_spec, render_spec

from ._loader import resolve_prompt_path

_SPEC_PATH = resolve_prompt_path("heading_normalize")

_spec = load_prompt_spec(_SPEC_PATH, expected_agent="heading_normalize")
HEADING_NORMALIZE_PROMPT, HEADING_NORMALIZE_PROMPT_VERSION = render_spec(_spec, part="system")


def build_normalize_prompt(headings_block: str) -> str:
    """Compose the full prompt sent to the LLM.

    Returns ``system + "\\n\\n" + user_rendered``, where the user
    template has ``@@HEADINGS@@`` substituted with ``headings_block``.
    """
    rendered_user, _version = render_spec(
        _spec,
        part="user",
        style="@@",
        HEADINGS=headings_block,
    )
    return f"{HEADING_NORMALIZE_PROMPT}\n\n{rendered_user}"


__all__ = [
    "HEADING_NORMALIZE_PROMPT",
    "HEADING_NORMALIZE_PROMPT_VERSION",
    "build_normalize_prompt",
]
