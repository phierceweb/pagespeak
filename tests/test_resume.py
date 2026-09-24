"""Tests for `orchestrators/_resume.py`.

Covers `_try_resume_from_checkpoint` (raw.md re-use) and
`_try_resume_from_cleaned` (cleaned.md re-use). Both are exercised
end-to-end through `to_markdown()` because the resume helpers are
dispatcher-internal — patching backend / cleanup is the natural way to
assert resume hits or misses.

Vision runs as its own phase after normalize-apply (not inside cleanup),
so vision-cache changes do NOT invalidate the `cleaned.md` resume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pagespeak import IngestResult, to_markdown

# --- _try_resume_from_checkpoint (raw.md) --------------------------------


def test_to_markdown_resumes_from_raw_checkpoint(fake_docx: Path, tmp_path: Path) -> None:
    """A pre-existing raw.md fresher than the source skips the backend
    call entirely. Tests by mocking the backend to fail loudly — if
    resume works, the mock is never invoked."""
    out = tmp_path / "out"
    out.mkdir()
    raw_md = out / f"{fake_docx.stem}.raw.md"
    cached_text = "# resumed from disk\n\nbackend was never called.\n"
    raw_md.write_text(cached_text, encoding="utf-8")
    # Make the checkpoint newer than the source.
    os.utime(raw_md, (raw_md.stat().st_atime, fake_docx.stat().st_mtime + 10))

    with patch(
        "pagespeak.backends._docx.convert_with_markitdown",
        side_effect=AssertionError("backend should not run on resume"),
    ) as mock_backend:
        result = to_markdown(fake_docx, output_dir=out, diagrams=False, cleanup="off")
    mock_backend.assert_not_called()
    assert result.markdown == cached_text


def test_to_markdown_invalidates_resume_when_source_newer(fake_docx: Path, tmp_path: Path) -> None:
    """If the source PDF has been edited since the checkpoint, redo the run."""
    out = tmp_path / "out"
    out.mkdir()
    raw_md = out / f"{fake_docx.stem}.raw.md"
    raw_md.write_text("STALE", encoding="utf-8")
    # Make the checkpoint OLDER than source.
    os.utime(raw_md, (raw_md.stat().st_atime, fake_docx.stat().st_mtime - 10))

    fresh = IngestResult(markdown="# fresh from backend", source_format="docx")
    with patch(
        "pagespeak.backends._docx.convert_with_markitdown", return_value=fresh
    ) as mock_backend:
        result = to_markdown(fake_docx, output_dir=out, diagrams=False, cleanup="off")
    mock_backend.assert_called_once()
    assert result.markdown == "# fresh from backend"
    # And the raw.md is overwritten with the fresh result.
    assert raw_md.read_text(encoding="utf-8") == "# fresh from backend"


def _pdf_raw_checkpoint(tmp_path: Path, recorded: dict[str, object] | None) -> tuple[Path, Path]:
    """A PDF whose raw.md checkpoint is fresh, with `recorded` as the run record's flags."""
    out = tmp_path / "out"
    out.mkdir(parents=True)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    raw_md = out / "doc.raw.md"
    raw_md.write_text("# from the earlier run\n\nbody\n", encoding="utf-8")
    os.utime(raw_md, (raw_md.stat().st_atime, src.stat().st_mtime + 10))
    if recorded is not None:
        (out / ".pagespeak-run.json").write_text(
            json.dumps({"resolved_flags": recorded}), encoding="utf-8"
        )
    return src, out


def _convert_without_backend(src: Path, out: Path, **kwargs: object) -> IngestResult:
    with patch(
        "pagespeak.backends._pdf_dispatch.convert",
        side_effect=AssertionError("backend must not run"),
    ):
        return to_markdown(src, output_dir=out, diagrams=False, cleanup="off", **kwargs)


def test_raw_resume_refuses_a_different_pdf_backend(tmp_path: Path) -> None:
    """Returning the old backend's markdown for a run that asked for another is a
    silent wrong answer; re-ingesting instead could re-describe every image."""
    src, out = _pdf_raw_checkpoint(tmp_path, {"pdf_backend": "marker"})
    with pytest.raises(ValueError, match=r"pdf_backend.*--rerun-from ingest"):
        _convert_without_backend(src, out, pdf_backend="docling")


