from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak import IngestResult
from pagespeak.models._pipeline import Manifest
from pagespeak.orchestrators._chunk import (
    CHUNK_PAGES_ENV_VAR,
    DEFAULT_CHUNK_PAGES,
    DEFAULT_WORKERS,
    WORKERS_ENV_VAR,
    ChunkPlan,
    chunk,
    plan_chunks,
    resolve_chunk_pages,
    resolve_cli_workers,
    resolve_workers,
)

# --- resolve_workers ---


def test_resolve_workers_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "10")
    assert resolve_workers(2) == 2


def test_resolve_workers_env_used_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "6")
    assert resolve_workers(None) == 6


def test_resolve_workers_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    assert resolve_workers(None) == DEFAULT_WORKERS


def test_resolve_workers_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        resolve_workers(0)


def test_resolve_workers_bad_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed env warns (via `pf_core.utils.env.resolve_int`) and falls
    back to default, so an operator typo doesn't crash the pipeline."""
    monkeypatch.setenv(WORKERS_ENV_VAR, "abc")
    with caplog.at_level("WARNING"):
        assert resolve_workers(None) == DEFAULT_WORKERS
    assert any("env_var_malformed" in r.message for r in caplog.records)


# --- resolve_chunk_pages ---


def test_resolve_chunk_pages_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "200")
    assert resolve_chunk_pages(100) == 100


def test_resolve_chunk_pages_env_used_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "75")
    assert resolve_chunk_pages(None) == 75


def test_resolve_chunk_pages_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CHUNK_PAGES_ENV_VAR, raising=False)
    assert resolve_chunk_pages(None) == DEFAULT_CHUNK_PAGES


def test_resolve_chunk_pages_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        resolve_chunk_pages(0)


def test_resolve_chunk_pages_bad_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed env warns (via pf_core.resolve_int) and falls back to
    default. We only assert the fall-back value here so this test doesn't
    couple to pf-core's log format."""
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "abc")
    assert resolve_chunk_pages(None) == DEFAULT_CHUNK_PAGES


# --- plan_chunks ---


def test_plan_chunks_even_split() -> None:
    plans = plan_chunks(100, 50)
    assert plans == [
        ChunkPlan(page_range="0-49", start=0, end=49),
        ChunkPlan(page_range="50-99", start=50, end=99),
    ]


def test_plan_chunks_remainder_in_last() -> None:
    plans = plan_chunks(105, 50)
    assert [p.page_range for p in plans] == ["0-49", "50-99", "100-104"]


def test_plan_chunks_single_chunk_when_smaller_than_size() -> None:
    plans = plan_chunks(20, 50)
    assert plans == [ChunkPlan(page_range="0-19", start=0, end=19)]


def test_plan_chunks_rejects_zero_pages() -> None:
    with pytest.raises(ValueError):
        plan_chunks(0, 50)


def test_plan_chunks_rejects_zero_chunk_size() -> None:
    with pytest.raises(ValueError):
        plan_chunks(100, 0)


# --- chunk() public API (mocking the worker) ---


def _stub_chunk_result_factory(out: Path):
    """Build a stub _ChunkResult creator that simulates a successful chunk
    by writing a raw.md and (optionally) an image into the chunk dir."""
    from pagespeak.orchestrators._chunk import _ChunkResult

    def stub(*, input_path: str, output_dir: str, page_range: str, **_kwargs):
        chunk_dir = Path(output_dir) / "chunks" / page_range
        chunk_dir.mkdir(parents=True, exist_ok=True)
        raw_md = chunk_dir / "raw.md"
        raw_md.write_text(f"# chunk {page_range}\n", encoding="utf-8")
        img_dir = chunk_dir / "images"
        img_dir.mkdir(exist_ok=True)
        img = img_dir / f"_page_{page_range.split('-')[0]}_Figure_1.png"
        img.write_bytes(b"\x89PNG\r\n")
        return _ChunkResult(
            page_range=page_range,
            raw_md_rel=str(raw_md.relative_to(Path(output_dir))),
            image_rels=[str(img.relative_to(Path(output_dir)))],
            error=None,
        )

    return stub


