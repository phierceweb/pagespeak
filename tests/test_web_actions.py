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


def test_upload_never_writes_through_a_staged_symlink(monkeypatch, tmp_path):
    """`in/` holds symlinks into an ingester's tree; writing through one would
    overwrite that tree's source file."""
    client, conv = _client(monkeypatch, tmp_path)
    upstream = tmp_path / "upstream.pdf"
    upstream.write_bytes(b"original")
    (conv / "in" / "Manual.pdf").symlink_to(upstream)
    r = client.post("/api/upload", files={"file": ("Manual.pdf", b"replacement")})
    assert r.status_code == 409
    assert upstream.read_bytes() == b"original"


def test_upload_refuses_names_that_are_not_a_plain_file(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    for name in ("..", ".env", "."):
        r = client.post("/api/upload", files={"file": (name, b"x")})
        assert r.status_code == 400, name
    assert not (conv / "in" / ".env").exists()


def test_upload_over_the_cap_is_refused_and_leaves_nothing(monkeypatch, tmp_path):
    """The body cap is also enforced while copying, for a request with no Content-Length."""
    from pagespeak.web.api import actions

    client, conv = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(actions, "max_upload_bytes", lambda: 10)
    r = client.post("/api/upload", files={"file": ("Big.pdf", b"x" * 100)})
    assert r.status_code == 413
    assert sorted(p.name for p in (conv / "in").iterdir()) == []


def test_upload_replaces_a_regular_file(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_bytes(b"old")
    client.post("/api/upload", files={"file": ("Doc.pdf", b"new")})
    assert (conv / "in" / "Doc.pdf").read_bytes() == b"new"


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


def test_deliver_rejects_out_root_alias(monkeypatch, tmp_path):
    # `%2e` decodes to `.`, which resolved to the out root itself — making the
    # destination `delivery/.` and rmtree'ing every previous delivery.
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir(parents=True)
    (out / "Doc.md").write_text("# master", encoding="utf-8")
    keeper = conv / "delivery" / "precious-old-delivery" / "keepme.md"
    keeper.parent.mkdir(parents=True)
    keeper.write_text("# earlier handoff", encoding="utf-8")

    r = client.post("/api/deliver/%2e")

    assert r.status_code == 404
    assert keeper.exists()


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


def _read_before(conv, ingest_flags):
    """A PDF the console already read, with `ingest_flags` naming how."""
    import json

    (conv / "in" / "Doc.pdf").write_bytes(b"%PDF-1.4\n")
    out = conv / "out" / "doc"
    out.mkdir(parents=True)
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"ingest_flags": ingest_flags}), encoding="utf-8"
    )
    return out


def _queued_options():
    from pf_core.jobs import JobRepo

    jobs = JobRepo().find(kind="pagespeak_convert")
    assert len(jobs) == 1
    return jobs[0]["inputs"]["options"]


def test_run_with_another_pdf_reader_re_reads_the_document(monkeypatch, tmp_path):
    """The pipeline refuses a raw.md read by another reader and the form has no
    re-ingest control, so choosing another reader has to re-read."""
    client, conv = _client(monkeypatch, tmp_path)
    _read_before(conv, {"pdf_backend": "marker"})
    r = client.post("/api/run/doc", data={"diagrams": "false", "pdf_backend": "docling"})
    assert r.status_code == 200
    assert _queued_options()["rerun_from"] == "ingest"


def test_run_re_reads_docling_output_without_a_hierarchy(monkeypatch, tmp_path):
    """The console's docling always adds --heading-hierarchy."""
    client, conv = _client(monkeypatch, tmp_path)
    _read_before(conv, {"pdf_backend": "docling", "heading_hierarchy": False})
    client.post("/api/run/doc", data={"diagrams": "false", "pdf_backend": "docling"})
    assert _queued_options()["rerun_from"] == "ingest"


def test_run_with_the_reader_already_used_reuses_the_read(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    _read_before(conv, {"pdf_backend": "docling", "heading_hierarchy": True})
    client.post("/api/run/doc", data={"diagrams": "false", "pdf_backend": "docling"})
    assert _queued_options()["rerun_from"] is None


def test_reader_change_counts_images_as_unknown(monkeypatch, tmp_path):
    """Another reader extracts other images, so today's cache count says nothing."""
    client, conv = _client(monkeypatch, tmp_path)
    out = _read_before(conv, {"pdf_backend": "marker"})
    (out / "images").mkdir()
    (out / "images" / "a.png").write_bytes(b"a")
    r = client.post("/api/run/doc", data={"diagrams": "true", "pdf_backend": "docling"})
    assert "Exact count known after ingest" in r.text


def test_reader_change_with_several_workers_is_refused(monkeypatch, tmp_path):
    """A multi-worker run cannot re-ingest; it would resume the chunks already read."""
    from pf_core.jobs import JobRepo

    client, conv = _client(monkeypatch, tmp_path)
    _read_before(conv, {"pdf_backend": "marker"})
    r = client.post(
        "/api/run/doc", data={"diagrams": "false", "pdf_backend": "docling", "workers": "4"}
    )
    assert r.status_code == 200
    assert "workers" in r.text
    assert JobRepo().find(kind="pagespeak_convert") == []