def test_raw_resume_refuses_a_different_page_range(tmp_path: Path) -> None:
    src, out = _pdf_raw_checkpoint(tmp_path, {"pdf_backend": "marker", "page_range": "0-19"})
    with pytest.raises(ValueError, match="page_range"):
        _convert_without_backend(src, out, page_range="20-39")


def test_raw_resume_accepts_matching_and_unrecorded_flags(tmp_path: Path) -> None:
    """Equal flags resume. A key an older record lacks, or no record at all, is
    not evidence of a mismatch. `heading_hierarchy` only matters under docling."""
    cases = [
        {"pdf_backend": "marker", "page_range": "0-2", "heading_hierarchy": True},
        {"pdf_backend": "marker"},
        None,
    ]
    for i, recorded in enumerate(cases):
        src, out = _pdf_raw_checkpoint(tmp_path / str(i), recorded)
        result = _convert_without_backend(src, out, pdf_backend="marker", page_range=[0, 1, 2])
        assert result.markdown.startswith("# from the earlier run")


def _write_record(out: Path, record: dict[str, object]) -> None:
    (out / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")


def test_raw_resume_refuses_a_page_capped_ingest(tmp_path: Path) -> None:
    """A `--max-pages` trial's raw.md is the first N pages; reusing it for a run
    that asked for the whole document ships a truncated document at exit 0."""
    src, out = _pdf_raw_checkpoint(tmp_path, None)
    _write_record(
        out,
        {
            "resolved_flags": {"pdf_backend": "marker", "page_range": None},
            "ingest_flags": {"pdf_backend": "marker", "page_range": None, "max_pages": 10},
        },
    )
    with pytest.raises(ValueError, match="max_pages: 10"):
        _convert_without_backend(src, out)


def test_chunked_page_capped_ingest_then_convert_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The two-command flow: a chunked `ingest --max-pages` trial, then a plain convert."""
    from pagespeak.models._pipeline import Manifest
    from pagespeak.orchestrators import _ingest

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    def fake_chunk(input_path: Path, **kwargs: object) -> Manifest:
        out_root = Path(str(kwargs["output_dir"]))
        mf = Manifest.load_or_create(out_root, input_path=Path(input_path))
        (out_root / "chunks" / "0-9").mkdir(parents=True)
        (out_root / "chunks" / "0-9" / "raw.md").write_text("# first ten\n", encoding="utf-8")
        mf.mark_chunk_completed("0-9", raw_md="chunks/0-9/raw.md", images=[], pdf_backend="marker")
        return mf

    monkeypatch.setattr(_ingest, "chunk_phase", fake_chunk)
    _ingest.ingest(src, output_dir=out, workers=2, max_pages=10)

    with pytest.raises(ValueError, match="max_pages"):
        _convert_without_backend(src, out)


def test_single_process_page_capped_ingest_then_convert_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    from pagespeak.orchestrators import _ingest

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    monkeypatch.setattr(_ingest, "count_pages", lambda _src: 100)
    first_ten = IngestResult(markdown="# first ten\n", images=[], source_format="pdf")
    with patch("pagespeak.backends._pdf_dispatch.convert", return_value=first_ten):
        _ingest.ingest(src, output_dir=out, workers=1, max_pages=10)

    with pytest.raises(ValueError, match="max_pages: 10"):
        _convert_without_backend(src, out)


def test_ingest_block_outranks_resolved_flags(tmp_path: Path) -> None:
    src, out = _pdf_raw_checkpoint(tmp_path, None)
    _write_record(
        out,
        {
            "resolved_flags": {"pdf_backend": "marker"},
            "ingest_flags": {"pdf_backend": "docling", "heading_hierarchy": True},
        },
    )
    with pytest.raises(ValueError, match="pdf_backend: 'docling'"):
        _convert_without_backend(src, out, pdf_backend="marker")
    result = _convert_without_backend(src, out, pdf_backend="docling", heading_hierarchy=True)
    assert result.markdown.startswith("# from the earlier run")


def _legacy_dir_mode_record(out: Path) -> None:
    """A record written over the output dir before ingest flags were stamped: its
    ingest keys are the defaults of a run that never read the PDF."""
    _write_record(
        out,
        {
            "input": "doc.raw.md",
            "resolved_flags": {"pdf_backend": "marker", "heading_hierarchy": False},
        },
    )


def test_legacy_dir_mode_record_is_not_evidence(tmp_path: Path) -> None:
    src, out = _pdf_raw_checkpoint(tmp_path, None)
    _legacy_dir_mode_record(out)
    result = _convert_without_backend(src, out, pdf_backend="docling", heading_hierarchy=True)
    assert result.markdown.startswith("# from the earlier run")


def test_legacy_dir_mode_record_defers_to_the_chunk_manifest(tmp_path: Path) -> None:
    """Chunked docling runs recorded `pdf_backend=marker` whatever ran; each chunk
    in the manifest names the backend that actually read it."""
    src, out = _pdf_raw_checkpoint(tmp_path, None)
    _legacy_dir_mode_record(out)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "chunks": [
                    {"page_range": "0-49", "status": "completed", "pdf_backend": "docling"},
                    {"page_range": "50-99", "status": "completed", "pdf_backend": "docling"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="pdf_backend: 'docling' → 'marker'"):
        _convert_without_backend(src, out, pdf_backend="marker")
    result = _convert_without_backend(src, out, pdf_backend="docling")
    assert result.markdown.startswith("# from the earlier run")


def test_legacy_dir_mode_record_defers_to_the_outline_marker(tmp_path: Path) -> None:
    """The hierarchy marker is written at ingest and only for docling with
    `--heading-hierarchy` on a bookmarked PDF."""
    src, out = _pdf_raw_checkpoint(tmp_path, None)
    _legacy_dir_mode_record(out)
    (out / ".pagespeak-hierarchy.json").write_text(
        json.dumps({"source": "outline", "depth": 4}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="heading_hierarchy"):
        _convert_without_backend(src, out, pdf_backend="docling", heading_hierarchy=False)
    result = _convert_without_backend(src, out, pdf_backend="docling", heading_hierarchy=True)
    assert result.markdown.startswith("# from the earlier run")


# --- _try_resume_from_cleaned (cleaned.md) -------------------------------


def test_resume_from_cleaned_skips_when_snapshot_valid(tmp_path: Path, monkeypatch) -> None:
    """A second run with no flag changes uses the cached cleaned.md
    and skips Phase 3a (no cleanup_markdown call)."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    # First run — backend + cleanup run.
    to_markdown(src, output_dir=out, diagrams=False)

    cleaned = out / "doc.cleaned.md"
    assert cleaned.exists(), "first run should write cleaned.md"

    # Second run — patch cleanup_markdown to fail loudly if called.
    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(cleanup_mod, "cleanup_markdown", spy)
    to_markdown(src, output_dir=out, diagrams=False)

    assert not cleanup_called, "second run should resume from cleaned.md"


def test_resume_from_cleaned_invalidated_by_flag_change(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    to_markdown(src, output_dir=out, diagrams=False, cleanup="basic")

    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(cleanup_mod, "cleanup_markdown", spy)
    # Flag changed → resume must NOT happen.
    to_markdown(src, output_dir=out, diagrams=False, cleanup="aggressive")
    assert cleanup_called, "flag change must invalidate cleaned snapshot"


def test_resume_from_cleaned_NOT_invalidated_by_newer_vision_cache(tmp_path: Path) -> None:
    """Vision moved out of cleanup phase, so vision-cache
    changes no longer invalidate cleaned.md. A vision-only re-run should
    NOT redo cleanup."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    to_markdown(src, output_dir=out, diagrams=False)

    # Simulate a newer vision-cache file (would have invalidated under
    # the rules; should NOT invalidate now).
    vc = out / ".vision-cache"
    vc.mkdir(exist_ok=True)
    fake = vc / "fake.json"
    fake.write_text("{}", encoding="utf-8")

    cleaned = out / "doc.cleaned.md"
    cl_mtime = cleaned.stat().st_mtime
    os.utime(fake, (cl_mtime + 60, cl_mtime + 60))

    # Patch cleanup to detect re-run.
    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cleanup_mod, "cleanup_markdown", spy)
        to_markdown(src, output_dir=out, diagrams=False)

    assert not cleanup_called, "newer vision-cache mtime must NOT invalidate cleaned.md anymore"


# --- Edge cases ---------------------------------


def test_resume_from_cleaned_invalidated_by_newer_raw(tmp_path: Path, monkeypatch) -> None:
    """If raw.md mtime > cleaned.md mtime (e.g. backend re-ran but
    cleanup hasn't yet), the cleaned snapshot is stale and resume
    must NOT short-circuit Phase 3a."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    # First run writes both raw.md and cleaned.md.
    to_markdown(src, output_dir=out, diagrams=False)
    raw = out / "doc.raw.md"
    cleaned = out / "doc.cleaned.md"
    assert raw.exists() and cleaned.exists()

    # Touch raw.md to a future mtime, AFTER cleaned.md.
    cl_mtime = cleaned.stat().st_mtime
    os.utime(raw, (cl_mtime + 60, cl_mtime + 60))

    # Patch cleanup to detect a re-run.
    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(cleanup_mod, "cleanup_markdown", spy)
    to_markdown(src, output_dir=out, diagrams=False)
    assert cleanup_called, "raw.md newer than cleaned must invalidate resume"


def test_resume_from_cleaned_skips_when_no_run_record(tmp_path: Path, monkeypatch) -> None:
    """cleaned.md present but .pagespeak-run.json missing → resume
    can't validate flag-equivalence and must return None (re-run cleanup)."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    to_markdown(src, output_dir=out, diagrams=False)
    run_record = out / ".pagespeak-run.json"
    assert run_record.exists()
    run_record.unlink()

    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(cleanup_mod, "cleanup_markdown", spy)
    to_markdown(src, output_dir=out, diagrams=False)
    assert cleanup_called, "missing run.json must invalidate resume"


def test_resume_from_cleaned_skips_when_run_record_corrupt(tmp_path: Path, monkeypatch) -> None:
    """Malformed run.json must be handled gracefully (return None), not
    raise. Protects against partial writes / disk corruption."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    to_markdown(src, output_dir=out, diagrams=False)
    run_record = out / ".pagespeak-run.json"
    run_record.write_text("{not valid json", encoding="utf-8")

    cleanup_called: list[int] = []
    import pagespeak.services._cleanup as cleanup_mod

    original = cleanup_mod.cleanup_markdown

    def spy(*a, **kw):
        cleanup_called.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(cleanup_mod, "cleanup_markdown", spy)
    # Must not raise — corrupt run.json should fall through to re-run.
    to_markdown(src, output_dir=out, diagrams=False)
    assert cleanup_called, "corrupt run.json must invalidate resume gracefully"

    # Sanity: the new run wrote a fresh, valid run.json.
    fresh = json.loads(run_record.read_text(encoding="utf-8"))
    assert "resolved_flags" in fresh


# --- cascade preservation ----------------------------------------


def test_rerun_from_ingest_preserves_vision_cache(tmp_path: Path, monkeypatch) -> None:
    """--rerun-from ingest should NOT delete .vision-cache/.
    The phash key self-invalidates, so cascading the cache was
    unnecessary work — preserved across the upstream cascade."""
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    to_markdown(src, output_dir=out, diagrams=False)

    # Manually create a vision-cache file (we used diagrams=False, so it's empty otherwise).
    vc = out / ".vision-cache"
    vc.mkdir(exist_ok=True)
    fake = vc / "abc.json"
    fake.write_text('{"caption": "test"}', encoding="utf-8")

    to_markdown(src, output_dir=out, diagrams=False, rerun_from="ingest")

    assert fake.exists(), "vision-cache must survive --rerun-from ingest"
