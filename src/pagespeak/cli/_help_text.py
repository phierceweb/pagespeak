"""CLI help strings read from live config rather than restated.

Each builder falls back to a claim-free sentence — a broken config must not
break `--help`.
"""

from __future__ import annotations

_NORMALIZE_MODES: tuple[tuple[str, str], ...] = (
    ("llm", "heading_normalize"),
    ("llm_full", "heading_normalize_full"),
    ("llm_dehead", "heading_normalize_dehead"),
)

_NORMALIZE_MODEL_BASE = (
    "LLM-mode only: model passed to `claude --model …`, overriding the per-mode "
    "model routed from config/model_router.yaml"
)


def normalize_model_help() -> str:
    try:
        from pf_core.llm.router import get_agent_config

        from .._agent_runtime import _ensure_router_config

        _ensure_router_config()
        pairs = [
            f"{mode}: {get_agent_config(slug, backend='claude_code')['model']}"
            for mode, slug in _NORMALIZE_MODES
        ]
    except Exception:  # noqa: BLE001 — help text must render on a broken config
        return f"{_NORMALIZE_MODEL_BASE}."
    return f"{_NORMALIZE_MODEL_BASE} ({', '.join(pairs)})."


NORMALIZE_MODEL_HELP = normalize_model_help()
