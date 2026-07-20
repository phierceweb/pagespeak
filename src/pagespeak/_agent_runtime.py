"""Per-task LLM call seam over pf-core's router, tracked calls, and recording.

Every LLM-calling site goes through `invoke_agent(slug, …)`: it resolves
backend + model via `pf_core.llm.router`, acquires the backend client, and
runs the call through `tracked_messages_call` (which writes the `llm_runs`
row when tracking is on, registers the versioned prompt, and appends a
per-call summary to the recording window).

`begin_call_recording` / `end_call_recording` re-export pf-core's
ContextVar-based window. Pool fan-outs must submit workers through
`contextvars.copy_context()` so the window stays visible — see the vision
pool in `services._diagrams`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Literal

from pf_core.llm.recording import begin_call_recording as begin_call_recording
from pf_core.llm.recording import end_call_recording as end_call_recording
from pf_core.llm.recording import record_call as _record_call
from pf_core.llm.router import get_agent_block, get_agent_config
from pf_core.llm.router import resolve_backend as _pf_resolve_backend
from pf_core.log import get_logger

logger = get_logger(__name__)


Backend = Literal["claude_code", "anthropic", "openrouter"]
_VALID_BACKENDS: tuple[Backend, ...] = ("claude_code", "anthropic", "openrouter")

# Defensive twin of the YAML's top-level `non_chat_keys` declaration: a
# custom MODEL_ROUTER_CONFIG that omits the declaration must still not
# leak pagespeak-side options into client.chat().
_NON_CHAT_KEYS: frozenset[str] = frozenset({"max_input_tokens"})


def _ensure_router_config() -> None:
    """Wheel installs have no cwd ``config/`` — point pf-core's router at
    the packaged model_router.yaml unless the operator already chose one
    (``MODEL_ROUTER_CONFIG`` env or a cwd ``config/model_router.yaml``).
    Runs at import (via ``pagespeak/__init__``) and at each seam entry."""
    if os.environ.get("MODEL_ROUTER_CONFIG"):
        return
    if Path("config/model_router.yaml").exists():
        return
    os.environ["MODEL_ROUTER_CONFIG"] = str(Path(__file__).with_name("model_router.yaml"))


_ensure_router_config()


def _job_id_from_env() -> int | None:
    """The web worker sets ``PAGESPEAK_JOB_ID`` on the conversion subprocess
    so every ``llm_runs`` row is attributed to that job. Returns ``None``
    (un-attributed) when unset or unparseable — tracking must never break a
    conversion over a bad value."""
    raw = os.environ.get("PAGESPEAK_JOB_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("pagespeak_job_id_unparseable value=%r", raw)
        return None


def resolve_backend(slug: str, *, backend: Backend | None = None) -> Backend:
    """Active backend for ``slug``, narrowed to pagespeak's ``Backend`` literal.

    Resolution is pf-core's precedence: ``backend=`` kwarg >
    ``PAGESPEAK_<SLUG>_BACKEND`` env (via the YAML's ``env_prefix``) > the
    YAML's top-level ``default_client``. An env value naming an undeclared
    backend falls through to the default instead of raising.
    """
    _ensure_router_config()
    resolved = _pf_resolve_backend(slug, backend=backend)
    if resolved not in _VALID_BACKENDS:
        raise ValueError(f"unknown backend {resolved!r} for {slug!r}; valid: {_VALID_BACKENDS}")
    return resolved


def agent_option(slug: str, key: str) -> Any:
    """Read a ``non_chat_keys`` option (e.g. ``max_input_tokens``) for the
    agent's ACTIVE backend, falling back to the agent-level value —
    ``get_agent_config`` strips these from chat kwargs."""
    _ensure_router_config()
    block = get_agent_block(slug)
    backend = resolve_backend(slug)
    backend_block = (block.get("backends") or {}).get(backend) or {}
    return backend_block.get(key, block.get(key))


def _get_client_for_backend(backend: str) -> Any:
    """Return the pf-core client singleton for the given backend.

    Imported lazily so consumers that never use a backend don't need
    its driver / API key configured.
    """
    if backend == "claude_code":
        from pf_core.clients import claude_code
        from pf_core.utils.env import resolve_int

        # Pass the timeout explicitly: pf-core's per-model singleton caches the
        # first call's args, and its own default is 600s — env bumps would be lost.
        timeout_s: int = resolve_int(None, "PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", default=1800)
        return claude_code.get_client(timeout=timeout_s)
    if backend == "openrouter":
        from pf_core.clients import openrouter

        return openrouter.get_client()
    if backend == "anthropic":
        from pf_core.clients import anthropic

        return anthropic.get_client()
    raise ValueError(f"unhandled backend: {backend!r}")


def invoke_agent(
    slug: str,
    *,
    messages: list[dict[str, Any]],
    prompt_version: int,
    system_prompt_text: str | None = None,
    model_override: str | None = None,
    backend_override: Backend | None = None,
    client_override: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, int | None]:
    """Single LLM-call seam for all pagespeak tasks.

    Returns ``(content, run_id)``. ``run_id`` is the pf-core
    ``llm_runs.id`` if the DB is initialized; ``None`` otherwise.
    Errors from the underlying client are re-raised after a
    ``status='failed'`` row is written.

    Args:
        slug: Pagespeak agent slug — ``"vision"``,
            ``"heading_normalize"``, or ``"heading_normalize_full"``.
        messages: Chat-format message list passed verbatim to the
            underlying client.
        prompt_version: Version int of the prompt being used; recorded on
            the run and, with ``system_prompt_text``, registered in
            ``llm_prompts``.
        system_prompt_text: the canonical (unrendered) system-prompt
            template for this agent. When provided, it is registered
            (idempotently) in ``llm_prompts`` and the id lands on
            ``llm_runs.system_prompt_id``. None skips the prompt write.
        model_override: Explicit per-call model override (CLI flag).
            Wins over the YAML.
        backend_override: Explicit backend selection that bypasses the
            ``PAGESPEAK_<SLUG>_BACKEND`` env var. Used by the backend
            classes that encode their identity in the class name.
        client_override: Pre-constructed client object exposing
            ``.chat(messages, model, **kwargs) -> (content, usage)``.
            Bypasses ``_get_client_for_backend`` (tests, pre-tuned
            clients).
        metadata: Task-specific extras split into tags/metrics on the
            tracking row (image phash, heading_count, etc.).
    """
    _ensure_router_config()
    backend = resolve_backend(slug, backend=backend_override)
    cfg = get_agent_config(slug, backend=backend, model_override=model_override)
    client = client_override if client_override is not None else _get_client_for_backend(backend)
    chat_kwargs = {k: v for k, v in cfg.items() if k not in _NON_CHAT_KEYS}
    model = str(chat_kwargs.pop("model"))

    from pagespeak import _db

    if not _db._initialized:
        # Tracking is opt-in: no DB → plain chat, but the recording window
        # still gets its per-call summary (run_id stays None).
        t0 = time.monotonic()
        success = False
        usage: dict[str, Any] = {}
        try:
            content, usage = client.chat(messages=messages, model=model, **chat_kwargs)
            success = True
        finally:
            usage = dict(usage) if usage else {}
            usage.setdefault("duration_ms", int((time.monotonic() - t0) * 1000))
            _record_call(
                {
                    "agent_type": slug,
                    "model": model,
                    "provider": backend,
                    "prompt_version": prompt_version,
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "cost_usd": float(usage.get("cost_usd", 0.0) or 0.0),
                    "duration_ms": int(usage.get("duration_ms", 0) or 0),
                    "success": success,
                    "run_id": None,
                }
            )
        return content, None

    from pf_core.llm.tracked import tracked_messages_call

    content, _usage, run_id = tracked_messages_call(
        client=client,
        agent_type=slug,
        messages=messages,
        model=model,
        sampling=chat_kwargs or None,
        spec=(
            {"version": prompt_version, "system": system_prompt_text}
            if system_prompt_text
            else None
        ),
        provider=backend,
        metadata=metadata,
        job_id=_job_id_from_env(),
        on_record_error="warn",
    )
    return content, run_id


__all__ = [
    "Backend",
    "agent_option",
    "begin_call_recording",
    "end_call_recording",
    "invoke_agent",
    "resolve_backend",
]
