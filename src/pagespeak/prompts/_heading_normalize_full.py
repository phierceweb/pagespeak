"""Heading-normalize-full prompt — rendered at import time from
`heading_normalize_full.yaml`.

Public exports `HEADING_NORMALIZE_FULL_PROMPT` (the static system prompt)
and `HEADING_NORMALIZE_FULL_PROMPT_VERSION` mirror the diagram-prompt
shape (see `_diagram.py`). `build_full_prompt(headings_block)` returns
the complete prompt string ready to send to `claude --print`: system
guidance + the rendered user template with the supplied headings block.
"""

from __future__ import annotations

from pf_core.llm.prompts import render_spec

from ._loader import load_pagespeak_spec

_spec = load_pagespeak_spec("heading_normalize_full")
HEADING_NORMALIZE_FULL_PROMPT, HEADING_NORMALIZE_FULL_PROMPT_VERSION = render_spec(
    _spec, part="system"
)


def build_full_prompt(headings_block: str) -> str:
    """Compose the full prompt sent to `claude --print`.

    Returns `system + "\\n\\n" + user_rendered`, where the user template
    has `@@HEADINGS@@` substituted with `headings_block`.
    """
    rendered_user, _version = render_spec(
        _spec,
        part="user",
        style="@@",
        HEADINGS=headings_block,
    )
    return f"{HEADING_NORMALIZE_FULL_PROMPT}\n\n{rendered_user}"


__all__ = [
    "HEADING_NORMALIZE_FULL_PROMPT",
    "HEADING_NORMALIZE_FULL_PROMPT_VERSION",
    "build_full_prompt",
]
