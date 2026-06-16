"""Unified backend phase: produce `<stem>.raw.md` + `images/` for one document.

Single entry point for "convert source → raw markdown." Dispatches on
`workers`:

- `workers == 1` (default): backend runs in-process. For PDFs this is
  Marker / docling; for other formats this is MarkItDown. Output goes
  directly to `<output_dir>/<stem>.raw.md` + `<output_dir>/images/`.

- `workers > 1`: PDF only. Splits the document into page-range chunks,
  runs a ProcessPoolExecutor of N workers, then concats per-chunk
  markdown in page order and flattens per-chunk images into a flat
  `<output_dir>/images/`. Manifest + `chunks/` artifacts persist for
  resume.

Output shape is identical between the two paths: `<stem>.raw.md` plus a
flat `images/` directory. Phase 3 (`pagespeak convert <outdir>`) runs
the same downstream regardless of which path produced the raw.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pf_core.log import get_logger

from ..backends._docx_dispatch import DEFAULT_DOCX_BACKEND, DocxBackendName
from ..backends._pdf_dispatch import DEFAULT_PDF_BACKEND, PdfBackendName
from ..backends._qti import is_qti_export
from ..models._pipeline import Manifest
from ._chunk import chunk as chunk_phase
from ._chunk import resolve_chunk_pages

logger = get_logger(__name__)

PDF_SUFFIXES: frozenset[str] = frozenset({".pdf"})
MARKITDOWN_SUFFIXES: frozenset[str] = frozenset(
    {
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".htm",
        ".csv",
        ".json",
        ".xml",
        ".epub",
    }
)
# Legacy binary Office (.doc / .ppt / .xls) is deliberately excluded: MarkItDown
# does not reliably handle the pre-OOXML binary formats, so they fall through to
# a clear "Unsupported format" error rather than a silent lossy conversion.
# Convert to .docx / .pptx / .xlsx first. See docs/format-support.md.
# Markdown deliverables are already the pipeline's target format — read them
# straight into raw.md rather than round-tripping through MarkItDown (lossy on
# lists / headings / emphasis). Lets an upstream ingester hand off clean
# markdown for the cleanup → split passes.
MARKDOWN_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown"})


def ingest(
    input_path: str | Path,
    *,
    output_dir: str | Path,
    workers: int = 1,
    pdf_backend: PdfBackendName = DEFAULT_PDF_BACKEND,
    pdf_backend_kwargs: dict[str, Any] | None = None,
    docx_backend: DocxBackendName = DEFAULT_DOCX_BACKEND,
    docx_outline_heading_depth: int = 0,
    chunk_pages: int | None = None,
    device: str | None = None,
    force_ocr: bool = False,
    page_range: str | list[int] | None = None,
    html_base_url: str | None = None,
    force: bool = False,
    max_pages: int | None = None,
) -> Path:
    """Produce `<output_dir>/<stem>.raw.md` + `<output_dir>/images/` for one input.

    Args:
        input_path: Source document.
        output_dir: Where raw.md + images/ + (when chunked) manifest+chunks/ live.
        workers: 1 (single-process) or N>1 (chunked-parallel, PDF-only).
        pdf_backend: 'marker' or 'docling'. Ignored for non-PDF inputs.
        pdf_backend_kwargs: Backend-specific options.
        docx_outline_heading_depth: python-docx backend only — the
            outline→heading switch. Default 0 = retain the WHOLE Word
            outline as a nested list (only the document title is `#`);
            N>0 overrides the top N outline levels into headings.
        chunk_pages: Page chunk size when chunked. Defaults to
            `PAGESPEAK_CHUNK_PAGES` env or 50.
        device: Forwarded to backend.
        force_ocr: Forwarded to backend.
        page_range: Forwarded to backend (single-process path only).
        html_base_url: HTML-only — base URL to resolve relative `<img>` refs
            against so a web-help export's images download (single-process).
        force: Discard manifest + chunks; re-run from scratch.
        max_pages: Limit ingest to first N pages of the PDF.

    Returns:
        The absolute path to `<output_dir>/<stem>.raw.md`.

    Raises:
        ValueError: workers < 1, or chunked path requested for non-PDF.
        FileNotFoundError: input doesn't exist.
    """
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers!r}")

    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"No such file: {src}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_md_path = out / f"{src.stem}.raw.md"
    suffix = src.suffix.lower()

    # Canvas QTI exports fan out into one full-pipeline document per quiz —
    # there is no single raw.md to produce, so `ingest` doesn't apply.
    if is_qti_export(src):
        raise ValueError(
            "Canvas QTI exports are converted with `pagespeak convert`, not `ingest` "
            "(each quiz becomes its own full-pipeline document)."
        )

    if workers == 1:
        return _ingest_single_process(
            src,
            out,
            raw_md_path=raw_md_path,
            suffix=suffix,
            pdf_backend=pdf_backend,
            pdf_backend_kwargs=pdf_backend_kwargs,
            docx_backend=docx_backend,
            docx_outline_heading_depth=docx_outline_heading_depth,
            device=device,
            force_ocr=force_ocr,
            page_range=page_range,
            html_base_url=html_base_url,
        )

    if page_range is not None:
        raise ValueError(
            "page_range is not supported on the chunked path (workers > 1). "
            "Use max_pages instead, or set workers=1."
        )

    if suffix not in PDF_SUFFIXES:
        raise ValueError(
            f"Chunked ingest (workers>1) is PDF-only; got {suffix!r}. "
            "Use workers=1 for non-PDF formats."
        )
    return _ingest_chunked(
        src,
        out,
        raw_md_path=raw_md_path,
        workers=workers,
        chunk_pages=resolve_chunk_pages(chunk_pages),
        pdf_backend=pdf_backend,
        pdf_backend_kwargs=pdf_backend_kwargs,
        device=device,
        force_ocr=force_ocr,
        force=force,
        max_pages=max_pages,
    )


def _ingest_single_process(
    src: Path,
    out: Path,
    *,
    raw_md_path: Path,
    suffix: str,
    pdf_backend: PdfBackendName,
    pdf_backend_kwargs: dict[str, Any] | None,
    docx_backend: DocxBackendName,
    docx_outline_heading_depth: int,
    device: str | None,
    force_ocr: bool,
    page_range: str | list[int] | None,
    html_base_url: str | None = None,
) -> Path:
    """Run the backend in-process and write raw.md + images/."""
    if suffix in PDF_SUFFIXES:
        from ..backends._pdf_dispatch import convert as _pdf_convert

        result = _pdf_convert(
            pdf_backend,
            src,
            output_dir=out,
            force_ocr=force_ocr,
            device=device,
            page_range=page_range,
            backend_kwargs=pdf_backend_kwargs,
        )
    elif suffix in MARKITDOWN_SUFFIXES:
        if suffix == ".docx":
            from ..backends._docx_dispatch import convert as _docx_convert

            result = _docx_convert(
                docx_backend,
                src,
                output_dir=out,
                outline_heading_depth=docx_outline_heading_depth,
            )
        else:
            from ..backends._docx import convert_with_markitdown

            result = convert_with_markitdown(src, output_dir=out, html_base_url=html_base_url)
    elif suffix in MARKDOWN_SUFFIXES:
        from ..backends._markdown import convert_markdown

        result = convert_markdown(src)
    else:
        raise ValueError(
            f"Unsupported format: {suffix!r}. Supported: "
            f"{sorted(PDF_SUFFIXES | MARKITDOWN_SUFFIXES | MARKDOWN_SUFFIXES)}"
        )

    raw_md_path.write_text(result.markdown, encoding="utf-8")
    logger.info(
        "ingest_single_process_complete src=%s raw_md=%s images=%d",
        src.name,
        raw_md_path.name,
        len(result.images),
    )
    return raw_md_path


def _ingest_chunked(
    src: Path,
    out: Path,
    *,
    raw_md_path: Path,
    workers: int,
    chunk_pages: int,
    pdf_backend: PdfBackendName,
    pdf_backend_kwargs: dict[str, Any] | None,
    device: str | None,
    force_ocr: bool,
    force: bool,
    max_pages: int | None,
) -> Path:
    """Run the chunked backend path, concat per-chunk markdown, flatten images."""
    if force:
        mf_path = Manifest.path_for(out)
        if mf_path.exists():
            mf_path.unlink()
        chunks_dir = out / "chunks"
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir)

    mf = chunk_phase(
        input_path=src,
        output_dir=out,
        chunk_pages=chunk_pages,
        workers=workers,
        device=device,
        force_ocr=force_ocr,
        force=False,  # manifest cleared above if force=True
        max_pages=max_pages,
        pdf_backend=pdf_backend,
        pdf_backend_kwargs=pdf_backend_kwargs,
    )

    completed_paths = mf.all_chunk_raw_md()
    failed_page_ranges = [c.page_range for c in mf.chunks if c.status == "failed"]
    if not completed_paths:
        raise RuntimeError(
            f"Chunked ingest produced no completed chunks in {out}. "
            f"Failed chunks: {len(failed_page_ranges)} of {len(mf.chunks)}. "
            "Inspect manifest.json for per-chunk error state."
        )

    # Concat per-chunk markdown in page-range order.
    parts: list[str] = []
    for p in completed_paths:
        if not p.exists():
            logger.warning("ingest_chunk_md_missing path=%s", p)
            continue
        parts.append(p.read_text(encoding="utf-8"))
    consolidated = "\n\n".join(parts)
    raw_md_path.write_text(consolidated, encoding="utf-8")

    # Flatten per-chunk images into <out>/images/. Names are already
    # page-range-prefixed by `_chunk._run_one_chunk`, so collisions
    # only happen for byte-identical duplicates — keep the first.
    flat_dir = out / "images"
    flat_dir.mkdir(parents=True, exist_ok=True)
    # Copy (not move) per-chunk images into the flat dir. Keeping the
    # `chunks/<range>/images/` originals lets a partial-flatten failure
    # resume cleanly — `mf.all_chunk_images()` still resolves on re-run.
    # Disk-space cost is bounded by the doc's image set (single copy in
    # flat dir + single copy per chunk; no inflation across chunks since
    # chunk-prefixed basenames are unique).
    for img in mf.all_chunk_images():
        if not img.exists():
            logger.warning("ingest_image_missing path=%s", img)
            continue
        target = flat_dir / img.name
        if target.exists():
            continue
        shutil.copy2(img, target)

    logger.info(
        "ingest_chunked_complete src=%s raw_md=%s chunks=%d images=%d failed=%d",
        src.name,
        raw_md_path.name,
        len(completed_paths),
        len(mf.all_chunk_images()),
        len(failed_page_ranges),
    )

    # raise PartialIngestError when ANY chunks failed. raw.md
    # is already written from the successful chunks (preserves resume
    # value), but the caller must know that the output is incomplete.
    # CLI catches this and exits with code 2; library callers can catch
    # to access `.raw_md_path` + `.failed_page_ranges` for retry logic.
    if failed_page_ranges:
        raise PartialIngestError(
            raw_md_path=raw_md_path,
            failed_page_ranges=failed_page_ranges,
            total_chunks=len(mf.chunks),
            output_dir=out,
        )

    return raw_md_path


class PartialIngestError(RuntimeError):
    """Raised when chunked ingest completes with at least one failed chunk.

    The output dir state IS valid for resume: completed chunks are
    written to `chunks/<range>/`, raw.md contains content from the
    successful chunks only, and manifest.json records which chunks
    failed (with error tracebacks). Re-running `pagespeak ingest`
    without `--force` resumes only the failed chunks.

    Attributes:
        raw_md_path: The (partial) <stem>.raw.md on disk.
        failed_page_ranges: List of page-range strings that failed.
        total_chunks: Total chunks planned (failed + completed).
        output_dir: The ingest output directory.
    """

    def __init__(
        self,
        *,
        raw_md_path: Path,
        failed_page_ranges: list[str],
        total_chunks: int,
        output_dir: Path,
    ) -> None:
        self.raw_md_path = raw_md_path
        self.failed_page_ranges = failed_page_ranges
        self.total_chunks = total_chunks
        self.output_dir = output_dir
        completed = total_chunks - len(failed_page_ranges)
        sample = failed_page_ranges[:5]
        suffix = "" if len(failed_page_ranges) <= 5 else f" (+{len(failed_page_ranges) - 5} more)"
        super().__init__(
            f"Chunked ingest completed with {len(failed_page_ranges)} of "
            f"{total_chunks} chunks failed (completed: {completed}). "
            f"Partial raw.md written to {raw_md_path}. "
            f"Failed page ranges: {sample}{suffix}. "
            f"Inspect {output_dir}/manifest.json for error details, then "
            "re-run `pagespeak ingest <input> -o <outdir>` (without --force) "
            "to retry the failed chunks only."
        )


__all__ = ["MARKITDOWN_SUFFIXES", "PDF_SUFFIXES", "PartialIngestError", "ingest"]
