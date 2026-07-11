"""Tests for `pagespeak._agent_runtime` — invoke_agent seam.

Covers:

- `resolve_agent_config`: precedence between override-kwarg, env var,
  per-backend YAML entry, and hardcoded fallback.
- `resolve_backend`: env-var resolution to one of
  `claude_code | anthropic | openrouter`; rejection of unknown values.
- `invoke_agent`: dispatch to the right pf-core client; capture of
  usage/duration/error into the returned tuple.
- DB tracking: when `pagespeak._db.init_db()` has been called, every
  successful invoke writes one `llm_runs` row.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """Reset pf-core's engine cache + pagespeak's DB-init flag + every
    pf-core client singleton between tests. Without this, modules cache
    state from earlier tests and we see ghost engines / wrong models /
    leaked DBs."""
    from pf_core.clients import claude_code as cc
    from pf_core.clients import openrouter as orr
    from pf_core.db.connection import reset_engine

    import pagespeak._db as db_mod

    reset_engine()
    db_mod._initialized = False
    cc.reset_client()
    orr.reset_client()
    # Anthropic client has a reset too, but it requires an API key on
    # creation — only reset if we'd actually used it.
    try:
        from pf_core.clients import anthropic as anth

        anth.reset_client()
    except Exception:
        pass
    # pf-core's resolver-caches (llm_agent_types, llm_models) are
    # module-level dicts that survive across tests. If a prior test
    # populated them against a different SQLite tmp_path, a later test
    # gets a cached id that doesn't exist in its fresh DB — FK INSERTs
    # downstream then fail. Clear before AND after each test.
    from pf_core.llm.tracking._resolvers import clear_caches as _clear_resolver_caches

    _clear_resolver_caches()
    yield
    reset_engine()
    db_mod._initialized = False
    cc.reset_client()
    orr.reset_client()
    _clear_resolver_caches()


# --- resolve_agent_config -------------------------------------------------


def test_resolve_agent_config_picks_backend_specific_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backend env var selects which subtree of the agent's
    `backends:` block is read."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        """agents:
  vision:
    backends:
      claude_code:
        model: haiku-via-claude-code
      openrouter:
        model: gemini-via-openrouter
""",
        encoding="utf-8",
    )
    from pagespeak._agent_runtime import resolve_agent_config

    monkeypatch.delenv("PAGESPEAK_VISION_MODEL", raising=False)

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "claude_code")
    assert resolve_agent_config("vision")["model"] == "haiku-via-claude-code"

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")
    assert resolve_agent_config("vision")["model"] == "gemini-via-openrouter"


def test_resolve_agent_config_explicit_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `model_override` kwarg beats env var beats YAML beats hardcoded."""
    from pagespeak._agent_runtime import resolve_agent_config

    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "from-env")
    cfg = resolve_agent_config("vision", model_override="from-arg")
    assert cfg["model"] == "from-arg"


def test_resolve_agent_config_ignores_legacy_env_model_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The legacy `PAGESPEAK_<SLUG>_MODEL` env var is no
    longer consulted. YAML is the single source of truth for model
    config; env vars are reserved for backend selection only."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        "agents:\n  vision:\n    backends:\n      claude_code:\n        model: from-yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "from-env-ignored")
    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "claude_code")
    from pagespeak._agent_runtime import resolve_agent_config

    assert resolve_agent_config("vision")["model"] == "from-yaml"


def test_resolve_agent_config_falls_back_to_hardcoded_haiku_when_config_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the resolved config yields no model — MODEL_ROUTER_CONFIG points
    at a missing file, so neither the cwd config nor the packaged default is
    read — resolution ends at the hardcoded haiku fallback."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAGESPEAK_VISION_MODEL", raising=False)
    monkeypatch.delenv("PAGESPEAK_VISION_BACKEND", raising=False)
    monkeypatch.setenv("MODEL_ROUTER_CONFIG", str(tmp_path / "missing.yaml"))
    from pagespeak._agent_runtime import resolve_agent_config

    cfg = resolve_agent_config("vision")
    assert cfg["model"] == "claude-haiku-4-5-20251001"


