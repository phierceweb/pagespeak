from __future__ import annotations


def test_run_job_success_marks_succeeded(monkeypatch, tmp_path):
    import pf_core.db.connection as conn_mod

    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    db.init_db()

    from pf_core.jobs import JobRepo, clear_registry

    from pagespeak.web._jobs import CONVERSION_KIND, register_conversion_kind

    clear_registry()
    register_conversion_kind()

    out = tmp_path / "out" / "doc"
    src = tmp_path / "in" / "Doc.pdf"
    src.parent.mkdir(parents=True)
    src.write_text("x", encoding="utf-8")

    jid = JobRepo().create(
        kind=CONVERSION_KIND,
        inputs={"out_dir": str(out), "source_path": str(src), "options": {"diagrams": False}},
        created_by="test",
    )

    import pagespeak.web._worker as worker

    class _FakeProc:
        returncode = 0

        def __init__(self):
            pass

        def wait(self):
            out.mkdir(parents=True, exist_ok=True)
            (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
            return 0

    def _fake_popen(cmd, **kwargs):  # noqa: ANN001
        return _FakeProc()

    import pf_core.jobs.workers as pf_workers

    monkeypatch.setattr(pf_workers.subprocess, "Popen", _fake_popen)

    job_row = JobRepo().claim_next(kinds=[CONVERSION_KIND], worker_id="w1")
    assert job_row is not None
    worker.run_job(job_row)

    final = JobRepo().get(jid)
    assert final["status"] == "succeeded"


def test_run_job_nonzero_marks_failed(monkeypatch, tmp_path):
    import pf_core.db.connection as conn_mod

    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    db.init_db()

    from pf_core.jobs import JobRepo, clear_registry

    from pagespeak.web._jobs import CONVERSION_KIND, register_conversion_kind

    clear_registry()
    register_conversion_kind()

    out = tmp_path / "out" / "doc"
    src = tmp_path / "in" / "Doc.pdf"
    src.parent.mkdir(parents=True)
    src.write_text("x", encoding="utf-8")
    jid = JobRepo().create(
        kind=CONVERSION_KIND,
        inputs={"out_dir": str(out), "source_path": str(src), "options": {}},
        created_by="test",
    )

    import pagespeak.web._worker as worker

    class _FakeProc:
        returncode = 2

        def wait(self):
            out.mkdir(parents=True, exist_ok=True)
            return 2

    import pf_core.jobs.workers as pf_workers

    monkeypatch.setattr(pf_workers.subprocess, "Popen", lambda cmd, **kw: _FakeProc())

    job_row = JobRepo().claim_next(kinds=[CONVERSION_KIND], worker_id="w1")
    worker.run_job(job_row)
    assert JobRepo().get(jid)["status"] == "failed"
