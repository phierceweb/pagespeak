"""Diagram-extraction prompt — rendered from diagram.yaml.

Public exports `DIAGRAM_PROMPT` and `DIAGRAM_PROMPT_VERSION`; the prompt
content lives in `diagram.yaml` (YAML-backed prompts).

The prompt is **alt-text-aware**: it carries an `@@ORIGINAL_ALT@@` token
that must be substituted per image with the figure's source alt text, so
the model can correct / keep / enrich the existing description rather than
overwrite it. Render per call via `render_diagram_prompt(original_alt)`.
`DIAGRAM_PROMPT` is the no-alt rendering (token → `(none provided)`), kept for
consumers/tests that want the static text.
"""

from __future__ import annotations

from pf_core.llm.prompts import render_spec

from ._loader import load_pagespeak_spec

_spec = load_pagespeak_spec("diagram")

# Substituted for `@@ORIGINAL_ALT@@` when the figure has no source alt text.
# Matches the prompt's "(none provided) → write from scratch" branch.
_NO_ALT_MARKER = "(none provided)"


def render_diagram_prompt(original_alt: str | None) -> str:
    """Render the diagram prompt with the figure's source alt text injected.

    `original_alt` is the figure's existing description (its markdown alt
    text). Blank/None → the `(none provided)` marker so the prompt's
    write-from-scratch branch fires. Token-style render (`@@…@@`) because the
    prompt body is full of literal JSON braces.
    """
    value = original_alt.strip() if original_alt and original_alt.strip() else _NO_ALT_MARKER
    text, _version = render_spec(_spec, part="system", style="@@", ORIGINAL_ALT=value)
    return text


DIAGRAM_PROMPT_VERSION = int(_spec["version"])
# No-alt rendering — static constant (fully token-substituted; carries no
# literal `@@ORIGINAL_ALT@@`).
DIAGRAM_PROMPT = render_diagram_prompt(None)

__all__ = ["DIAGRAM_PROMPT", "DIAGRAM_PROMPT_VERSION", "render_diagram_prompt"]
