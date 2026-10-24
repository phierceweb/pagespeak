"""Tests for orchestrators._dispatch_finish — the master file and the run record."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pagespeak.models._models import IngestResult
from pagespeak.orchestrators import _dispatch_finish
from pagespeak.services._run_record import RUN_RECORD_FILENAME


def _finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stop_after: str | None) -> Path:
    monkeypatch.setattr(_dispatch_finish, "resolved_flags_from_ctx", lambda _ctx: {})
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()
    _dispatch_finish.write_final_outputs(
        SimpleNamespace(section_count=None),  # type: ignore[arg-type]
        IngestResult(markdown="# Doc\n", source_format="pdf"),
        src=src,
        out=out,
        effective_stem="doc",
        dir_mode=False,
        qti_mode=False,
        preset=None,
        stop_after=stop_after,
        started_at="2026-01-01T00:00:00Z",
        llm_call_records=[],
    )
    return out


def test_writes_the_master_and_the_record(tmp_path: Path, monkeypatch) -> None:
    out = _finish(tmp_path, monkeypatch, stop_after=None)
    assert (out / "doc.md").read_text(encoding="utf-8") == "# Doc\n"
    assert (out / RUN_RECORD_FILENAME).exists()


def test_a_run_stopped_before_vision_leaves_the_master_alone(tmp_path: Path, monkeypatch) -> None:
    """Its markdown is an intermediate checkpoint, not the document."""
    out = _finish(tmp_path, monkeypatch, stop_after="cleanup")
    assert not (out / "doc.md").exists()
    assert (out / RUN_RECORD_FILENAME).exists()


def test_a_failed_record_write_is_logged_not_raised(tmp_path: Path, monkeypatch) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("pagespeak.services._run_record.write_run_record", refuse)
    out = _finish(tmp_path, monkeypatch, stop_after=None)
    assert (out / "doc.md").exists()
