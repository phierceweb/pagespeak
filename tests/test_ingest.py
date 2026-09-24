"""Tests for orchestrators._ingest."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.orchestrators._ingest import (
    PartialIngestError,
    assert_ingest_complete,
    ingest,
)


def _write_manifest(out: Path, chunks: list[tuple[str, str]]) -> None:
    import json

    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(
            {"version": 3, "chunks": [{"page_range": pr, "status": st} for pr, st in chunks]}
        ),
        encoding="utf-8",
    )


def test_assert_ingest_complete_refuses_incomplete_chunks(tmp_path, caplog):
    """Nothing downstream reads chunk status, so this is the only stop between a
    failed chunk and a document silently missing those pages."""
    out = tmp_path / "out"
    _write_manifest(out, [("0-49", "completed"), ("50-99", "failed")])
    (out / "doc.raw.md").write_text("half\n", encoding="utf-8")

    with pytest.raises(PartialIngestError) as excinfo:
        assert_ingest_complete(out)
    assert excinfo.value.failed_page_ranges == ["50-99"]

    # A killed run leaves `in_progress`, which is equally incomplete.
    _write_manifest(out, [("0-49", "completed"), ("50-99", "in_progress")])
    with pytest.raises(PartialIngestError):
        assert_ingest_complete(out)

    # Opt-in downgrades to a warning.
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert_ingest_complete(out, allow_partial=True)
    assert "ingest_incomplete_accepted" in caplog.text


def test_assert_ingest_complete_passes_when_nothing_to_flag(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert_ingest_complete(out)  # no manifest → not a chunked run
    assert_ingest_complete(None)  # library call with no output dir

    _write_manifest(out, [("0-49", "completed"), ("50-99", "completed")])
    assert_ingest_complete(out)


def test_ingest_single_process_writes_raw_md_and_images(tmp_path, monkeypatch):
    """workers=1 → backend in-process, output is raw.md + images/."""
    from pagespeak.backends import _pdf_dispatch
    from pagespeak.models._models import IngestResult

    def fake_convert(
        backend_name,
        src,
        *,
        output_dir,
        force_ocr,
        device,
        page_range,
        heading_hierarchy=False,
        backend_kwargs=None,
    ):
        img = output_dir / "images" / "fig1.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        return IngestResult(
            markdown="# Doc\n\n![](images/fig1.png)\n",
            images=[img],
            diagrams=[],
            source_format="pdf",
        )

    monkeypatch.setattr(_pdf_dispatch, "convert", fake_convert)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    result_path = ingest(src, output_dir=out, workers=1, pdf_backend="marker")
    assert result_path == out / "doc.raw.md"
    assert result_path.exists()
    raw = result_path.read_text(encoding="utf-8")
    assert "fig1.png" in raw

    # No manifest in single-process mode.
    assert not (out / "manifest.json").exists()
    # No chunks/ in single-process mode.
    assert not (out / "chunks").exists()
    # Images at the flat location.
    assert (out / "images" / "fig1.png").exists()


def test_ingest_records_the_flags_it_ran(tmp_path, monkeypatch):
    """The two-command flow (`ingest`, then `convert <out_dir>`) inherits from this."""
    from pagespeak.backends import _pdf_dispatch
    from pagespeak.models._models import IngestResult
    from pagespeak.services._run_record import read_run_record

    monkeypatch.setattr(
        _pdf_dispatch,
        "convert",
        lambda *a, **k: IngestResult(markdown="# Doc\n", images=[], source_format="pdf"),
    )
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    ingest(src, output_dir=out, workers=1, pdf_backend="docling", heading_hierarchy=True)

    record = read_run_record(out)
    assert record is not None
    flags = record["resolved_flags"]
    assert flags["pdf_backend"] == "docling"
    assert flags["heading_hierarchy"] is True
    assert flags["force_ocr"] is False
    assert record["source_identity"]["source_id"] == "doc"


def test_ingest_single_process_non_pdf_uses_markitdown(tmp_path, monkeypatch):
    """workers=1 with a .docx routes to the markitdown backend."""
    from pagespeak.backends import _docx
    from pagespeak.models._models import IngestResult

    def fake_markitdown(src, *, output_dir):
        img = output_dir / "images" / "img.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        return IngestResult(
            markdown="# Doc\n",
            images=[img],
            diagrams=[],
            source_format="docx",
        )

    monkeypatch.setattr(_docx, "convert_with_markitdown", fake_markitdown)

    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK\x03\x04")  # zip header
    out = tmp_path / "out"
    result_path = ingest(src, output_dir=out, workers=1)
    assert result_path == out / "doc.raw.md"
    assert (out / "doc.raw.md").exists()


def test_ingest_single_process_markdown_passthrough(tmp_path):
    """workers=1 with a .md reads the file verbatim into raw.md (no conversion)."""
    src = tmp_path / "doc.md"
    body = "# Already markdown\n\nBody with a [link](https://example.com).\n"
    src.write_text(body, encoding="utf-8")
    out = tmp_path / "out"

    result_path = ingest(src, output_dir=out, workers=1)

    assert result_path == out / "doc.raw.md"
    assert (out / "doc.raw.md").read_text(encoding="utf-8") == body


def test_ingest_workers_must_be_positive(tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    with pytest.raises(ValueError, match="workers must be >= 1"):
        ingest(src, output_dir=tmp_path / "out", workers=0)


def test_ingest_chunked_rejects_page_range(tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    with pytest.raises(ValueError, match="page_range is not supported on the chunked path"):
        ingest(src, output_dir=tmp_path / "out", workers=2, page_range="0-10")


def _capture_backends(monkeypatch) -> list[object]:
    """Stub the PDF and MarkItDown backends; returns where the PDF page ranges land."""
    from pagespeak.backends import _docx, _pdf_dispatch
    from pagespeak.models._models import IngestResult

    ranges: list[object] = []

    def fake_pdf(backend_name, src, *, page_range=None, **_kwargs):
        ranges.append(page_range)
        return IngestResult(markdown="# Doc\n", images=[], source_format="pdf")

    monkeypatch.setattr(_pdf_dispatch, "convert", fake_pdf)
    monkeypatch.setattr(
        _docx,
        "convert_with_markitdown",
        lambda *a, **k: IngestResult(markdown="# Doc\n", images=[], source_format="docx"),
    )
    return ranges


def test_ingest_single_process_honors_max_pages(tmp_path, monkeypatch):
    """`--max-pages` without `--workers` converted the whole document."""
    from pagespeak.orchestrators import _ingest
    from pagespeak.services._run_record import read_run_record

    ranges = _capture_backends(monkeypatch)
    monkeypatch.setattr(_ingest, "count_pages", lambda _src: 100)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    ingest(src, output_dir=out, workers=1, max_pages=10)

    assert ranges == ["0-9"]
    record = read_run_record(out)
    assert record is not None
    assert record["ingest_flags"]["max_pages"] == 10
    # The cap is not a page range: a later convert must not inherit it as one.
    assert record["ingest_flags"]["page_range"] is None


def test_ingest_max_pages_past_the_end_reads_every_page(tmp_path, monkeypatch):
    from pagespeak.orchestrators import _ingest

    ranges = _capture_backends(monkeypatch)
    monkeypatch.setattr(_ingest, "count_pages", lambda _src: 6)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")

    ingest(src, output_dir=tmp_path / "out", workers=1, max_pages=10)

    assert ranges == ["0-5"]


@pytest.mark.parametrize(
    ("name", "kwargs", "message"),
    [
        ("doc.docx", {}, "PDF"),
        ("doc.pdf", {"pdf_backend": "tophat"}, "tophat"),
        ("doc.pdf", {"page_range": "0-3"}, "page_range"),
        ("doc.pdf", {"max_pages": 0}, ">= 1"),
    ],
)
def test_ingest_refuses_a_max_pages_it_cannot_apply(tmp_path, monkeypatch, name, kwargs, message):
    """Converting the whole document anyway is what made the flag a silent no-op."""
    _capture_backends(monkeypatch)
    src = tmp_path / name
    src.write_bytes(b"x")
    with pytest.raises(ValueError, match=message):
        ingest(src, output_dir=tmp_path / "out", workers=1, **{"max_pages": 5, **kwargs})


def test_ingest_chunked_writes_unified_raw_md(tmp_path, monkeypatch):
    """workers=2 → chunked path → unified raw.md + flat images/."""
    from pagespeak.models._pipeline import ChunkState, Manifest
    from pagespeak.orchestrators import _ingest

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    def fake_chunk(input_path, **kwargs):
        # Simulate two completed chunks already on disk.
        out_root = Path(kwargs["output_dir"])
        mf = Manifest.load_or_create(out_root, input_path=Path(input_path))
        for page_range, _lo in [("0000-0049", 0), ("0050-0099", 50)]:
            d = out_root / "chunks" / page_range / "images"
            d.mkdir(parents=True, exist_ok=True)
            img_name = f"{page_range}-_page_1_Figure_1.png"
            (d / img_name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            raw_md = out_root / "chunks" / page_range / "raw.md"
            raw_md.write_text(
                f"# Chunk {page_range}\n\n![](images/{img_name})\n",
                encoding="utf-8",
            )
            mf.add_or_update_chunk(
                ChunkState(
                    page_range=page_range,
                    status="completed",
                    raw_md=str(raw_md.relative_to(out_root)),
                    images=[str((d / img_name).relative_to(out_root))],
                    pdf_backend="marker",
                )
            )
        return mf

    monkeypatch.setattr(_ingest, "chunk_phase", fake_chunk)

    result_path = ingest(src, output_dir=out, workers=2, pdf_backend="marker")

    assert result_path == out / "doc.raw.md"
    raw = result_path.read_text(encoding="utf-8")
    # Both chunks present:
    assert "Chunk 0000-0049" in raw
    assert "Chunk 0050-0099" in raw
    # Flat images dir has both:
    assert (out / "images" / "0000-0049-_page_1_Figure_1.png").exists()
    assert (out / "images" / "0050-0099-_page_1_Figure_1.png").exists()
    # Manifest preserved:
    assert (out / "manifest.json").exists()


def test_ingest_chunked_flattens_only_the_current_plan(tmp_path, monkeypatch):
    """A shelved chunk's images stay under chunks/; a flat copy left in images/
    would be described by vision and counted by the console's cost gate."""
    from pagespeak.models._pipeline import Manifest
    from pagespeak.orchestrators import _ingest

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"
    (out / "images").mkdir(parents=True)
    (out / "images" / "0-19-fig.png").write_bytes(b"flat copy from the trial run")

    def fake_chunk(input_path, **kwargs):
        out_root = Path(kwargs["output_dir"])
        mf = Manifest.load_or_create(out_root, input_path=Path(input_path))
        for page_range in ("0-19", "0-49"):
            d = out_root / "chunks" / page_range / "images"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{page_range}-fig.png").write_bytes(b"png")
            (out_root / "chunks" / page_range / "raw.md").write_text(
                f"# {page_range}\n", encoding="utf-8"
            )
            mf.mark_chunk_completed(
                page_range,
                raw_md=f"chunks/{page_range}/raw.md",
                images=[f"chunks/{page_range}/images/{page_range}-fig.png"],
                pdf_backend="marker",
            )
        mf.set_plan({"0-49"})
        return mf

    monkeypatch.setattr(_ingest, "chunk_phase", fake_chunk)
    ingest(src, output_dir=out, workers=2)

    assert sorted(p.name for p in (out / "images").iterdir()) == ["0-49-fig.png"]
    assert (out / "chunks" / "0-19" / "images" / "0-19-fig.png").exists()
    assert (out / "doc.raw.md").read_text(encoding="utf-8") == "# 0-49\n"


