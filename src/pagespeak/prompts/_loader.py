"""Prompt YAML path resolver — shared by all prompt loader stubs.

Each per-agent loader (`_diagram.py`, `_heading_normalize.py`,
`_heading_normalize_full.py`) calls :func:`resolve_prompt_path(agent_slug)`
to find the YAML file for that agent. Path resolution follows an
override chain so the same loader code works for two use modes:

1. **CLI / standalone**: pagespeak runs from its own repo root. Users
   editing prompts drop their version into ``config/prompts/<agent>.yaml``
   at the repo root; the loader picks it up without modifying installed
   source. Mirrors the ``config/model_router.yaml`` resolution pattern.

2. **Library**: pagespeak is imported by another project. The other
   project's CWD is the consumer's project root. The consumer ships
   their own ``config/prompts/`` if they want custom prompts; otherwise
   they get pagespeak's bundled defaults.

Resolution order (highest precedence first):

1. ``$PAGESPEAK_PROMPTS_DIR/<agent>.yaml`` — env var pointing at a
   directory of override YAMLs. Set when running in an environment
   that doesn't follow the CWD convention (containerized deployments,
   monorepo subprojects, etc.).
2. ``config/prompts/<agent>.yaml`` relative to the current working
   directory. The recommended override location for most users.
3. Bundled fallback at ``src/pagespeak/prompts/<agent>.yaml`` —
   shipped inside the installed package; the source of truth when no
   override is present.
"""

from __future__ import annotations

from pathlib import Path

from pf_core.utils.config_path import resolve_config_path

# Bundled defaults ship at the same directory as this module — see
# `heading_normalize.yaml`, `heading_normalize_full.yaml`, `diagram.yaml`.
_BUNDLED_DIR = Path(__file__).parent


def resolve_prompt_path(agent_slug: str) -> Path:
    """Return the YAML file path for the given agent.

    Walks the override chain (``$PAGESPEAK_PROMPTS_DIR`` → CWD
    ``config/prompts/`` → bundled) via
    :func:`pf_core.utils.config_path.resolve_config_path`. Returns the
    first existing path, absolute, so callers don't trip over CWD changes
    between resolve and load. Falls through to the bundled default, which
    is a packaging invariant — so this never raises ``FileNotFoundError``.
    """
    return resolve_config_path(
        f"{agent_slug}.yaml",
        env_dir_var="PAGESPEAK_PROMPTS_DIR",
        bundled_dir=_BUNDLED_DIR,
        cwd_subdir="config/prompts",
    )


__all__ = ["resolve_prompt_path"]
