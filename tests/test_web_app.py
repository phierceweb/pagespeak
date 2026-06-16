from __future__ import annotations

import pf_core.db.connection as conn_mod
from fastapi.testclient import TestClient

from pagespeak.web import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGESPEAK_CONVERSIONS_DIR", str(tmp_path / "conversions"))
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    app = create_app(start_worker=False)
    return TestClient(app)


def test_health_ok(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_home_renders(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "pagespeak" in r.text.lower()


def test_admin_llm_mounted(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/admin/llm/")
    assert r.status_code == 200