def test_resolve_agent_config_uses_packaged_default_when_no_cwd_or_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installed copy — no MODEL_ROUTER_CONFIG env and no cwd
    config/model_router.yaml — falls back to the model_router.yaml bundled in
    the package, so the tuned defaults ship (not the hardcoded haiku)."""
    monkeypatch.chdir(tmp_path)  # no config/ here → forces the packaged default
    monkeypatch.delenv("MODEL_ROUTER_CONFIG", raising=False)
    from pagespeak._agent_runtime import resolve_agent_config

    cfg = resolve_agent_config("heading_normalize_full", backend="claude_code")
    # The packaged default sets claude_code → opus for llm_full; the
    # hardcoded fallback would instead be claude-haiku-4-5-20251001.
    assert cfg["model"] == "opus"
    assert cfg["max_input_tokens"] == 800000  # a packaged-default kwarg


def test_resolve_agent_config_unknown_slug_raises() -> None:
    from pagespeak._agent_runtime import resolve_agent_config

    with pytest.raises(KeyError):
        resolve_agent_config("nonexistent_agent")


def test_resolve_agent_config_shared_kwargs_overlay_with_backend_specific(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Top-level agent kwargs (temperature, max_tokens) apply to all
    backends. Backend-specific kwargs overlay them."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        """agents:
  vision:
    temperature: 0.5
    max_tokens: 4000
    backends:
      claude_code:
        model: shared-temp-model
      openrouter:
        model: override-temp-model
        temperature: 0.1
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("PAGESPEAK_VISION_MODEL", raising=False)
    from pagespeak._agent_runtime import resolve_agent_config

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "claude_code")
    cfg = resolve_agent_config("vision")
    assert cfg["model"] == "shared-temp-model"
    assert cfg["temperature"] == 0.5
    assert cfg["max_tokens"] == 4000

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")
    cfg = resolve_agent_config("vision")
    assert cfg["model"] == "override-temp-model"
    assert cfg["temperature"] == 0.1  # backend-specific overrides shared
    assert cfg["max_tokens"] == 4000  # shared still applies


def test_invoke_agent_strips_pagespeak_only_keys_before_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pagespeak-side YAML keys like `max_input_tokens` must
    not leak into `client.chat()` as kwargs (the underlying SDK would
    reject them as unknown). The key remains visible on
    `resolve_agent_config(slug)` for pagespeak callers to read."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "model_router.yaml").write_text(
        """agents:
  heading_normalize_full:
    max_input_tokens: 250000
    backends:
      claude_code:
        model: haiku-test
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND", "claude_code")

    from pagespeak._agent_runtime import invoke_agent, resolve_agent_config

    # Visible on resolve_agent_config().
    cfg = resolve_agent_config("heading_normalize_full")
    assert cfg["max_input_tokens"] == 250000
    assert cfg["model"] == "haiku-test"

    # Not passed to chat().
    captured: list[dict] = []
    fake = _make_fake_client(captured)
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        invoke_agent(
            "heading_normalize_full",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
        )
    assert "max_input_tokens" not in captured[0]["kwargs"]
    # `model` still threads through.
    assert captured[0]["model"] == "haiku-test"


# --- resolve_backend ------------------------------------------------------


def test_resolve_backend_returns_three_way_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pagespeak._agent_runtime import resolve_backend

    monkeypatch.delenv("PAGESPEAK_VISION_BACKEND", raising=False)
    assert resolve_backend("vision") == "claude_code"  # default

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "anthropic")
    assert resolve_backend("vision") == "anthropic"

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")
    assert resolve_backend("vision") == "openrouter"


def test_resolve_backend_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from pagespeak._agent_runtime import resolve_backend

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "bogus")
    with pytest.raises(ValueError, match="unknown backend"):
        resolve_backend("vision")


def test_resolve_backend_unknown_slug_raises() -> None:
    from pagespeak._agent_runtime import resolve_backend

    with pytest.raises(KeyError):
        resolve_backend("nonexistent_agent")


# --- invoke_agent ---------------------------------------------------------


def _make_fake_client(captured: list[dict], response: str = "response") -> object:
    """Build a fake client whose .chat() captures the call kwargs."""

    class FakeClient:
        def chat(self, *, messages, model, **kwargs):
            captured.append({"messages": messages, "model": model, "kwargs": kwargs})
            return (
                response,
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "cost_usd": 0.001,
                    "duration_ms": 50,
                },
            )

    return FakeClient()


def test_invoke_agent_dispatches_to_routed_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """invoke_agent picks the right client based on resolved backend."""
    from pagespeak._agent_runtime import invoke_agent

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")
    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "google/gemini-2.5-flash")

    captured: list[dict] = []
    fake = _make_fake_client(captured)

    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        content, run_id = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "test"}],
            prompt_version=1,
        )

    assert content == "response"
    assert run_id is None  # DB not initialized → no row written
    assert len(captured) == 1
    assert captured[0]["model"] == "google/gemini-2.5-flash"
    assert captured[0]["messages"] == [{"role": "user", "content": "test"}]


def test_invoke_agent_passes_explicit_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-call `model_override` wins over env-var + YAML."""
    from pagespeak._agent_runtime import invoke_agent

    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "ignored")

    captured: list[dict] = []
    with patch(
        "pagespeak._agent_runtime._get_client_for_backend",
        return_value=_make_fake_client(captured),
    ):
        invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
            model_override="explicit-haiku",
        )

    assert captured[0]["model"] == "explicit-haiku"


