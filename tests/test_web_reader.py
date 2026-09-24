"""Tests for pagespeak.web._reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.web._jobs import ConversionOptions
from pagespeak.web._reader import ReaderChangeRefused, previous_reader, reread_on_reader_change


def _converted(tmp_path: Path, record: dict[str, object] | None) -> tuple[Path, Path]:
    source = tmp_path / "in" / "Doc.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    if record is not None:
        (out / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    return source, out


def test_no_change_without_a_choice_a_read_or_a_pdf(tmp_path: Path) -> None:
    source, out = _converted(tmp_path, {"ingest_flags": {"pdf_backend": "marker"}})
    assert previous_reader(out, source, None) is None
    assert previous_reader(out, source.with_suffix(".docx"), "docling") is None
    assert previous_reader(tmp_path / "never-read", source, "docling") is None


def test_unknown_reader_is_not_a_change(tmp_path: Path) -> None:
    """No record, or one written over the output dir that only knows defaults."""
    source, out = _converted(tmp_path, None)
    assert previous_reader(out, source, "docling") is None
    legacy = {"input": "Doc.raw.md", "resolved_flags": {"pdf_backend": "marker"}}
    source, out = _converted(tmp_path / "legacy", legacy)
    assert previous_reader(out, source, "docling") is None


def test_change_names_the_previous_reader(tmp_path: Path) -> None:
    source, out = _converted(tmp_path, {"ingest_flags": {"pdf_backend": "marker"}})
    assert previous_reader(out, source, "docling") == "marker"
    assert previous_reader(out, source, "marker") is None


def test_only_an_ingest_start_re_reads(tmp_path: Path) -> None:
    source, out = _converted(tmp_path, {"ingest_flags": {"pdf_backend": "marker"}})
    opts = ConversionOptions(pdf_backend="docling")
    assert reread_on_reader_change(opts, out_dir=out, source=source, start="cleanup") == (
        opts,
        False,
    )
    changed, rereads = reread_on_reader_change(opts, out_dir=out, source=source, start="ingest")
    assert (changed.rerun_from, rereads) == ("ingest", True)
    with pytest.raises(ReaderChangeRefused, match="workers"):
        reread_on_reader_change(
            opts.model_copy(update={"workers": 2}), out_dir=out, source=source, start=None
        )