class _InlineFuture:
    """Synchronous future stand-in: result computed eagerly so as_completed
    sees something it can yield without a real pool."""

    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class _InlineExecutor:
    """ProcessPoolExecutor stand-in for tests. Calls the function inline so
    we don't fork (Marker import would crash mocks)."""

    def __init__(self, *args, **kwargs):
        self._submitted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, **kwargs):
        result = fn(**kwargs)
        fut = _InlineFuture(result)
        self._submitted.append(fut)
        return fut


def _patch_inline(monkeypatch: pytest.MonkeyPatch, stub) -> None:
    monkeypatch.setattr("pagespeak.orchestrators._chunk.ProcessPoolExecutor", _InlineExecutor)
    monkeypatch.setattr(
        "pagespeak.orchestrators._chunk.as_completed", lambda futures: list(futures)
    )
    monkeypatch.setattr("pagespeak.orchestrators._chunk._run_one_chunk", stub)


def test_chunk_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        chunk(tmp_path / "nope.pdf", output_dir=tmp_path / "out")


def test_chunk_rejects_non_pdf(tmp_path: Path) -> None:
    f = tmp_path / "doc.docx"
    f.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match="only handles PDFs"):
        chunk(f, output_dir=tmp_path / "out")


def test_chunk_writes_manifest_and_chunk_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    stub = _stub_chunk_result_factory(out)
    _patch_inline(monkeypatch, stub)
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    mf = chunk(src, output_dir=out, chunk_pages=50, workers=1)

    assert (out / "manifest.json").exists()
    assert (out / "chunks" / "0-49" / "raw.md").exists()
    assert (out / "chunks" / "50-99" / "raw.md").exists()
    assert mf.completed_chunk_ranges() == {"0-49", "50-99"}


def test_chunk_resume_skips_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    # Pre-mark 0-49 as completed.
    mf = Manifest.load_or_create(out, input_path=src)
    mf.mark_chunk_completed("0-49", raw_md="chunks/0-49/raw.md", images=[])

    calls = []

    def stub(**kwargs):
        from pagespeak.orchestrators._chunk import _ChunkResult

        calls.append(kwargs["page_range"])
        return _ChunkResult(
            page_range=kwargs["page_range"],
            raw_md_rel=f"chunks/{kwargs['page_range']}/raw.md",
            image_rels=[],
            error=None,
        )

    _patch_inline(monkeypatch, stub)
    chunk(src, output_dir=out, chunk_pages=50, workers=1)

    assert calls == ["50-99"]


def test_chunk_keeps_other_plans_out_of_raw_md_without_losing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A `--max-pages` trial then the full run: the trial's `0-19` chunk overlaps
    the new `0-49`, and concatenating both duplicated those pages in raw.md. A
    trial after the full run must not cost the full run's chunks either."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    rendered: list[str] = []
    make = _stub_chunk_result_factory(out)

    def stub(**kwargs: object):
        rendered.append(str(kwargs["page_range"]))
        return make(**kwargs)

    _patch_inline(monkeypatch, stub)
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    chunk(src, output_dir=out, chunk_pages=50, workers=1, max_pages=20)
    with caplog.at_level("WARNING"):
        mf = chunk(src, output_dir=out, chunk_pages=50, workers=1)
    assert mf.completed_chunk_ranges() == {"0-49", "50-99"}
    assert [p.parent.name for p in mf.all_chunk_raw_md()] == ["0-49", "50-99"]
    assert "chunk_plan_changed" in caplog.text
    assert Manifest.load_or_create(out).completed_chunk_ranges() == {"0-49", "50-99"}

    chunk(src, output_dir=out, chunk_pages=50, workers=1, max_pages=20)
    mf = chunk(src, output_dir=out, chunk_pages=50, workers=1)
    assert rendered == ["0-19", "0-49", "50-99"]
    assert [p.parent.name for p in mf.all_chunk_raw_md()] == ["0-49", "50-99"]