def test_invoke_agent_reraises_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the underlying client.chat() raises, invoke_agent re-raises
    the same exception. Tracking write (if DB initialized) still
    happens with status=failed."""
    from pagespeak._agent_runtime import invoke_agent

    class FailingClient:
        def chat(self, **kwargs):
            raise RuntimeError("simulated client failure")

    with (
        patch(
            "pagespeak._agent_runtime._get_client_for_backend",
            return_value=FailingClient(),
        ),
        pytest.raises(RuntimeError, match="simulated client failure"),
    ):
        invoke_agent("vision", messages=[{"role": "user", "content": "x"}], prompt_version=1)


def test_invoke_agent_writes_llm_runs_row_when_db_initialized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When pf-core tracking DB is initialized, invoke_agent writes
    one llm_runs row per call."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")
    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")
    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "google/gemini-2.5-flash")

    from pagespeak._agent_runtime import invoke_agent
    from pagespeak._db import get_engine, init_db

    init_db()

    captured: list[dict] = []
    with patch(
        "pagespeak._agent_runtime._get_client_for_backend",
        return_value=_make_fake_client(captured),
    ):
        content, run_id = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
        )

    assert run_id is not None
    assert run_id > 0

    # Verify exactly one llm_runs row written and it carries the
    # expected agent slug + model + provider.
    from sqlalchemy import text

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.slug, m.name, r.provider, "
                "r.prompt_tokens, r.completion_tokens, r.cost_usd "
                "FROM llm_runs r "
                "JOIN llm_agent_types a ON a.id = r.agent_type_id "
                "JOIN llm_models m ON m.id = r.model_id "
                "ORDER BY r.id"
            )
        ).fetchall()
    assert len(rows) == 1
    slug, model_name, provider, ptok, ctok, cost = rows[0]
    assert slug == "vision"
    assert model_name.endswith("gemini-2.5-flash")
    assert provider == "openrouter"
    assert ptok == 10
    assert ctok == 20
    # cost_usd may be stored as Decimal/float depending on dialect
    assert abs(float(cost) - 0.001) < 1e-9


def test_invoke_agent_registers_system_prompt_in_llm_prompts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When `system_prompt_text` is supplied, invoke_agent
    registers the template in `llm_prompts` (idempotent INSERT keyed by
    (agent_type, part, version)) and threads the resulting id through to
    `llm_runs.system_prompt_id`, so every llm_run keeps its template lineage."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")
    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")

    from pagespeak._agent_runtime import invoke_agent
    from pagespeak._db import get_engine, init_db

    init_db()

    captured: list[dict] = []
    fake = _make_fake_client(captured)
    prompt_text = "You are a diagram analyzer. Output JSON."

    # Two calls with the same (agent, version, content) → llm_prompts
    # stays at one row (idempotent), but two llm_runs both FK to it.
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        _, run_id_a = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=3,
            system_prompt_text=prompt_text,
        )
        _, run_id_b = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "y"}],
            prompt_version=3,
            system_prompt_text=prompt_text,
        )

    from sqlalchemy import text

    with get_engine().connect() as conn:
        prompt_rows = conn.execute(
            text("SELECT id, part, version, content FROM llm_prompts ORDER BY id")
        ).fetchall()
        run_rows = conn.execute(
            text("SELECT id, system_prompt_id FROM llm_runs ORDER BY id")
        ).fetchall()

    # One prompt row, two runs both linked to it.
    assert len(prompt_rows) == 1
    prompt_id, part, version, content = prompt_rows[0]
    assert part == "system"
    assert version == 3
    assert content == prompt_text

    assert len(run_rows) == 2
    assert run_rows[0][1] == prompt_id
    assert run_rows[1][1] == prompt_id
    assert run_id_a is not None and run_id_b is not None


def test_invoke_agent_no_prompt_registration_when_text_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Backward-compat: callers that don't pass `system_prompt_text`
    (yet) still write llm_runs rows with NULL system_prompt_id. No
    accidental empty-content INSERTs into `llm_prompts`."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")

    from pagespeak._agent_runtime import invoke_agent
    from pagespeak._db import get_engine, init_db

    init_db()

    fake = _make_fake_client([])
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
        )

    from sqlalchemy import text

    with get_engine().connect() as conn:
        prompt_count = conn.execute(text("SELECT count(*) FROM llm_prompts")).scalar()
        run_prompt_id = conn.execute(text("SELECT system_prompt_id FROM llm_runs LIMIT 1")).scalar()

    assert prompt_count == 0
    assert run_prompt_id is None


def test_invoke_agent_metadata_splits_into_tags_and_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Per-call metadata flows through `_write_run_row` into
    pf-core's `tags` / `metrics` kwargs, landing in `llm_run_tags` and
    `llm_run_metrics`. String / bool values → tags as `"key:value"`;
    numeric values → metrics with the value cast to float."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")

    from pagespeak._agent_runtime import invoke_agent
    from pagespeak._db import get_engine, init_db

    init_db()

    fake = _make_fake_client([])
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        _, run_id = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
            metadata={
                "image_basename": "_page_303_Picture_4.jpeg",
                "image_phash": "ab12cd34ef56" + "0" * 4,  # 16 chars
                "anchors_included": True,
                "heading_count": 1750,
                "irrelevant": None,  # dropped
            },
        )

    assert run_id is not None
    from sqlalchemy import text

    with get_engine().connect() as conn:
        tags = {
            row[0]
            for row in conn.execute(
                text("SELECT tag FROM llm_run_tags WHERE llm_run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }
        metrics = {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT metric_name, metric_value FROM llm_run_metrics WHERE llm_run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }

    assert tags == {
        "image_basename:_page_303_Picture_4.jpeg",
        "image_phash:ab12cd34ef560000",
        "anchors_included:true",
    }
    assert metrics == {"heading_count": 1750.0}


def test_begin_call_recording_session_metadata_attaches_to_every_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`begin_call_recording(session_metadata={...})` stashes
    session-level tags that get merged into every `invoke_agent` call
    within the window. Per-call metadata wins on key collision."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")

    from pagespeak._agent_runtime import (
        begin_call_recording,
        end_call_recording,
        invoke_agent,
    )
    from pagespeak._db import get_engine, init_db

    init_db()

    fake = _make_fake_client([])
    begin_call_recording(session_metadata={"source_basename": "textbook.pdf"})
    try:
        with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
            _, run_a = invoke_agent(
                "vision",
                messages=[{"role": "user", "content": "x"}],
                prompt_version=1,
                metadata={"image_basename": "img1.png"},
            )
            _, run_b = invoke_agent(
                "vision",
                messages=[{"role": "user", "content": "y"}],
                prompt_version=1,
                metadata={"image_basename": "img2.png"},
            )
    finally:
        end_call_recording()

    from sqlalchemy import text

    with get_engine().connect() as conn:
        tags_by_run: dict[int, set[str]] = {}
        for run_id in (run_a, run_b):
            tags_by_run[run_id] = {
                row[0]
                for row in conn.execute(
                    text("SELECT tag FROM llm_run_tags WHERE llm_run_id = :r"),
                    {"r": run_id},
                ).fetchall()
            }

    # Both calls inherit the session tag.
    assert "source_basename:textbook.pdf" in tags_by_run[run_a]
    assert "source_basename:textbook.pdf" in tags_by_run[run_b]
    # Per-call metadata is also captured.
    assert "image_basename:img1.png" in tags_by_run[run_a]
    assert "image_basename:img2.png" in tags_by_run[run_b]
    # No cross-contamination.
    assert "image_basename:img2.png" not in tags_by_run[run_a]
    assert "image_basename:img1.png" not in tags_by_run[run_b]


def test_per_call_metadata_overrides_session_metadata_on_key_collision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Per-call metadata wins over session-level."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/track.db")

    from pagespeak._agent_runtime import (
        begin_call_recording,
        end_call_recording,
        invoke_agent,
    )
    from pagespeak._db import get_engine, init_db

    init_db()

    fake = _make_fake_client([])
    begin_call_recording(session_metadata={"role": "session-value"})
    try:
        with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
            _, run_id = invoke_agent(
                "vision",
                messages=[{"role": "user", "content": "x"}],
                prompt_version=1,
                metadata={"role": "per-call-wins"},
            )
    finally:
        end_call_recording()

    from sqlalchemy import text

    with get_engine().connect() as conn:
        tags = {
            row[0]
            for row in conn.execute(
                text("SELECT tag FROM llm_run_tags WHERE llm_run_id = :r"),
                {"r": run_id},
            ).fetchall()
        }

    assert "role:per-call-wins" in tags
    assert "role:session-value" not in tags


def test_invoke_agent_skips_db_write_when_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `init_db` has not been called, invoke_agent returns run_id=None
    and writes no rows. Pagespeak still works as a library without
    tracking; init_db is opt-in."""
    from pagespeak._agent_runtime import invoke_agent

    captured: list[dict] = []
    with patch(
        "pagespeak._agent_runtime._get_client_for_backend",
        return_value=_make_fake_client(captured),
    ):
        content, run_id = invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
        )

    assert run_id is None


