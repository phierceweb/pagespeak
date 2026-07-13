from __future__ import annotations

import pf_core.db.connection as conn_mod
import pytest


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """Clear pf-core resolver caches + DB-init flag + engine between tests.

    Without this, `agent_type_id` / `model_id` resolved against one test's
    SQLite DB are cached and cause FK failures in the next test's fresh DB.
    Mirrors the identical fixture in `test_agent_runtime.py`.
    """
    from pf_core.db.connection import reset_engine
    from pf_core.jobs import clear_registry
    from pf_core.llm.tracking import clear_resolver_caches as _clear_resolver_caches

    import pagespeak._db as db_mod

    reset_engine()
    db_mod._initialized = False
    _clear_resolver_caches()
    clear_registry()
    yield
    reset_engine()
    db_mod._initialized = False
    _clear_resolver_caches()
    # Don't leak this test's throwaway job kind into the global registry —
    # otherwise a later create_app() re-registering its real kinds collides.
    clear_registry()


class _FakeClient:
    def chat(self, *, messages, **kwargs):  # noqa: ANN001
        return "ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0}


def test_job_id_from_env_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    db.init_db()

    from pf_core.jobs import JobRepo, clear_registry, register_kind

    clear_registry()
    register_kind(kind="job_attr_test")
    jid = JobRepo().create(kind="job_attr_test", created_by="test")

    monkeypatch.setenv("PAGESPEAK_JOB_ID", str(jid))

    from pagespeak._agent_runtime import invoke_agent

    _content, run_id = invoke_agent(
        "vision",
        messages=[{"role": "user", "content": "hi"}],
        prompt_version=1,
        client_override=_FakeClient(),
    )
    assert run_id is not None

    from pf_core.llm.tracking import LlmRunRepo

    row = LlmRunRepo().get(run_id)
    assert row is not None
    assert row["job_id"] == jid


def test_no_job_id_env_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PAGESPEAK_JOB_ID", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    db.init_db()

    from pf_core.jobs import clear_registry, register_kind

    clear_registry()
    register_kind(kind="job_attr_test")

    from pagespeak._agent_runtime import invoke_agent

    _content, run_id = invoke_agent(
        "vision",
        messages=[{"role": "user", "content": "hi"}],
        prompt_version=1,
        client_override=_FakeClient(),
    )
    from pf_core.llm.tracking import LlmRunRepo

    row = LlmRunRepo().get(run_id)
    assert row is not None
    assert row["job_id"] is None
