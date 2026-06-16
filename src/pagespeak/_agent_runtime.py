"""Per-task LLM call infrastructure with pf-core tracking integration.

Every LLM-calling site in pagespeak goes through `invoke_agent(slug, …)`,
which:

1. Resolves the per-backend model from `config/model_router.yaml`
   (with env-var and explicit-arg overrides — see
   :func:`resolve_agent_config`).
2. Picks the backend client (`claude_code`, `anthropic`, or
   `openrouter`) based on `PAGESPEAK_<SLUG>_BACKEND` env var.
3. Invokes the client's ``.chat(messages, **cfg)``.
4. Writes one row to the pf-core ``llm_runs`` table (if
   :func:`pagespeak._db.init_db` was called; no-op otherwise — tracking
   is opt-in).

Same seam is used for vision, heading_normalize, and
heading_normalize_full so model selection, routing, and tracking are
uniform across pagespeak's LLM surface.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from pf_core.log import get_logger

from ._agent_config import (
    _PAGESPEAK_ONLY_CFG_KEYS,
    Backend,
    resolve_agent_config,
    resolve_backend,
)
from ._agent_config import (
    _load_yaml_config as _load_yaml_config,
)

logger = get_logger(__name__)


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


# Per-conversion call accumulator. `to_markdown()` opens a window via
# `begin_call_recording()`; each `invoke_agent` call within it appends a
# record; `end_call_recording()` drains + closes it. One conversion per
# process in practice, so a module-level list + lock suffices (vision
# ThreadPoolExecutor workers share it via the lock). `_session_metadata`
# carries per-conversion tags (source_basename, etc.) merged into every
# call's metadata, so `to_markdown` sets source context once at entry.
_call_records_lock = threading.Lock()
_call_records: list[dict[str, Any]] | None = None
_session_metadata: dict[str, Any] | None = None


def begin_call_recording(*, session_metadata: dict[str, Any] | None = None) -> None:
    """Open a per-conversion accumulator window. Subsequent
    `invoke_agent` calls (including those fired from ThreadPoolExecutor
    workers in the vision pass) append one record per call.

    ``session_metadata``: dict of key→value pairs attached
    to every call's tracking row within the window. Values are stringly-
    typed for ``llm_run_tags`` storage (numerics go in
    ``llm_run_metrics``). Typical use: ``{"source_basename":
    "textbook.pdf"}`` set by ``to_markdown`` so every downstream LLM call
    attributes to that input doc without threading kwargs through 4 layers
    of dispatch.

    Idempotent at the entry point — calling again resets the list and
    replaces the session metadata.
    """
    global _call_records, _session_metadata
    with _call_records_lock:
        _call_records = []
        _session_metadata = dict(session_metadata) if session_metadata else None


def end_call_recording() -> list[dict[str, Any]]:
    """Drain the accumulator and close the window. Returns the list of
    record dicts. Subsequent calls return ``[]`` until the next
    :func:`begin_call_recording`. Also clears the session
    metadata so it doesn't leak into subsequent recording windows.
    """
    global _call_records, _session_metadata
    with _call_records_lock:
        out = list(_call_records) if _call_records else []
        _call_records = None
        _session_metadata = None
    return out


def _append_call_record(record: dict[str, Any]) -> None:
    """Internal — append one record if recording is active. Thread-safe
    via the module-level lock; safe to call from vision-pass workers."""
    with _call_records_lock:
        if _call_records is not None:
            _call_records.append(record)


# Max length for an `llm_run_tags.tag` value. The DDL caps the column at
# 64 chars; we encode "key:value" tag strings, so the whole rendered tag
# (including the prefix and colon) has to fit. Longer values are
# truncated rather than dropped — partial provenance beats none.
_TAG_MAX_CHARS = 64


def _split_metadata_to_tags_and_metrics(
    metadata: dict[str, Any],
) -> tuple[list[str], dict[str, float]]:
    """Translate a pagespeak metadata dict into pf-core's tag list +
    metric map for `llm_run_tags` / `llm_run_metrics` inserts.

    Rules:

    - Numeric values (int, float, excluding bools) → `metrics`.
    - Everything else stringifiable → `tags` as ``"key:value"``.
      Truncated to ``_TAG_MAX_CHARS``.
    - ``None`` values are dropped entirely (no tag, no metric).
    - Bools encode as ``"key:true"`` / ``"key:false"`` in tags (not
      metrics — they're conceptually flags, not measurements).
    """
    tags: list[str] = []
    metrics: dict[str, float] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool):
            tags.append(f"{key}:{'true' if value else 'false'}"[:_TAG_MAX_CHARS])
        elif isinstance(value, (int, float)):
            metrics[str(key)[:64]] = float(value)
        else:
            tag = f"{key}:{value}"
            tags.append(tag[:_TAG_MAX_CHARS])
    return tags, metrics


def _get_client_for_backend(backend: Backend) -> Any:
    """Return the pf-core client singleton for the given backend.

    Imported lazily so consumers that never use a backend don't need
    its driver / API key configured.
    """
    if backend == "claude_code":
        from pf_core.clients import claude_code
        from pf_core.utils.env import resolve_int

        # Operational tunable (env-configurable):
        # `PAGESPEAK_CLAUDE_CODE_TIMEOUT_S` (default 1800) sets the
        # subprocess timeout for every `claude --print` call from
        # pagespeak (vision, heading_normalize, heading_normalize_full).
        # pf-core's `get_client()` caches a per-model singleton; first
        # call wins, so passing the resolved timeout here propagates to
        # all downstream `chat()` invocations on the cached client.
        # Without this, pf-core's internal `DEFAULT_TIMEOUT_SECONDS = 600`
        # is silently used and bumps via the env var have no effect.
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
    Errors from the underlying client are re-raised after writing a
    ``status='failed'`` row to the DB.

    Args:
        slug: Pagespeak agent slug — ``"vision"``,
            ``"heading_normalize"``, or ``"heading_normalize_full"``.
        messages: Chat-format message list passed verbatim to the
            underlying client.
        prompt_version: Version int of the prompt being used (from the
            agent's prompt-loader module). Recorded for replay /
            regression-tracking.
        system_prompt_text: the canonical (unrendered) system-
            prompt template for this agent, e.g. ``DIAGRAM_PROMPT`` or
            ``HEADING_NORMALIZE_PROMPT``. When provided, gets registered
            (idempotently) in ``llm_prompts`` via pf-core's
            :func:`pf_core.llm.tracking._resolvers.resolve_prompt_id` and
            the resulting id is set as ``llm_runs.system_prompt_id``.
            Pair with ``prompt_version`` to track template-version
            cohorts across runs. None skips the prompt-table write.
        model_override: Explicit per-call model override (CLI flag).
            Wins over env var and YAML.
        backend_override: Explicit backend selection that bypasses the
            ``PAGESPEAK_<SLUG>_BACKEND`` env var. Used by backward-
            compat backend classes (e.g. ``AnthropicVisionBackend``)
            that encode their backend identity in the class name.
        client_override: Pre-constructed client object exposing
            ``.chat(messages, model, **kwargs) -> (content, usage)``.
            When set, bypasses ``_get_client_for_backend``. Used by
            tests that inject mock clients.
        metadata: Task-specific extras attached to the tracking row
            (image phash, anchors_included, heading_count, etc.).
    """
    backend = backend_override or resolve_backend(slug)
    cfg = resolve_agent_config(slug, model_override=model_override, backend=backend)
    client = client_override if client_override is not None else _get_client_for_backend(backend)

    # Strip pagespeak-only keys (e.g. `max_input_tokens`) so they don't
    # leak into client.chat() as unknown kwargs that the underlying SDK
    # would reject. Pagespeak callers read these via
    # `resolve_agent_config(slug).get(key)` directly. The tracking-row
    # write below still sees the full cfg.
    chat_kwargs = {k: v for k, v in cfg.items() if k not in _PAGESPEAK_ONLY_CFG_KEYS}

    started_at = time.time()
    success = False
    error: str | None = None
    error_class: str | None = None
    content = ""
    usage: dict[str, Any] = {}
    try:
        content, usage = client.chat(messages=messages, **chat_kwargs)
        success = True
    except Exception as e:
        error = str(e)
        error_class = type(e).__name__
        raise
    finally:
        duration_ms = int((time.time() - started_at) * 1000)
        # Ensure pf-core's usage tracking sees a duration even when the
        # client doesn't supply one.
        usage = dict(usage) if usage else {}
        usage.setdefault("duration_ms", duration_ms)
        run_id = _write_run_row(
            slug=slug,
            backend=backend,
            cfg=cfg,
            prompt_version=prompt_version,
            system_prompt_text=system_prompt_text,
            messages=messages,
            response_content=content,
            usage=usage,
            success=success,
            error=error,
            error_class=error_class,
            metadata=metadata or {},
        )
        # Per-conversion accumulator (no-op when not recording).
        _append_call_record(
            {
                "task": slug,
                "backend": backend,
                "model": cfg["model"],
                "prompt_version": prompt_version,
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "cost_usd": float(usage.get("cost_usd", 0.0)),
                "duration_ms": duration_ms,
                "success": success,
                "run_id": run_id,
            }
        )

    return content, run_id


def _write_run_row(
    *,
    slug: str,
    backend: Backend,
    cfg: dict[str, Any],
    prompt_version: int,
    system_prompt_text: str | None,
    messages: list[dict[str, Any]],
    response_content: str,
    usage: dict[str, Any],
    success: bool,
    error: str | None,
    error_class: str | None,
    metadata: dict[str, Any],
) -> int | None:
    """Write one ``llm_runs`` row + related table rows via pf-core's
    ``LlmRunRepo.record()``. No-op if the DB hasn't been initialized
    (pagespeak's ``init_db`` wasn't called).

    Tracking failures never break the conversion pipeline — any
    exception writing the row is logged and the call returns ``None``.

    when ``system_prompt_text`` is provided, registers (or
    looks up) the prompt template in ``llm_prompts`` via pf-core's
    ``resolve_prompt_id`` and threads the resulting id through as
    ``llm_runs.system_prompt_id`` so the call is tied to a specific
    versioned template.
    """
    from pagespeak import _db

    if not _db._initialized:
        return None

    try:
        from pf_core.llm.tracking import LlmRunRepo
        from pf_core.llm.tracking._resolvers import (
            resolve_agent_type_id,
            resolve_prompt_id,
        )

        # Render system + user prompts from the messages list for
        # storage in `llm_run_payloads`. pf-core's `record()` accepts
        # them as a (system, user) tuple; we extract them by role.
        rendered_system: str | None = None
        rendered_user: str | None = None
        for msg in messages:
            role = msg.get("role")
            text = msg.get("content")
            if not isinstance(text, str):
                # Multimodal / structured content — skip rendering.
                continue
            if role == "system" and rendered_system is None:
                rendered_system = text
            elif role == "user" and rendered_user is None:
                rendered_user = text

        # Resolve the prompt template id (idempotent INSERT in
        # `llm_prompts` on first sight; lookup thereafter). Stored as
        # `part='system'` since this is the agent's canonical
        # instruction set — both vision and heading-normalize put their
        # template in the system slot, regardless of which API role the
        # underlying SDK sends it in.
        system_prompt_id: int | None = None
        if system_prompt_text:
            agent_type_id = resolve_agent_type_id(slug)
            system_prompt_id = resolve_prompt_id(
                agent_type_id=agent_type_id,
                part="system",
                version=prompt_version,
                content=system_prompt_text,
            )

        # pf-core's `record()` picks known sampling kwargs out of the
        # `sampling` dict; pass anything in the resolved config aside
        # from `model` (its own arg) and pagespeak-only keys (not part
        # of the actual chat() call, recorded separately if needed).
        sampling = {
            k: v for k, v in cfg.items() if k != "model" and k not in _PAGESPEAK_ONLY_CFG_KEYS
        }

        # merge session metadata (set by `to_markdown` via
        # `begin_call_recording(session_metadata=...)`) with per-call
        # metadata, then split string-shaped fields into `tags` and
        # numeric-shaped fields into `metrics` for pf-core's record().
        # Per-call values win over session values on key collision.
        with _call_records_lock:
            session_md_snapshot = dict(_session_metadata) if _session_metadata else {}
        combined_metadata: dict[str, Any] = session_md_snapshot
        combined_metadata.update(metadata)
        tags, metrics = _split_metadata_to_tags_and_metrics(combined_metadata)

        repo = LlmRunRepo()
        run_id: int = repo.record(
            agent_type=slug,
            model=cfg["model"],
            provider=backend,
            usage=usage,
            sampling=sampling,
            status="success" if success else "failed",
            error=(error or "")[:10_000] if error else None,
            error_class=error_class,
            system_prompt_id=system_prompt_id,
            rendered_prompts=(rendered_system, rendered_user),
            raw_response=response_content or None,
            tags=tags or None,
            metrics=metrics or None,
            job_id=_job_id_from_env(),
        )
        return run_id
    except Exception as e:
        # Tracking-sink failure must never break the conversion.
        logger.warning("llm_runs_write_failed slug=%s error=%s", slug, e)
        return None


__all__ = [
    "Backend",
    "begin_call_recording",
    "end_call_recording",
    "invoke_agent",
    "resolve_agent_config",
    "resolve_backend",
]