def test_invoke_agent_backend_override_bypasses_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`backend_override` wins over the `PAGESPEAK_<SLUG>_BACKEND` env
    var so backward-compat backend classes can encode their identity
    in the class name."""
    from pagespeak._agent_runtime import invoke_agent

    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "openrouter")

    captured: list[dict] = []
    fake = _make_fake_client(captured)
    # `_get_client_for_backend` is invoked with the override, not the env.
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake) as mock_get:
        invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
            backend_override="anthropic",
        )
    assert mock_get.call_args.args == ("anthropic",)


def test_invoke_agent_client_override_bypasses_client_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`client_override` bypasses `_get_client_for_backend` so test
    fixtures can inject mock clients without setting up pf-core
    singletons."""
    from pagespeak._agent_runtime import invoke_agent

    captured: list[dict] = []
    mock_client = _make_fake_client(captured)

    # If client_override is honored, _get_client_for_backend must NOT
    # be called at all.
    with patch(
        "pagespeak._agent_runtime._get_client_for_backend",
        side_effect=AssertionError("client_override should bypass this"),
    ):
        invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
            client_override=mock_client,
        )

    assert len(captured) == 1


# --- per-conversion call recording -----------------------------


def test_call_recording_captures_invoke_agent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Between `begin_call_recording()` and `end_call_recording()`,
    every `invoke_agent` call appends one record to the active list."""
    from pagespeak._agent_runtime import (
        begin_call_recording,
        end_call_recording,
        invoke_agent,
    )

    captured: list[dict] = []
    fake = _make_fake_client(captured)

    begin_call_recording()
    try:
        with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
            invoke_agent(
                "vision",
                messages=[{"role": "user", "content": "x"}],
                prompt_version=2,
            )
            invoke_agent(
                "heading_normalize",
                messages=[{"role": "user", "content": "y"}],
                prompt_version=1,
            )
        records = end_call_recording()
    finally:
        # Belt-and-suspenders cleanup in case the test fails mid-block.
        end_call_recording()

    assert len(records) == 2
    assert records[0]["task"] == "vision"
    assert records[0]["prompt_version"] == 2
    assert records[0]["prompt_tokens"] == 10
    assert records[0]["completion_tokens"] == 20
    assert records[0]["success"] is True
    assert records[1]["task"] == "heading_normalize"


def test_call_recording_is_noop_when_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `begin_call_recording()` was never called, `invoke_agent`
    runs normally — no accumulator side-effect, no error."""
    from pagespeak._agent_runtime import end_call_recording, invoke_agent

    # Ensure no active recording from a prior test.
    end_call_recording()

    captured: list[dict] = []
    fake = _make_fake_client(captured)
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        invoke_agent(
            "vision",
            messages=[{"role": "user", "content": "x"}],
            prompt_version=1,
        )

    # No active recording → end_call_recording returns empty list.
    records = end_call_recording()
    assert records == []


