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