def test_ingest_chunked_raises_partial_error_on_some_failed_chunks(tmp_path, monkeypatch):
    """When some chunks succeed and some fail, ingest writes the
    partial raw.md and raises PartialIngestError. The exception carries
    enough state for callers / CLI to report cleanly and for users to
    retry the failed chunks only."""
    from pagespeak.models._pipeline import ChunkState, Manifest
    from pagespeak.orchestrators import _ingest
    from pagespeak.orchestrators._ingest import PartialIngestError

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    def fake_chunk(input_path, **kwargs):
        # Simulate one completed chunk + three failed chunks.
        out_root = Path(kwargs["output_dir"])
        mf = Manifest.load_or_create(out_root, input_path=Path(input_path))
        page_range = "0050-0099"
        d = out_root / "chunks" / page_range / "images"
        d.mkdir(parents=True, exist_ok=True)
        raw_md = out_root / "chunks" / page_range / "raw.md"
        raw_md.write_text(f"# Chunk {page_range}\n", encoding="utf-8")
        mf.add_or_update_chunk(
            ChunkState(
                page_range=page_range,
                status="completed",
                raw_md=str(raw_md.relative_to(out_root)),
                images=[],
                pdf_backend="marker",
            )
        )
        for failed_range in ("0000-0049", "0100-0149", "0150-0199"):
            mf.add_or_update_chunk(
                ChunkState(
                    page_range=failed_range,
                    status="failed",
                    error="fake torch error",
                    pdf_backend="marker",
                )
            )
        return mf

    monkeypatch.setattr(_ingest, "chunk_phase", fake_chunk)

    import pytest

    with pytest.raises(PartialIngestError) as excinfo:
        ingest(src, output_dir=out, workers=2, pdf_backend="marker")

    err = excinfo.value
    assert err.raw_md_path == out / "doc.raw.md"
    assert err.total_chunks == 4
    assert sorted(err.failed_page_ranges) == ["0000-0049", "0100-0149", "0150-0199"]
    assert err.output_dir == out
    # Partial raw.md was still written (resume value).
    assert err.raw_md_path.exists()
    assert "Chunk 0050-0099" in err.raw_md_path.read_text(encoding="utf-8")
    # Error message is informative.
    msg = str(err)
    assert "3 of 4 chunks failed" in msg
    assert "manifest.json" in msg


