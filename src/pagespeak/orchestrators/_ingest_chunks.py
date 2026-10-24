"""A chunked ingest's output: completed chunks assembled into `<stem>.raw.md`
+ a flat `images/`, and the error and guard for an ingest that left chunks
unfinished."""

from __future__ import annotations

import shutil
from pathlib import Path

from pw_foundation.log import get_logger
from pw_foundation.utils.io import atomic_write_text

from ..backends._pdf_dispatch import PdfBackendName
from ..models._pipeline import Manifest, read_chunk_statuses

logger = get_logger(__name__)


def assemble_chunks(
    mf: Manifest,
    src: Path,
    out: Path,
    *,
    raw_md_path: Path,
    pdf_backend: PdfBackendName,
    heading_hierarchy: bool,
) -> Path:
    """Concat the completed chunks' markdown in page order and flatten their images.

    Raises:
        RuntimeError: no chunk completed.
        PartialIngestError: a chunk is not completed or its markdown is gone;
            raw.md holds the others.
    """
    completed_paths = [p for p in mf.all_chunk_raw_md() if p.exists()]
    failed_page_ranges = _missing_ranges(mf)
    if not completed_paths:
        raise RuntimeError(
            f"Chunked ingest produced no completed chunks in {out}. "
            f"Failed chunks: {len(failed_page_ranges)} of {len(mf.chunks)}. "
            "Inspect manifest.json for per-chunk error state."
        )

    atomic_write_text(
        raw_md_path, "\n\n".join(p.read_text(encoding="utf-8") for p in completed_paths)
    )
    # Stamp provenance from the real PDF, as the single-process path does — a
    # later phase resolves its source to the checkpoint and cannot ask again.
    from ..services._hierarchy_trust import record_hierarchy_source, record_structured

    record_hierarchy_source(out, src, pdf_backend=pdf_backend, heading_hierarchy=heading_hierarchy)
    # Chunked ingest is PDF-only: no backend here reads structure from the format.
    record_structured(out, authoritative=False)

    _flatten_images(mf, out)

    logger.info(
        "ingest_chunked_complete src=%s raw_md=%s chunks=%d images=%d failed=%d",
        src.name,
        raw_md_path.name,
        len(completed_paths),
        len(mf.all_chunk_images()),
        len(failed_page_ranges),
    )

    # raw.md from the successful chunks is kept for resume, but the caller must
    # know the output is incomplete: the CLI exits 2, library callers can retry
    # from `.raw_md_path` + `.failed_page_ranges`.
    if failed_page_ranges:
        raise PartialIngestError(
            raw_md_path=raw_md_path,
            failed_page_ranges=failed_page_ranges,
            total_chunks=len(mf.chunks),
            output_dir=out,
        )

    return raw_md_path


def _flatten_images(mf: Manifest, out: Path) -> None:
    """Copy per-chunk images into `<out>/images/`. Names are already
    page-range-prefixed by `_chunk._run_one_chunk`, so collisions only happen
    for byte-identical duplicates — keep the first."""
    flat_dir = out / "images"
    flat_dir.mkdir(parents=True, exist_ok=True)
    # A shelved chunk keeps its images under chunks/; a flat copy would reach vision.
    current = {img.name for img in mf.all_chunk_images()}
    for shelved in mf.shelved:
        for rel in shelved.images:
            if Path(rel).name not in current:
                (flat_dir / Path(rel).name).unlink(missing_ok=True)
    # Copy, not move: the `chunks/<range>/images/` originals let a failed
    # flatten resume, since `mf.all_chunk_images()` still resolves on re-run.
    for img in mf.all_chunk_images():
        if not img.exists():
            logger.warning("ingest_image_missing path=%s", img)
            continue
        target = flat_dir / img.name
        if target.exists():
            continue
        shutil.copy2(img, target)


def _missing_ranges(mf: Manifest) -> list[str]:
    """Page ranges not in raw.md: a chunk not completed, or completed with its markdown gone."""
    return [
        c.page_range
        for c in mf.chunks
        if c.status != "completed" or not c.raw_md or not (mf.output_dir / c.raw_md).exists()
    ]


class PartialIngestError(RuntimeError):
    """A chunked ingest left pages out: a chunk failed, did not finish, or lost its
    markdown. `raw_md_path` holds the other chunks; re-running `pagespeak ingest`
    without `--force` runs only the missing ones (`failed_page_ranges`)."""

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


def assert_ingest_complete(output_dir: Path | None, *, allow_partial: bool = False) -> None:
    """Refuse to build a document from an out dir whose chunked ingest never finished.

    Nothing downstream reads chunk status — resume keys on the raw.md snapshot — so
    without this a run whose chunk OOMed yields a document silently missing those
    pages, at exit 0.
    """
    if output_dir is None:
        return
    statuses = read_chunk_statuses(output_dir)
    incomplete = [pr for pr, st in statuses if st != "completed"]
    if not incomplete:
        return
    if allow_partial:
        logger.warning("ingest_incomplete_accepted output_dir=%s chunks=%s", output_dir, incomplete)
        return
    raw = sorted(output_dir.glob("*.raw.md"))
    raise PartialIngestError(
        raw_md_path=raw[0] if raw else output_dir,
        failed_page_ranges=incomplete,
        total_chunks=len(statuses),
        output_dir=output_dir,
    )
