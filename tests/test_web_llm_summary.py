from __future__ import annotations

import pf_core.db.connection as conn_mod
import pytest
from fastapi.testclient import TestClient

from pagespeak.web import create_app


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    # pf_core caches agent_type_id/model_id in-process; across tests that each
    # build a fresh temp DB those cached ids go stale and cause FK failures.
    from pf_core.llm.tracking import clear_resolver_caches as clear_caches

    clear_caches()
    yield
    clear_caches()


def _client(monkeypatch, tmp_path):
    conv = tmp_path / "conversions"
    (conv / "in").mkdir(parents=True)
    (conv / "out" / "doc").mkdir(parents=True)
    (conv / "out" / "doc" / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    monkeypatch.setenv("PAGESPEAK_CONVERSIONS_DIR", str(conv))
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    return TestClient(create_app(start_worker=False)), conv


def test_llm_summary_counts_runs_for_conversion_jobs(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)

    from pf_core.jobs import JobRepo
    from pf_core.llm.tracking import LlmRunRepo

    from pagespeak.web._jobs import CONVERSION_KIND

    jid = JobRepo().create(
        kind=CONVERSION_KIND,
        inputs={"out_dir": str(conv / "out" / "doc"), "options": {}},
        created_by="web",
    )
    LlmRunRepo().record(agent_type="vision", model="m", job_id=jid, usage={"cost_usd": 0.01})

    r = client.get("/partials/llm/doc")
    assert r.status_code == 200
    assert "1" in r.text
