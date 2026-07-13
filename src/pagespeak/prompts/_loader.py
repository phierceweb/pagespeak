"""Prompt spec loading — shared by all per-agent prompt stub modules.

Each stub (`_diagram.py`, `_heading_normalize.py`, `_heading_normalize_full.py`)
calls :func:`load_pagespeak_spec(agent_slug)`. Resolution + validation live in
:func:`pf_core.llm.prompts.load_prompt`: `$PAGESPEAK_PROMPTS_DIR/<slug>.yaml` →
CWD `config/prompts/<slug>.yaml` → the bundled default next to this module
(a packaging invariant, so loading never falls through to a missing file).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pf_core.llm.prompts import load_prompt

_BUNDLED_DIR = Path(__file__).parent


def load_pagespeak_spec(agent_slug: str) -> dict[str, Any]:
    """Load + validate `<agent_slug>.yaml` via the override chain."""
    return load_prompt(
        agent_slug,
        env_dir_var="PAGESPEAK_PROMPTS_DIR",
        bundled_dir=_BUNDLED_DIR,
        cwd_subdir="config/prompts",
    )


__all__ = ["load_pagespeak_spec"]