def test_chunk_refuses_resume_with_other_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reusing chunks read with other settings keeps their output while the run
    record claims the new settings."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    _patch_inline(monkeypatch, _stub_chunk_result_factory(out))
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)
    chunk(src, output_dir=out, chunk_pages=50, workers=1, pdf_backend="docling")

    with pytest.raises(ValueError, match="heading_hierarchy: False → True"):
        chunk(
            src,
            output_dir=out,
            chunk_pages=50,
            workers=1,
            pdf_backend="docling",
            heading_hierarchy=True,
        )
    with pytest.raises(ValueError, match="force_ocr"):
        chunk(src, output_dir=out, chunk_pages=50, workers=1, pdf_backend="docling", force_ocr=True)
    with pytest.raises(ValueError, match="pdf_backend_kwargs"):
        chunk(
            src,
            output_dir=out,
            chunk_pages=50,
            workers=1,
            pdf_backend="docling",
            pdf_backend_kwargs={"do_formula_enrichment": True},
        )
    chunk(src, output_dir=out, chunk_pages=50, workers=1, pdf_backend="docling")


def test_chunk_settings_compare_only_what_the_backend_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker ignores `heading_hierarchy`; chunks from before settings were
    recorded are not evidence of a mismatch."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    _patch_inline(monkeypatch, _stub_chunk_result_factory(out))
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)
    chunk(src, output_dir=out, chunk_pages=50, workers=1)
    chunk(src, output_dir=out, chunk_pages=50, workers=1, heading_hierarchy=True)

    legacy = tmp_path / "legacy"
    mf = Manifest.load_or_create(legacy, input_path=src)
    for page_range in ("0-49", "50-99"):
        mf.mark_chunk_completed(
            page_range, raw_md=f"chunks/{page_range}/raw.md", images=[], pdf_backend="marker"
        )
    chunk(src, output_dir=legacy, chunk_pages=50, workers=1, force_ocr=True)


def test_chunk_records_settings_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    _patch_inline(monkeypatch, _stub_chunk_result_factory(out))
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 50)

    mf = chunk(
        src,
        output_dir=out,
        chunk_pages=50,
        workers=1,
        pdf_backend="docling",
        heading_hierarchy=True,
        pdf_backend_kwargs={"do_formula_enrichment": True},
    )

    assert mf.chunks[0].settings == {
        "force_ocr": False,
        "heading_hierarchy": True,
        "pdf_backend_kwargs": {"do_formula_enrichment": True},
    }


def test_chunk_force_reruns_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    mf = Manifest.load_or_create(out, input_path=src)
    mf.mark_chunk_completed("0-49", raw_md="chunks/0-49/raw.md", images=[])

    calls = []

    def stub(**kwargs):
        from pagespeak.orchestrators._chunk import _ChunkResult

        calls.append(kwargs["page_range"])
        return _ChunkResult(
            page_range=kwargs["page_range"],
            raw_md_rel=f"chunks/{kwargs['page_range']}/raw.md",
            image_rels=[],
            error=None,
        )

    _patch_inline(monkeypatch, stub)
    chunk(src, output_dir=out, chunk_pages=50, workers=1, force=True)

    assert sorted(calls) == ["0-49", "50-99"]


def test_chunk_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 50)

    def stub(**kwargs):
        from pagespeak.orchestrators._chunk import _ChunkResult

        return _ChunkResult(
            page_range=kwargs["page_range"],
            raw_md_rel=None,
            image_rels=[],
            error="surya crash\n",
        )

    _patch_inline(monkeypatch, stub)
    mf = chunk(src, output_dir=out, chunk_pages=50, workers=1)

    assert mf.chunks[0].status == "failed"
    assert "surya crash" in (mf.chunks[0].error or "")


def test_chunk_no_op_when_all_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 50)

    mf = Manifest.load_or_create(out, input_path=src)
    mf.mark_chunk_completed("0-49", raw_md="chunks/0-49/raw.md", images=[])

    # If chunk() tried to call the worker we'd see ImportError on real Marker.
    # Just patch it out defensively to nothing.
    monkeypatch.setattr(
        "pagespeak.orchestrators._chunk._run_one_chunk",
        lambda **kw: (_ for _ in ()).throw(AssertionError("worker should not run")),
    )

    mf2 = chunk(src, output_dir=out, chunk_pages=50, workers=1)
    assert mf2.completed_chunk_ranges() == {"0-49"}


def test_chunk_default_uses_default_chunk_pages() -> None:
    # Sanity: the constant exists and is non-trivial.
    assert DEFAULT_CHUNK_PAGES > 0


