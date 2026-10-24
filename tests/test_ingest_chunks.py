"""Tests for orchestrators._ingest_chunks — assembling a chunked ingest's output, and
refusing an unfinished one."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.orchestrators._ingest_chunks import PartialIngestError, assert_ingest_complete


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


def _chunked(out: Path, statuses: list[str]):
    from pagespeak.models._pipeline import ChunkState, Manifest

    chunks = []
    for i, status in enumerate(statuses):
        pages = f"{2 * i}-{2 * i + 1}"
        md = out / "chunks" / pages / "raw.md"
        img = out / "chunks" / pages / "images" / f"p{pages}.png"
        img.parent.mkdir(parents=True)
        md.write_text(f"page {pages}", encoding="utf-8")
        img.write_bytes(b"png")
        rel = [str(p.relative_to(out)) for p in (md, img)]
        chunks.append(ChunkState(pages, status, raw_md=rel[0], images=[rel[1]]))
    return Manifest(output_dir=out, chunks=chunks)


def _assemble(
    tmp_path: Path, monkeypatch, statuses: list[str], *, lose_md: int | None = None
) -> tuple[Path, list[object]]:
    from pagespeak.orchestrators._ingest_chunks import assemble_chunks
    from pagespeak.services import _hierarchy_trust

    stamped: list[object] = []
    monkeypatch.setattr(
        _hierarchy_trust, "record_hierarchy_source", lambda *_a, **k: stamped.append(("source", k))
    )
    monkeypatch.setattr(
        _hierarchy_trust, "record_structured", lambda *_a, **k: stamped.append(("structured", k))
    )
    out = tmp_path / "out"
    mf = _chunked(out, statuses)
    if lose_md is not None:
        (out / str(mf.chunks[lose_md].raw_md)).unlink()
    raw = out / "doc.raw.md"
    assemble_chunks(
        mf,
        tmp_path / "doc.pdf",
        out,
        raw_md_path=raw,
        pdf_backend="docling",
        heading_hierarchy=True,
    )
    return raw, stamped


def test_assemble_joins_the_chunks_flattens_images_and_stamps_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    raw, stamped = _assemble(tmp_path, monkeypatch, ["completed", "completed"])
    assert raw.read_text(encoding="utf-8") == "page 0-1\n\npage 2-3"
    assert sorted(p.name for p in (raw.parent / "images").iterdir()) == ["p0-1.png", "p2-3.png"]
    assert stamped == [
        ("source", {"pdf_backend": "docling", "heading_hierarchy": True}),
        ("structured", {"authoritative": False}),
    ]


def test_assemble_keeps_the_completed_chunks_and_names_the_failed(
    tmp_path: Path, monkeypatch
) -> None:
    with pytest.raises(PartialIngestError) as excinfo:
        _assemble(tmp_path, monkeypatch, ["completed", "failed"])
    assert excinfo.value.failed_page_ranges == ["2-3"]
    assert (tmp_path / "out" / "doc.raw.md").read_text(encoding="utf-8") == "page 0-1"


@pytest.mark.parametrize(
    ("statuses", "lose_md"), [(["completed", "in_progress"], None), (["completed", "completed"], 1)]
)
def test_assemble_counts_an_unfinished_or_emptied_chunk_as_missing_pages(
    tmp_path: Path, monkeypatch, statuses: list[str], lose_md: int | None
) -> None:
    with pytest.raises(PartialIngestError) as excinfo:
        _assemble(tmp_path, monkeypatch, statuses, lose_md=lose_md)
    assert excinfo.value.failed_page_ranges == ["2-3"]


def test_assemble_with_no_completed_chunk_raises(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="no completed chunks"):
        _assemble(tmp_path, monkeypatch, ["failed"])
