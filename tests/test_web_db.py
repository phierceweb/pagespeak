from __future__ import annotations

import pf_core.db.connection as conn_mod

from pagespeak.web._db import init_web_db


def test_init_web_db_creates_jobs_and_llm_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False

    init_web_db()

    from pf_core.jobs import JobRepo, clear_registry, register_kind

    clear_registry()
    register_kind(kind="t_kind")
    jid = JobRepo().create(kind="t_kind", inputs=None, created_by="test")
    assert isinstance(jid, int)
    from pf_core.llm.tracking import LlmRunRepo

    rid = LlmRunRepo().record(agent_type="vision", model="m", job_id=jid)
    assert isinstance(rid, int)