def test_chunk_refuses_resume_across_mismatched_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A previous run completed chunks with marker; trying to resume with
    docling must error so the manifest doesn't end up mixing two
    backends' output (anchor maps + image conventions diverge)."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    # Pre-populate manifest with a marker-completed chunk.
    mf = Manifest.load_or_create(out, input_path=src)
    mf.mark_chunk_completed("0-49", raw_md="chunks/0-49/raw.md", images=[], pdf_backend="marker")

    with pytest.raises(ValueError, match="cannot resume with pdf_backend='docling'"):
        chunk(src, output_dir=out, chunk_pages=50, workers=1, pdf_backend="docling")


def test_chunk_force_overrides_backend_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` is the explicit escape hatch — the user has decided
    they want to re-run from scratch with a different backend."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 50)

    mf = Manifest.load_or_create(out, input_path=src)
    mf.mark_chunk_completed("0-49", raw_md="chunks/0-49/raw.md", images=[], pdf_backend="marker")

    def stub(**kwargs):
        from pagespeak.orchestrators._chunk import _ChunkResult

        return _ChunkResult(
            page_range=kwargs["page_range"],
            raw_md_rel=f"chunks/{kwargs['page_range']}/raw.md",
            image_rels=[],
            error=None,
        )

    _patch_inline(monkeypatch, stub)
    # Force re-run with docling — should not raise.
    mf2 = chunk(
        src,
        output_dir=out,
        chunk_pages=50,
        workers=1,
        pdf_backend="docling",
        force=True,
    )
    # And the new chunk records its backend.
    assert any(c.pdf_backend == "docling" for c in mf2.chunks if c.status == "completed")


def test_chunk_records_pdf_backend_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manifest must remember which backend produced each chunk so resume
    can refuse mismatched re-runs."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    stub = _stub_chunk_result_factory(out)
    _patch_inline(monkeypatch, stub)
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda p: 100)

    mf = chunk(src, output_dir=out, chunk_pages=50, workers=1, pdf_backend="docling")

    completed = [c for c in mf.chunks if c.status == "completed"]
    assert completed
    for c in completed:
        assert c.pdf_backend == "docling"


def test_run_one_chunk_serializes_error(tmp_path: Path) -> None:
    """Worker should never raise — errors are returned in the dataclass."""
    from pagespeak.orchestrators._chunk import _run_one_chunk

    out = tmp_path / "out"
    out.mkdir()
    # Pass a nonexistent file so convert_pdf raises inside the worker.
    result = _run_one_chunk(
        input_path=str(tmp_path / "missing.pdf"),
        output_dir=str(out),
        page_range="0-9",
        device=None,
        force_ocr=False,
    )
    assert result.error is not None
    assert result.raw_md_rel is None


def test_run_one_chunk_writes_raw_md_and_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker happy path: convert_pdf returns markdown + images, worker
    persists them and reports relative paths."""
    from pagespeak.orchestrators._chunk import _run_one_chunk

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()

    def fake_convert(
        path,
        *,
        output_dir,
        force_ocr,
        device,
        page_range,
        heading_hierarchy=False,
        backend_kwargs=None,
    ):
        # Simulate Marker writing an image as it does in real life.
        img_dir = output_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        img = img_dir / "_page_0_Figure_1.png"
        img.write_bytes(b"\x89PNG\r\n")
        return IngestResult(markdown="# fake chunk\n", images=[img], source_format="pdf")

    monkeypatch.setattr("pagespeak.backends._pdf.convert_pdf", fake_convert)

    result = _run_one_chunk(
        input_path=str(src),
        output_dir=str(out),
        page_range="0-9",
        device=None,
        force_ocr=False,
    )
    assert result.error is None
    assert result.raw_md_rel == "chunks/0-9/raw.md"
    assert result.image_rels == ["chunks/0-9/images/_page_0_Figure_1.png"]
    assert (out / result.raw_md_rel).read_text() == "# fake chunk\n"


def test_run_one_chunk_prefixes_image_basenames_and_absolutizes_anchors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker output: image filenames under chunks/50-99/images/ are
    prefixed; markdown refs match; page anchors are absolute."""
    from pagespeak.orchestrators import _chunk

    def fake_convert(
        name: str,
        src: Path,
        *,
        output_dir: Path,
        force_ocr: bool,
        device: object,
        page_range: str,
        heading_hierarchy: bool = False,
        backend_kwargs: object = None,
    ) -> IngestResult:
        # Simulate Marker emitting chunk-local page 3 with one image and one anchor.
        img_dir = output_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        img = img_dir / "_page_3_Figure_1.jpeg"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        md = (
            '<span id="page-3-2"></span>\n\n'
            "# Heading\n\n"
            "![](images/_page_3_Figure_1.jpeg)\n\n"
            "[See section](#page-3-2)\n"
        )
        return IngestResult(markdown=md, images=[img], diagrams=[], source_format="pdf")

    monkeypatch.setattr("pagespeak.backends._pdf_dispatch.convert", fake_convert)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"
    out.mkdir()

    # page_range "50-99" → page_offset = 50
    result = _chunk._run_one_chunk(
        input_path=str(src),
        output_dir=str(out),
        page_range="50-99",
        device=None,
        force_ocr=False,
        pdf_backend="marker",
        backend_kwargs=None,
    )

    assert result.error is None, f"unexpected error: {result.error}"
    # Image renamed on disk:
    renamed = out / "chunks" / "50-99" / "images" / "50-99-_page_3_Figure_1.jpeg"
    assert renamed.exists(), f"expected renamed image at {renamed}"
    # Original basename gone:
    assert not (out / "chunks" / "50-99" / "images" / "_page_3_Figure_1.jpeg").exists()
    # Markdown rewritten:
    raw_md = (out / "chunks" / "50-99" / "raw.md").read_text(encoding="utf-8")
    assert "50-99-_page_3_Figure_1.jpeg" in raw_md
    assert 'id="page-53-2"' in raw_md
    assert "(#page-53-2)" in raw_md
    assert "page-3-2" not in raw_md


def test_chunk_pool_raises_actionable_error_on_sysconf_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("[Errno 1] Operation not permitted: sysconf")

    monkeypatch.setattr("pagespeak.orchestrators._chunk.ProcessPoolExecutor", _bomb)
    monkeypatch.setattr("pagespeak.orchestrators._chunk.count_pages", lambda _p: 10)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    with pytest.raises(PermissionError, match="sandboxed") as excinfo:
        chunk(src, output_dir=out, chunk_pages=50, workers=2)
    assert "docs/operations.md" in str(excinfo.value)
    assert "n_workers=2" in str(excinfo.value)


def test_resolve_cli_workers_default_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI default must stay 1 — DEFAULT_WORKERS sizes the pool, not the choice."""
    monkeypatch.delenv("PAGESPEAK_WORKERS", raising=False)
    assert resolve_cli_workers(None) == 1


def test_resolve_cli_workers_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(None, pdf) == 6


def test_resolve_cli_workers_explicit_beats_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(2, pdf) == 2


def test_resolve_cli_workers_clamps_env_for_non_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambient env value must not push a DOCX or an out dir onto the PDF-only path."""
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"PK\x03\x04")
    outdir = tmp_path / "out"
    outdir.mkdir()
    assert resolve_cli_workers(None, docx) == 1
    assert resolve_cli_workers(None, outdir) == 1
    assert resolve_cli_workers(None, None) == 1
    # An explicit flag still reaches the PDF-only guard, which is the useful error.
    assert resolve_cli_workers(6, docx) == 6


def test_resolve_cli_workers_clamps_env_when_run_is_chunk_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chunked path re-ingests and cannot carry every option, so an ambient
    value must not silently reroute a run that asked for something else."""
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(None, pdf, chunk_unsafe=True) == 1
    assert resolve_cli_workers(None, pdf, chunk_unsafe=False) == 6


def test_resolve_cli_workers_never_clamps_an_explicit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed --workers is a request; the downstream error is the useful answer."""
    monkeypatch.delenv("PAGESPEAK_WORKERS", raising=False)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(4, pdf, chunk_unsafe=True) == 4


def test_resolve_cli_workers_rejects_a_non_positive_explicit_flag() -> None:
    """The error must name `--workers`, not the env var behind the resolver."""
    with pytest.raises(ValueError, match=r"--workers"):
        resolve_cli_workers(0)
    with pytest.raises(ValueError, match=r"--workers"):
        resolve_cli_workers(-2)
