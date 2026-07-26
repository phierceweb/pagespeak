"""Heading-normalize-dehead prompt — rendered at import time from
`heading_normalize_dehead.yaml`.

Mirrors `_heading_normalize_full.py`'s shape. This prompt asks only
whether each heading is real; the levels it arrives with are preserved.
"""

from __future__ import annotations

from pf_core.llm.prompts import render_spec

from ._loader import load_pagespeak_spec

_spec = load_pagespeak_spec("heading_normalize_dehead")
HEADING_NORMALIZE_DEHEAD_PROMPT, HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION = render_spec(
    _spec, part="system"
)


def build_dehead_prompt(headings_block: str) -> str:
    """Compose the full prompt sent to `claude --print`."""
    rendered_user, _version = render_spec(
        _spec,
        part="user",
        style="@@",
        HEADINGS=headings_block,
    )
    return f"{HEADING_NORMALIZE_DEHEAD_PROMPT}\n\n{rendered_user}"


__all__ = [
    "HEADING_NORMALIZE_DEHEAD_PROMPT",
    "HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION",
    "build_dehead_prompt",
]
