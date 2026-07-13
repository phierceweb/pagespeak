"""Stable re-export of the diagram prompt.

The prompt is YAML-backed in `pagespeak.prompts.diagram.yaml`, loaded by
`pagespeak.prompts._diagram` (via `load_pagespeak_spec` + `render_spec`).
This shim preserves the public import path used by `services/_diagrams.py`.
"""

from __future__ import annotations

from ..prompts._diagram import (
    DIAGRAM_PROMPT,
    DIAGRAM_PROMPT_VERSION,
    render_diagram_prompt,
)

__all__ = ["DIAGRAM_PROMPT", "DIAGRAM_PROMPT_VERSION", "render_diagram_prompt"]
