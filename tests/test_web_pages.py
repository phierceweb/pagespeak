from __future__ import annotations

import pf_core.db.connection as conn_mod
from fastapi.testclient import TestClient

from pagespeak.web import create_app


def test_detail_rejects_path_traversal(monkeypatch, tmp_path):
    # An encoded ".." in dir_name must not escape conversions/out/ (it would
    # otherwise resolve to the parent and read files outside the out root).
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "secret.txt").write_text("nope", encoding="utf-8")
    assert client.get("/c/%2e%2e").status_code == 404
    assert client.get("/c/%2e%2e/images/secret.txt").status_code == 404


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


def test_home_lists_conversions(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "New Manual.pdf").write_text("x", encoding="utf-8")
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")

    r = client.get("/")
    assert r.status_code == 200
    assert "new-manual" in r.text
    assert "doc" in r.text


def test_detail_renders_checkpoint_and_images(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# Raw heading\n\ntext", encoding="utf-8")
    (out / "Doc.md").write_text("# Final heading\n\ndone", encoding="utf-8")
    (out / "images").mkdir()
    (out / "images" / "p1.png").write_bytes(b"x")

    r = client.get("/c/doc")
    assert r.status_code == 200
    assert "Doc" in r.text
    assert "Final heading" in r.text

    ri = client.get("/c/doc/images/p1.png")
    assert ri.status_code == 200


def test_detail_404(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    r = client.get("/c/missing")
    assert r.status_code == 404


def test_detail_view_specific_checkpoint(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# Raw only", encoding="utf-8")
    r = client.get("/c/doc?view=ingest")
    assert r.status_code == 200
    assert "Raw only" in r.text


def test_detail_view_pills_cover_all_served_views(monkeypatch, tmp_path):
    # Every checkpoint view the route layer serves must have a clickable pill.
    from pagespeak.web.api.pages import _VIEW_SUFFIX

    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    r = client.get("/c/doc")
    assert r.status_code == 200
    for v in _VIEW_SUFFIX:
        assert f'href="?view={v}"' in r.text


def test_queue_partial_shows_active_jobs(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    client.post("/api/run/doc", data={"diagrams": "false"}, follow_redirects=False)
    r = client.get("/partials/queue")
    assert r.status_code == 200
    assert "doc" in r.text.lower()


def test_actions_partial_has_options_form(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    r = client.get("/partials/actions/doc")
    assert r.status_code == 200
    # Step picker filters options by phase; the Run button is separate.
    assert "Choose what to run" in r.text
    assert 'data-phase="vision"' in r.text  # phase selector button
    assert "data-phases=" in r.text  # options tagged with their relevant phase(s)
    assert "Run full conversion" in r.text  # the (separate) run button
    assert "vision_backend" in r.text
    # Vision is a single 3-way control (not two combinable checkboxes), so the
    # invalid "skip + cached-only" pair can't be selected.
    assert 'id="vision-mode"' in r.text
    assert "Skip images" in r.text
    # Run controls are confirm-guarded against accidental clicks.
    assert "hx-confirm" in r.text
    # Each option has a hover tooltip (ⓘ → styled bubble), plus a link to full help.
    assert "which AI looks at images" in r.text  # a plain-language option label
    assert "tip-box" in r.text  # the hover-tooltip bubble
    assert "/help" in r.text


def test_detail_run_record_tab(monkeypatch, tmp_path):
    import json

    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "preset": None,
                "resolved_flags": {"cleanup": "basic", "diagrams": True, "split_sections": False},
                "input": "Doc.raw.md",
                "finished_at": "2026-05-23T23:18:32Z",
                "section_count": 5,
                "image_count": 3,
                "llm_calls": {"total_calls": 0, "total_cost_usd": 0.0},
            }
        ),
        encoding="utf-8",
    )
    r = client.get("/c/doc")
    assert r.status_code == 200
    assert "tab-btn-runrecord" in r.text  # the run-record tab exists
    assert "Settings used" in r.text  # readable settings table
    assert "last time this document was converted" in r.text  # plain explanation
    assert "0.1.0" in r.text  # a value is shown


def test_help_page_renders(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    r = client.get("/help")
    assert r.status_code == 200
    assert "help" in r.text.lower()
    assert "which AI looks at images" in r.text  # options documented (plain English)
    assert "Cost &amp; safety" in r.text or "Cost & safety" in r.text
    # Pipeline table lists the structure phase between repair and vision.
    assert (
        r.text.index(".repaired.md") < r.text.index(".structured.md") < r.text.index(".visioned.md")
    )


def test_partial_phase_strip_renders(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    r = client.get("/partials/phase-strip/doc")
    assert r.status_code == 200
    assert "ingest" in r.text and "vision" in r.text


def test_partial_job_status_renders(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    from pf_core.jobs import JobRepo

    from pagespeak.web._jobs import CONVERSION_KIND

    jid = JobRepo().create(
        kind=CONVERSION_KIND,
        inputs={"out_dir": str(conv / "out" / "doc"), "options": {}},
        created_by="web",
    )
    r = client.get(f"/partials/job/{jid}")
    assert r.status_code == 200
    assert f"#{jid}" in r.text
    assert "Queued" in r.text  # pending state


def test_partial_image_detail_shows_caption_and_mermaid(monkeypatch, tmp_path):
    import json

    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    (out / "images").mkdir(parents=True)
    (out / "images" / "a.png").write_bytes(b"img")
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    cache = out / ".vision-cache"
    cache.mkdir()
    (cache / "HASH.json").write_text(
        json.dumps(
            {
                "caption": "A flow of water through the dimmer",
                "mermaid": "graph TD; A-->B;",
                "diagram_type": "flowchart",
            }
        ),
        encoding="utf-8",
    )
    # The route phashes the image and reads .vision-cache/<phash>.json; pin the
    # phash so it maps to our fixture cache entry.
    import pagespeak.web.api.partials as partials

    monkeypatch.setattr(partials, "compute_phash", lambda p: "HASH")

    r = client.get("/partials/image/doc/a.png")
    assert r.status_code == 200
    assert "A flow of water through the dimmer" in r.text  # caption / alt text
    assert "graph TD" in r.text  # mermaid source
    assert "flowchart" in r.text  # diagram type


def test_detail_uses_zero_md_with_raw_toggle(monkeypatch, tmp_path):
    # The preview pane renders with the <zero-md> web component (it fetches the
    # markdown from the md route), plus a raw-text toggle that embeds the source.
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.md").write_text("# Big title\n\n| a | b |\n|---|---|\n| 1 | 2 |", encoding="utf-8")
    (out / "Doc.raw.md").write_text("# Big title", encoding="utf-8")
    r = client.get("/c/doc")
    assert r.status_code == 200
    assert "zero-md" in r.text  # renderer component
    assert "/c/doc/md/final" in r.text  # zero-md fetches the checkpoint markdown
    assert "Raw text" in r.text  # the rendered/raw toggle
    assert "| a | b |" in r.text  # raw markdown embedded for the text view
    # Document / Images tabs (gallery moved out of the document's column).
    assert "tab-btn-document" in r.text
    assert "tab-btn-images" in r.text


def test_checkpoint_md_route_returns_markdown(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# Heading\n\ntext", encoding="utf-8")
    r = client.get("/c/doc/md/ingest")
    assert r.status_code == 200
    assert r.text == "# Heading\n\ntext"
    assert "markdown" in r.headers["content-type"]


def test_checkpoint_md_route_unknown_view_404(monkeypatch, tmp_path):
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# Heading", encoding="utf-8")
    assert client.get("/c/doc/md/bogus").status_code == 404


def test_detail_mermaid_security_level_is_not_loose(monkeypatch, tmp_path):
    # Mermaid diagram source is the vision LLM's output on user-supplied images,
    # rendered in the browser. securityLevel must not be 'loose' (which lets a
    # crafted diagram label execute script against the localhost console).
    client, conv = _client(monkeypatch, tmp_path)
    out = conv / "out" / "doc"
    out.mkdir()
    (out / "Doc.md").write_text("# Title", encoding="utf-8")
    (out / "Doc.raw.md").write_text("# Title", encoding="utf-8")
    r = client.get("/c/doc")
    assert r.status_code == 200
    assert "securityLevel: 'loose'" not in r.text
    assert "antiscript" in r.text
