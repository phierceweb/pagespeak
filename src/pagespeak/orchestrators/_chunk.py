"""Chunk phase: parallel Marker conversion of page-range slices.

Splits a PDF into N-page chunks, runs each through Marker in a separate
process (Marker isn't thread-safe and the torch+surya model load is per-
process), and records each chunk's output in the manifest. Resume on
re-invocation: chunks marked `completed` are skipped.

The chunked output lives under `OUTDIR/chunks/<page_range>/`:

    chunks/0-49/raw.md
    chunks/0-49/images/_page_0_Figure_2.jpeg
    chunks/50-99/raw.md
    ...

The stitch phase later concats the raw.md files and copies/symlinks images
into a flat `OUTDIR/images/` for the consolidated markdown to reference.
"""

from __future__ import annotations

import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pf_core.log import get_logger
from pf_core.utils.env import resolve_positive_int

from ..backends._pdf_dispatch import DEFAULT_PDF_BACKEND, PdfBackendName
from ..models._pipeline import ChunkState, Manifest

logger = get_logger(__name__)

DEFAULT_CHUNK_PAGES = 50
CHUNK_PAGES_ENV_VAR = "PAGESPEAK_CHUNK_PAGES"
WORKERS_ENV_VAR = "PAGESPEAK_WORKERS"
DEFAULT_WORKERS = 4


def resolve_chunk_pages(explicit: int | None = None) -> int:
    """Pick chunk size (pages): explicit param > env var > default 50.

    Operational tunable (env-configurable) — larger chunks
    mean fewer Marker model-loads (~30s each), smaller chunks mean
    finer-grained resume. Memory-bound: each worker holds its chunk in
    RAM. Delegates to `pf_core.utils.env.resolve_positive_int`: an
    explicit `< 1` raises `ValueError`; a malformed or out-of-range env
    value warns and falls back to the default.
    """
    return resolve_positive_int(
        explicit, CHUNK_PAGES_ENV_VAR, default=DEFAULT_CHUNK_PAGES, min_value=1
    )


def resolve_workers(explicit: int | None = None) -> int:
    """Pick worker count: explicit param > env var > default 4.

    Delegates to `pf_core.utils.env.resolve_positive_int`. An explicit
    `< 1` raises `ValueError` (caller bug — fail fast). A malformed env
    var emits a structured `env_var_malformed` warning and falls back to
    the default; an out-of-range env value (e.g. `"-3"` that parses but
    isn't positive) emits `env_var_out_of_range` and falls back rather
    than allowed to deadlock the ProcessPoolExecutor. Operator typos no
    longer crash the pipeline.
    """
    return resolve_positive_int(explicit, WORKERS_ENV_VAR, default=DEFAULT_WORKERS, min_value=1)