def test_ingest_chunked_no_completed_chunks_raises_runtime_error(tmp_path, monkeypatch):
    """Existing behavior preserved: when ZERO chunks complete, raise
    plain RuntimeError (not PartialIngestError) — no raw.md to resume
    from."""
    from pagespeak.models._pipeline import ChunkState, Manifest
    from pagespeak.orchestrators import _ingest

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    def fake_chunk(input_path, **kwargs):
        out_root = Path(kwargs["output_dir"])
        mf = Manifest.load_or_create(out_root, input_path=Path(input_path))
        for page_range in ("0000-0049", "0050-0099"):
            mf.add_or_update_chunk(
                ChunkState(
                    page_range=page_range,
                    status="failed",
                    error="x",
                    pdf_backend="marker",
                )
            )
        return mf

    monkeypatch.setattr(_ingest, "chunk_phase", fake_chunk)

    import pytest

    with pytest.raises(RuntimeError, match="no completed chunks"):
        ingest(src, output_dir=out, workers=2, pdf_backend="marker")


def test_ingest_docx_backend_threads_through(make_docx, tmp_path) -> None:
    from unittest.mock import patch

    from pagespeak.models._models import IngestResult
    from pagespeak.orchestrators._ingest import ingest

    src = make_docx(document_xml="<w:p><w:r><w:t>Q</w:t></w:r></w:p>")
    d = tmp_path / "q.docx"
    d.write_bytes(src.read_bytes())
    with patch(
        "pagespeak.backends._docx_dispatch.convert",
        return_value=IngestResult(markdown="Q", source_format="docx"),
    ) as conv:
        ingest(d, output_dir=tmp_path / "o", docx_backend="python-docx")
    assert conv.call_args.args[0] == "python-docx"


def test_ingest_rejects_legacy_doc_format(tmp_path):
    """Legacy binary Office (.doc/.ppt/.xls) is deliberately unsupported —
    MarkItDown doesn't reliably handle the binary format. Ingest must raise a
    clear 'Unsupported format' error (pointing at the .docx workaround), not
    silently attempt a lossy conversion."""
    src = tmp_path / "legacy.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0")  # OLE2 (legacy Office) magic
    with pytest.raises(ValueError, match="Unsupported format"):
        ingest(src, output_dir=tmp_path / "out", workers=1)
