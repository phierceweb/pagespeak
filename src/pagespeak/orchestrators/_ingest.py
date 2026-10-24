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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pw_foundation.log import get_logger
from pw_foundation.utils.io import atomic_write_text

from ..backends._docx_dispatch import DEFAULT_DOCX_BACKEND, DocxBackendName
from ..backends._pdf_dispatch import DEFAULT_PDF_BACKEND, PdfBackendName
from ..backends._qti import is_qti_export
from ..models._pipeline import Manifest
from ._chunk import chunk as chunk_phase
from ._chunk import count_pages
from ._chunk_sizing import resolve_chunk_pages
from ._convert_source import (
    MARKDOWN_SUFFIXES,
    MARKITDOWN_SUFFIXES,
    PDF_SUFFIXES,
    convert_source,
    unsupported_format_error,
)
from ._ingest_chunks import PartialIngestError, assemble_chunks, assert_ingest_complete

logger = get_logger(__name__)


def ingest(
    input_path: str | Path,
    *,
    output_dir: str | Path,
    workers: int = 1,
    pdf_backend: PdfBackendName = DEFAULT_PDF_BACKEND,
    pdf_backend_kwargs: dict[str, Any] | None = None,
    heading_hierarchy: bool = False,
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
        max_pages: Limit ingest to first N pages of the PDF (not with
            `page_range` or the tophat backend).

    Returns:
        The absolute path to `<output_dir>/<stem>.raw.md`.

    Raises:
        ValueError: workers < 1, chunked path requested for non-PDF, or a
            `max_pages` that cannot apply.
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

    started_at = _now_utc_iso()
    flags: dict[str, Any] = {
        "pdf_backend": pdf_backend,
        "pdf_backend_kwargs": pdf_backend_kwargs,
        "heading_hierarchy": heading_hierarchy,
        "force_ocr": force_ocr,
        "device": device,
        "page_range": page_range,
        "html_base_url": html_base_url,
        "docx_backend": docx_backend,
        "docx_outline_heading_depth": docx_outline_heading_depth,
        "max_pages": max_pages,
    }
    if workers == 1:
        if max_pages is not None:
            page_range = _first_pages(
                src, suffix=suffix, pdf_backend=pdf_backend, page_range=page_range, n=max_pages
            )
        raw = _ingest_single_process(
            src,
            out,
            raw_md_path=raw_md_path,
            suffix=suffix,
            pdf_backend=pdf_backend,
            pdf_backend_kwargs=pdf_backend_kwargs,
            heading_hierarchy=heading_hierarchy,
            docx_backend=docx_backend,
            docx_outline_heading_depth=docx_outline_heading_depth,
            device=device,
            force_ocr=force_ocr,
            page_range=page_range,
            html_base_url=html_base_url,
        )
        stamp_ingest_record(out, src, flags, started_at=started_at)
        return raw

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
    try:
        raw = _ingest_chunked(
            src,
            out,
            raw_md_path=raw_md_path,
            workers=workers,
            chunk_pages=resolve_chunk_pages(chunk_pages),
            pdf_backend=pdf_backend,
            pdf_backend_kwargs=pdf_backend_kwargs,
            heading_hierarchy=heading_hierarchy,
            device=device,
            force_ocr=force_ocr,
            force=force,
            max_pages=max_pages,
        )
    except PartialIngestError:
        stamp_ingest_record(out, src, flags, started_at=started_at)
        raise
    stamp_ingest_record(out, src, flags, started_at=started_at)
    return raw


def _now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_pages(
    src: Path, *, suffix: str, pdf_backend: str, page_range: str | list[int] | None, n: int
) -> str:
    """The 0-based page range for `max_pages=n` on the single-process path."""
    if n < 1:
        raise ValueError(f"max_pages must be >= 1, got {n!r}")
    if suffix not in PDF_SUFFIXES:
        raise ValueError(f"max_pages applies to PDFs only; got {suffix!r}")
    if pdf_backend == "tophat":
        raise ValueError(
            "max_pages does not apply to the tophat backend, which reads the whole export"
        )
    if page_range is not None:
        raise ValueError("pass page_range or max_pages, not both")
    return f"0-{min(n, count_pages(src)) - 1}"


def stamp_ingest_record(
    out: Path, src: Path, flags: dict[str, Any], *, started_at: str | None = None
) -> None:
    """Stamp the ingest flags into `.pagespeak-run.json` as soon as raw.md exists, so
    a run that dies later still leaves a record that describes the raw.md. A write
    failure is non-fatal."""
    from .. import __version__
    from ..services._provenance import persistable_source_identity
    from ..services._run_record import record_ingest

    images_dir = out / "images"
    try:
        record_ingest(
            out,
            version=__version__,
            input_path=src,
            flags=flags,
            started_at=started_at or _now_utc_iso(),
            finished_at=_now_utc_iso(),
            image_count=sum(1 for _ in images_dir.iterdir()) if images_dir.is_dir() else 0,
            source_identity=persistable_source_identity(src, out, dir_mode=False),
        )
    except OSError as e:
        logger.warning("run_record_write_failed path=%s error=%s", out, e)


def _ingest_single_process(
    src: Path,
    out: Path,
    *,
    raw_md_path: Path,
    suffix: str,
    pdf_backend: PdfBackendName,
    pdf_backend_kwargs: dict[str, Any] | None,
    heading_hierarchy: bool,
    docx_backend: DocxBackendName,
    docx_outline_heading_depth: int,
    device: str | None,
    force_ocr: bool,
    page_range: str | list[int] | None,
    html_base_url: str | None = None,
) -> Path:
    """Run the backend in-process and write raw.md + images/."""
    result = convert_source(
        src,
        out,
        suffix=suffix,
        pdf_backend=pdf_backend,
        pdf_backend_kwargs=pdf_backend_kwargs,
        heading_hierarchy=heading_hierarchy,
        docx_backend=docx_backend,
        docx_outline_heading_depth=docx_outline_heading_depth,
        device=device,
        force_ocr=force_ocr,
        page_range=page_range,
        html_base_url=html_base_url,
    )
    atomic_write_text(raw_md_path, result.markdown)
    # Stamp provenance now: a resume run resolves src to a checkpoint.
    from ..services._hierarchy_trust import record_hierarchy_source, record_structured

    record_hierarchy_source(out, src, pdf_backend=pdf_backend, heading_hierarchy=heading_hierarchy)
    # Both ingest entry points stamp this, so a split ingest/convert keeps the
    # signal. This path always runs the backend, so the value is always current.
    record_structured(
        out,
        authoritative=result.structure_authoritative,
        authored_headings=result.authored_headings,
    )
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
    heading_hierarchy: bool,
    device: str | None,
    force_ocr: bool,
    force: bool,
    max_pages: int | None,
) -> Path:
    """Run the chunked backend path, then assemble the chunks into raw.md + images/."""
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
        heading_hierarchy=heading_hierarchy,
    )
    return assemble_chunks(
        mf,
        src,
        out,
        raw_md_path=raw_md_path,
        pdf_backend=pdf_backend,
        heading_hierarchy=heading_hierarchy,
    )


__all__ = [
    "MARKDOWN_SUFFIXES",
    "MARKITDOWN_SUFFIXES",
    "PDF_SUFFIXES",
    "PartialIngestError",
    "assert_ingest_complete",
    "convert_source",
    "ingest",
    "stamp_ingest_record",
    "unsupported_format_error",
]