def count_pages(pdf_path: Path) -> int:
    """Count pages in a PDF using pypdfium2 (already a Marker dep)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise ImportError(
            "Page counting requires pypdfium2 (a Marker dep). "
            "Install with: pip install pagespeak[pdf]"
        ) from e
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


@dataclass(frozen=True)
class ChunkPlan:
    page_range: str  # "0-49"
    start: int  # 0-based, inclusive
    end: int  # 0-based, inclusive


def plan_chunks(total_pages: int, chunk_pages: int) -> list[ChunkPlan]:
    """Slice a page count into fixed-size chunks. Last chunk may be shorter."""
    if total_pages < 1:
        raise ValueError(f"total_pages must be >= 1, got {total_pages}")
    if chunk_pages < 1:
        raise ValueError(f"chunk_pages must be >= 1, got {chunk_pages}")
    plans: list[ChunkPlan] = []
    for start in range(0, total_pages, chunk_pages):
        end = min(start + chunk_pages - 1, total_pages - 1)
        plans.append(ChunkPlan(page_range=f"{start}-{end}", start=start, end=end))
    return plans


# --- Worker (must be importable at module level for pickling) ----


@dataclass(frozen=True)
class _ChunkResult:
    page_range: str
    raw_md_rel: str | None  # relative to OUTDIR
    image_rels: list[str]  # relative to OUTDIR
    error: str | None


def _run_one_chunk(
    *,
    input_path: str,
    output_dir: str,
    page_range: str,
    device: str | None,
    force_ocr: bool,
    pdf_backend: PdfBackendName = DEFAULT_PDF_BACKEND,
    backend_kwargs: dict[str, Any] | None = None,
) -> _ChunkResult:
    """Convert one page-range slice. Runs in a worker process.

    Each worker reloads the active backend's models on first call (Marker:
    torch+surya; Docling: layout + tableformer + OCR). All paths in/out
    are strings to keep pickling simple.

    post-backend, the worker rewrites the chunk's markdown so
    image basenames are page-range-prefixed and page-anchor IDs/refs
    are absolute (offset by the chunk's start page). Image files are
    renamed on disk to match. This means cross-chunk concatenation in
    `_ingest.py` doesn't need to disambiguate — the chunks already
    sit in a deterministic, collision-free layout.
    """
    try:
        from ..backends._pdf_dispatch import convert as _pdf_convert
        from ..services._chunk_rewrite import (
            prefix_image_basenames,
            rewrite_anchor_ids_to_absolute,
        )

        out_root = Path(output_dir)
        chunk_dir = out_root / "chunks" / page_range
        chunk_dir.mkdir(parents=True, exist_ok=True)

        result = _pdf_convert(
            pdf_backend,
            Path(input_path),
            output_dir=chunk_dir,
            force_ocr=force_ocr,
            device=device,
            page_range=page_range,
            backend_kwargs=backend_kwargs,
        )

        # Compute absolute page offset from the chunk's page_range
        # ("50-99" → offset 50). Malformed page_range = programmer bug; let
        # it raise so the outer except produces a clear traceback.
        start_str = page_range.split("-", 1)[0]
        page_offset = int(start_str)

        # Rewrite anchor IDs/refs to absolute pages.
        rewritten_md = rewrite_anchor_ids_to_absolute(result.markdown, page_offset=page_offset)
        # Rewrite image refs in markdown + rename image files on disk.
        rewritten_md, renames = prefix_image_basenames(rewritten_md, page_range=page_range)
        renamed_images: list[Path] = []
        for img in result.images:
            old_name = img.name
            new_name = renames.get(old_name, old_name)
            target = img.parent / new_name
            if old_name != new_name and not target.exists():
                img.rename(target)
            if not target.exists():
                raise RuntimeError(
                    f"chunk worker expected image at {target} "
                    f"(renamed from {img}) but file is missing"
                )
            renamed_images.append(target)

        raw_md = chunk_dir / "raw.md"
        raw_md.write_text(rewritten_md, encoding="utf-8")

        raw_md_rel = str(raw_md.relative_to(out_root))
        image_rels = [str(p.relative_to(out_root)) for p in renamed_images]

        return _ChunkResult(
            page_range=page_range,
            raw_md_rel=raw_md_rel,
            image_rels=image_rels,
            error=None,
        )
    except Exception:
        return _ChunkResult(
            page_range=page_range,
            raw_md_rel=None,
            image_rels=[],
            error=traceback.format_exc(limit=8),
        )


# --- Public API ----


def chunk(
    input_path: str | Path,
    *,
    output_dir: str | Path,
    chunk_pages: int | None = None,
    workers: int | None = None,
    device: str | None = None,
    force_ocr: bool = False,
    force: bool = False,
    max_pages: int | None = None,
    pdf_backend: PdfBackendName = DEFAULT_PDF_BACKEND,
    pdf_backend_kwargs: dict[str, Any] | None = None,
) -> Manifest:
    """Run the chunk phase: parallel Marker conversion of page-range slices.

    Args:
        input_path: Source PDF.
        output_dir: Where the manifest and chunks/ live. Created if missing.
        chunk_pages: Pages per chunk. Defaults to `PAGESPEAK_CHUNK_PAGES`
            env or 50. Smaller chunks mean finer-grained resume; larger
            chunks mean less Marker model-load overhead (~30s per worker).
        workers: Process pool size. Defaults to `PAGESPEAK_WORKERS` env or 4.
            Each worker loads ~2GB of torch+surya state.
        device: Forwarded to `convert_pdf` (e.g. `"cpu"` to dodge MPS crash).
        force_ocr: Forwarded to `convert_pdf`.
        force: If True, re-run even chunks already marked completed in the
            manifest. Default False (resume).
        max_pages: If set, only chunk the first N pages of the PDF (0-based
            counting). Useful for sanity-checking the pipeline on a smaller
            slice of a long doc before committing to the full run.

    Returns:
        The updated `Manifest`. Inspect `mf.chunks` for per-chunk status.
    """
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"No such file: {src}")
    if src.suffix.lower() != ".pdf":
        raise ValueError(
            f"chunk() only handles PDFs today; got {src.suffix!r}. "
            "Use to_markdown() for other formats."
        )
    out = Path(output_dir)

    mf = Manifest.load_or_create(out, input_path=src)

    # Refuse to resume across mismatched PDF backends. The two produce
    # subtly different markdown and image-name conventions; mixing them in
    # one manifest leads to broken anchor maps and orphan image refs at
    # stitch time.
    completed_backends = {
        c.pdf_backend for c in mf.chunks if c.status == "completed" and c.pdf_backend
    }
    if completed_backends and pdf_backend not in completed_backends and not force:
        raise ValueError(
            f"Output dir {out} has chunks completed with backend(s) "
            f"{sorted(completed_backends)}; cannot resume with "
            f"pdf_backend={pdf_backend!r}. Use --force to re-run from scratch, "
            f"or pick a fresh output dir."
        )

    total = count_pages(src)
    if max_pages is not None:
        if max_pages < 1:
            raise ValueError(f"max_pages must be >= 1, got {max_pages!r}")
        total = min(total, max_pages)
    chunk_pages = resolve_chunk_pages(chunk_pages)
    plans = plan_chunks(total, chunk_pages)
    completed = mf.completed_chunk_ranges() if not force else set()

    todo = [p for p in plans if p.page_range not in completed]
    logger.info(
        "chunk_phase_start total_pages=%d total_chunks=%d todo=%d completed=%d",
        total,
        len(plans),
        len(todo),
        len(completed),
    )

    if not todo:
        return mf

    n_workers = resolve_workers(workers)

    # Mark planned-but-pending chunks so the manifest reflects intent.
    for p in todo:
        existing = mf.chunk_by_range(p.page_range)
        if existing is None or existing.status not in ("completed", "in_progress"):
            mf.add_or_update_chunk(ChunkState(page_range=p.page_range, status="in_progress"))

    try:
        pool_cm = ProcessPoolExecutor(max_workers=n_workers)
    except PermissionError as e:
        if "sysconf" in str(e) or "Operation not permitted" in str(e):
            raise PermissionError(
                f"ProcessPoolExecutor failed to start (n_workers={n_workers}). "
                "This usually means the shell is sandboxed and "
                '`os.sysconf("SC_SEM_NSEMS_MAX")` is denied. '
                "Re-run with broader permissions or use single-shot conversion "
                "(`pagespeak convert`). "
                "See docs/operations.md for details."
            ) from e
        raise

    with pool_cm as pool:
        futures = {
            pool.submit(
                _run_one_chunk,
                input_path=str(src),
                output_dir=str(out),
                page_range=p.page_range,
                device=device,
                force_ocr=force_ocr,
                pdf_backend=pdf_backend,
                backend_kwargs=pdf_backend_kwargs,
            ): p
            for p in todo
        }
        for fut in as_completed(futures):
            plan = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                logger.warning("chunk_worker_died page_range=%s error=%s", plan.page_range, e)
                mf.mark_chunk_failed(plan.page_range, error=str(e))
                continue

            if result.error is not None:
                logger.warning(
                    "chunk_failed page_range=%s error=%s",
                    result.page_range,
                    result.error.splitlines()[-1] if result.error else "",
                )
                mf.mark_chunk_failed(result.page_range, error=result.error)
            else:
                assert result.raw_md_rel is not None
                mf.mark_chunk_completed(
                    result.page_range,
                    raw_md=result.raw_md_rel,
                    images=result.image_rels,
                    pdf_backend=pdf_backend,
                )
                logger.info(
                    "chunk_completed page_range=%s images=%d backend=%s",
                    result.page_range,
                    len(result.image_rels),
                    pdf_backend,
                )

    return mf
