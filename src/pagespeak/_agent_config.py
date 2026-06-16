"""Agent config resolution: model + backend selection from model_router.yaml.

The "which model / which backend for this task slug" concern.
Self-contained — reads `config/model_router.yaml` + the
`PAGESPEAK_<SLUG>_BACKEND` env var, with no dependency on the runtime's
call-recording state. `_agent_runtime` re-exports `Backend` /
`resolve_backend` / `resolve_agent_config` / `_load_yaml_config`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pf_core.log import get_logger

logger = get_logger(__name__)


Backend = Literal["claude_code", "anthropic", "openrouter"]
_VALID_BACKENDS: tuple[Backend, ...] = ("claude_code", "anthropic", "openrouter")


# Final fallback if neither YAML nor env var supplies a model. Same
# cost-protection rationale as the DEFAULT_VISION_MODEL: without
# an explicit model, `claude --print` would use the user's interactive
# session model — on a Max account that's Sonnet/Opus, and a 1000-image
# vision pass quietly burns a day's premium usage. Forcing Haiku by
# default keeps batch LLM work cheap.
_HARDCODED_FALLBACKS: dict[str, str] = {
    "vision": "claude-haiku-4-5-20251001",
    "heading_normalize": "claude-haiku-4-5-20251001",
    "heading_normalize_full": "claude-haiku-4-5-20251001",
}

# Model-router YAML resolution. `MODEL_ROUTER_CONFIG` (an explicit path)
# wins; else a `config/model_router.yaml` in the cwd (the repo / a local
# override); else the copy bundled in the package, which ships in the wheel
# so an installed copy has the tuned defaults with no config on disk.
_DEFAULT_CONFIG_PATH = "config/model_router.yaml"
_PACKAGED_CONFIG_PATH = Path(__file__).with_name("model_router.yaml")

# Keys that live in `config/model_router.yaml` but are pagespeak-side
# config (not client.chat() kwargs). `invoke_agent` strips these from
# the resolved cfg before calling chat() so they aren't passed to the
# underlying SDK as unknown kwargs. Pagespeak callers read them via
# `resolve_agent_config(slug).get(key)`.
_PAGESPEAK_ONLY_CFG_KEYS: frozenset[str] = frozenset(
    {
        # llm_full's input-token-budget gate (chars÷4 prompt-size
        # threshold above which body anchors are dropped). Used by
        # `_heading_normalize._resolve_max_input_tokens`.
        "max_input_tokens",
    }
)


def _config_path() -> Path:
    """Resolve the model-router YAML (highest precedence first): the
    MODEL_ROUTER_CONFIG env override, a cwd `config/model_router.yaml`, then
    the packaged default bundled in the wheel."""
    env = os.environ.get("MODEL_ROUTER_CONFIG")
    if env:
        return Path(env)
    cwd = Path(_DEFAULT_CONFIG_PATH)
    if cwd.exists():
        return cwd
    return _PACKAGED_CONFIG_PATH


def _load_yaml_config() -> dict[str, Any]:
    """Load the agent YAML config. Not cached — re-read every call so
    edits land immediately. The file is small (a few hundred bytes)
    and the read happens at most a few times per conversion run."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("model_router_yaml_unexpected_shape path=%s", path)
            return {}
        return data
    except (OSError, yaml.YAMLError) as e:
        logger.warning("model_router_yaml_load_failed path=%s error=%s", path, e)
        return {}


def resolve_backend(slug: str) -> Backend:
    """Resolve the active backend for the given task slug.

    Env var: ``PAGESPEAK_<SLUG>_BACKEND`` (default ``claude_code``).
    Must be one of ``claude_code | anthropic | openrouter``.
    """
    if slug not in _HARDCODED_FALLBACKS:
        raise KeyError(f"unknown pagespeak agent slug: {slug!r}")

    env_var = f"PAGESPEAK_{slug.upper()}_BACKEND"
    value = (os.environ.get(env_var) or "claude_code").strip().lower()
    if value not in _VALID_BACKENDS:
        raise ValueError(f"unknown backend {value!r} for {slug!r}; valid: {_VALID_BACKENDS}")
    return value


def resolve_agent_config(
    slug: str,
    *,
    model_override: str | None = None,
    backend: Backend | None = None,
) -> dict[str, Any]:
    """Resolve the agent's config dict including the model.

    Precedence for the ``model`` field (highest first):

    1. ``model_override`` kwarg (CLI flag / constructor arg)
    2. YAML ``agents.<slug>.backends.<backend>.model``
    3. Hardcoded fallback in :data:`_HARDCODED_FALLBACKS`

    Other kwargs (``temperature``, ``max_tokens``, etc.) come from the
    YAML's ``agents.<slug>`` top-level (shared across all backends) and
    are overlaid by ``agents.<slug>.backends.<backend>`` (backend-
    specific values win).

    env-var step (``PAGESPEAK_<SLUG>_MODEL``) removed. The YAML
    is the single source of truth for per-task per-backend model
    configuration; env vars are reserved for backend selection only
    (``PAGESPEAK_<SLUG>_BACKEND``). Per-call explicit overrides still
    win — passing ``--vision-model`` or ``--normalize-headings-model``
    on the CLI behaves unchanged.
    """
    if slug not in _HARDCODED_FALLBACKS:
        raise KeyError(f"unknown pagespeak agent slug: {slug!r}")

    backend = backend or resolve_backend(slug)
    yaml_data = _load_yaml_config()
    agent_block = (yaml_data.get("agents") or {}).get(slug) or {}

    # Start with shared kwargs (everything except `backends`).
    cfg: dict[str, Any] = {k: v for k, v in agent_block.items() if k != "backends"}
    # Overlay backend-specific kwargs.
    backends_block = agent_block.get("backends") or {}
    backend_cfg = backends_block.get(backend) or {}
    cfg.update(backend_cfg)

    # Resolve `model` with full precedence chain (no env-var step).
    model = model_override or cfg.get("model") or _HARDCODED_FALLBACKS[slug]
    cfg["model"] = model
    return cfg