def test_end_call_recording_returns_records_then_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second `end_call_recording()` call returns [] — the
    accumulator is drained on the first call."""
    from pagespeak._agent_runtime import (
        begin_call_recording,
        end_call_recording,
        invoke_agent,
    )

    fake = _make_fake_client([])
    begin_call_recording()
    with patch("pagespeak._agent_runtime._get_client_for_backend", return_value=fake):
        invoke_agent("vision", messages=[{"role": "user", "content": "x"}], prompt_version=1)

    first = end_call_recording()
    second = end_call_recording()
    assert len(first) == 1
    assert second == []


# --- claude_code singleton timeout wiring (regression test for
#     PAGESPEAK_CLAUDE_CODE_TIMEOUT_S reaching the real client) ---


def test_get_client_for_backend_passes_default_timeout_to_claude_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without PAGESPEAK_CLAUDE_CODE_TIMEOUT_S, `_get_client_for_backend`
    must pass our 1800s default (NOT pf-core's internal 600s default)
    to `claude_code.get_client` — otherwise pf-core's
    DEFAULT_TIMEOUT_SECONDS=600 silently wins."""
    from pagespeak._agent_runtime import _get_client_for_backend

    monkeypatch.delenv("PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", raising=False)
    with patch("pf_core.clients.claude_code.get_client") as mock_get_client:
        _get_client_for_backend("claude_code")
    mock_get_client.assert_called_once()
    assert mock_get_client.call_args.kwargs["timeout"] == 1800


def test_get_client_for_backend_respects_env_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting PAGESPEAK_CLAUDE_CODE_TIMEOUT_S=N must reach
    `claude_code.get_client(timeout=N)` on the live path."""
    from pagespeak._agent_runtime import _get_client_for_backend

    monkeypatch.setenv("PAGESPEAK_CLAUDE_CODE_TIMEOUT_S", "2400")
    with patch("pf_core.clients.claude_code.get_client") as mock_get_client:
        _get_client_for_backend("claude_code")
    assert mock_get_client.call_args.kwargs["timeout"] == 2400


def test_pf_core_claude_code_client_isolates_by_default() -> None:
    """Dependency-floor canary: pf-core >= 0.5.0 runs `claude --print` with
    `--safe-mode` by default (`isolate=True`), so the cwd project's CLAUDE.md/
    skills can't hijack a vision caption or normalize call. A downgrade below
    that floor silently reintroduces the hijack — this catches it."""
    import inspect

    from pf_core.clients.claude_code import ClaudeCodeClient

    assert inspect.signature(ClaudeCodeClient.__init__).parameters["isolate"].default is True
