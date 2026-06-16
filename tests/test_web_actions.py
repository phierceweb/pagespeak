from __future__ import annotations

import pf_core.db.connection as conn_mod
from fastapi.testclient import TestClient

from pagespeak.web import create_app


def _client(monkeypatch, tmp_path):
    conv = tmp_path / "conversions"
    (conv / "in").mkdir(parents=True)
    (conv / "out").mkdir(parents=True)
    monkeypatch.setenv("PAGESPEAK_CONVERSIONS_DIR", str(conv))
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    return TestClient(create_app(start_worker=False)), conv


def test_upload_saves_to_in(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    r = client.post(
        "/api/upload",
        files={"file": ("My Doc.pdf", b"data", "application/pdf")},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)
    assert (conv / "in" / "My Doc.pdf").is_file()


def test_run_diagrams_off_creates_pending_job(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    r = client.post("/api/run/doc", data={"diagrams": "false"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    from pf_core.jobs import JobRepo

    jobs = JobRepo().find(kind="pagespeak_convert")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"


def test_run_returns_live_status_fragment(monkeypatch, tmp_path):
    # A successful run replies with the live status line (into #run-result),
    # not a redirect — so the user gets immediate feedback.
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    r = client.post("/api/run/doc", data={"diagrams": "false"})
    assert r.status_code == 200
    assert "Queued" in r.text
    assert "/partials/job/" in r.text  # self-poll wired up


def test_run_cache_only_without_diagrams_is_dropped(monkeypatch, tmp_path):
    # vision_cache_only requires diagrams (the converter raises otherwise). A
    # POST with the invalid combo must be normalized, not turned into a failing job.
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    client.post(
        "/api/run/doc",
        data={"diagrams": "false", "vision_cache_only": "true"},
        follow_redirects=False,
    )
    from pf_core.jobs import JobRepo

    jobs = JobRepo().find(kind="pagespeak_convert")
    assert len(jobs) == 1
    opts = jobs[0]["inputs"]["options"]
    assert opts["diagrams"] is False
    assert opts["vision_cache_only"] is False  # guarded: dropped because diagrams off


def test_run_live_vision_needs_confirm(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    (out / "images").mkdir(parents=True)
    (out / "images" / "a.png").write_bytes(b"a")
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")

    r = client.post(
        "/api/run/doc", data={"diagrams": "true", "start": "vision", "stop_after": "vision"}
    )
    assert r.status_code == 200
    assert "confirm" in r.text.lower()
    from pf_core.jobs import JobRepo

    assert JobRepo().find(kind="pagespeak_convert") == []


def test_deliver_strips_to_delivery_dir(monkeypatch, tmp_path):
    # The detail-page Deliver button mirrors `pagespeak deliver`: copy only
    # the master .md + sections/ + images/ into a parallel conversions/delivery/
    # dir, dropping checkpoints/caches/run records.
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir(parents=True)
    (out / "Doc.md").write_text("# master", encoding="utf-8")
    (out / "Doc.raw.md").write_text("# raw checkpoint", encoding="utf-8")
    (out / "images").mkdir()
    (out / "images" / "a.png").write_bytes(b"a")
    (out / ".pagespeak-run.json").write_text("{}", encoding="utf-8")

    r = client.post("/api/deliver/doc")
    assert r.status_code == 200
    assert "delivered 1 document" in r.text

    delivered = conv / "delivery" / "doc"
    assert (delivered / "Doc.md").is_file()
    assert (delivered / "images" / "a.png").is_file()
    # Working files must NOT have been copied.
    assert not (delivered / "Doc.raw.md").exists()
    assert not (delivered / ".pagespeak-run.json").exists()


def test_deliver_without_master_md_reports_nothing(monkeypatch, tmp_path):
    # An out dir that only has a raw checkpoint (no final .md yet) reports
    # "nothing to deliver", not a 500.
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir(parents=True)
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")

    r = client.post("/api/deliver/doc")
    assert r.status_code == 200
    assert "nothing to deliver" in r.text
    assert not (conv / "delivery" / "doc").exists()


def test_deliver_unknown_conversion_404(monkeypatch, tmp_path):
    client, _conv = _client(monkeypatch, tmp_path)
    r = client.post("/api/deliver/does-not-exist")
    assert r.status_code == 404


def test_run_live_vision_confirmed_creates_job(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    (out / "images").mkdir(parents=True)
    (out / "images" / "a.png").write_bytes(b"a")
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    r = client.post(
        "/api/run/doc",
        data={"diagrams": "true", "start": "vision", "stop_after": "vision", "confirmed": "true"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)
    from pf_core.jobs import JobRepo

    assert len(JobRepo().find(kind="pagespeak_convert")) == 1
