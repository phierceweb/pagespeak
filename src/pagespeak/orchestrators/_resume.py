"""Resume helpers for the single-shot dispatcher.

Thin shim over `pf_core.pipeline.resume`. Two checkpoints can
short-circuit a re-run:

1. `<stem>.raw.md` — the backend's output, persisted immediately after
   Marker / MarkItDown returns. Lets a crashed-mid-vision run skip the
   backend on the next attempt.
2. `<stem>.cleaned.md` — the markdown after frontmatter strip +
   decoration strip + cleanup. Lets a re-run with no upstream change
   skip cleanup. Vision runs in a downstream phase, so vision flag
   changes don't invalidate `cleaned.md`.

A thin binding over `pf_core.pipeline.resume`: supplies the
pagespeak-specific cleanup-affecting flag set + run-record filename and
preserves the public API.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pf_core.pipeline.resume import SnapshotValidator, try_resume_from_snapshot

from ..backends._pdf import parse_page_range
from ..models._models import IngestResult
from ..models._pipeline import completed_chunk_backends
from ..services._hierarchy_trust import ingested_from_outline
from ..services._run_record import INGEST_FLAGS_FIELD, read_run_record

# Cleanup-affecting flags. If any of these change between runs, the
# cleaned.md snapshot is stale and Phase 3a (frontmatter strip +
# decoration strip + cleanup) must re-run. Vision flags dropped
# — vision injection moved to after normalize-apply, no longer affects
# cleaned.md.
_CLEANUP_AFFECTING_FLAGS: tuple[str, ...] = (
    "cleanup",
    "cross_refs",
    "strip_frontmatter",
    "decoration_threshold",
    "decoration_hamming_distance",
)


def _compared_ingest_keys(suffix: str, flags: Mapping[str, Any]) -> tuple[str, ...]:
    """The ingest flags that change what this format's backend writes."""
    if suffix == ".pdf":
        keys = ("pdf_backend", "force_ocr", "page_range", "max_pages")
        return (*keys, "heading_hierarchy") if flags.get("pdf_backend") == "docling" else keys
    if suffix == ".docx":
        if flags.get("docx_backend") == "python-docx":
            return ("docx_backend", "docx_outline_heading_depth")
        return ("docx_backend",)
    if suffix in (".html", ".htm"):
        return ("html_base_url",)
    return ()


def _comparable(key: str, value: Any) -> Any:
    if key == "page_range" and value is not None:
        try:
            return tuple(parse_page_range(value))
        except (TypeError, ValueError):
            return value
    return value


def recorded_ingest_flags(out: Path) -> dict[str, Any]:
    """The settings that produced `out`'s raw.md, as far as they are known.

    The `ingest_flags` block, else an older record's `resolved_flags` — unless a
    run over the output dir wrote it (input = the raw.md checkpoint): those are
    defaults, so only ingest's own traces count (chunk backends, outline marker).
    """
    record = read_run_record(out) or {}
    block = record.get(INGEST_FLAGS_FIELD)
    if isinstance(block, dict):
        return block
    flags = record.get("resolved_flags")
    if not isinstance(flags, dict):
        return {}
    if not str(record.get("input", "")).endswith(".raw.md"):
        return flags
    evidence: dict[str, Any] = {}
    backends = completed_chunk_backends(out)
    if len(backends) == 1:
        evidence["pdf_backend"] = backends.pop()
    if ingested_from_outline(out):
        evidence.update(pdf_backend="docling", heading_hierarchy=True)
    return evidence


def assert_ingest_flags_match(out: Path, suffix: str, current: Mapping[str, Any]) -> None:
    """Refuse to reuse a raw.md that was ingested differently.

    A key with no record (an older record, or none) is not evidence of a
    mismatch. Re-ingesting silently instead would switch a docling dir to
    Marker and re-describe nearly every image.
    """
    recorded = recorded_ingest_flags(out)
    diffs = [
        f"{key}: {recorded[key]!r} → {current.get(key)!r}"
        for key in _compared_ingest_keys(suffix, current)
        if key in recorded and _comparable(key, recorded[key]) != _comparable(key, current.get(key))
    ]
    if diffs:
        raise ValueError(
            f"{out} holds a raw.md ingested with different settings ({'; '.join(diffs)}). "
            "Pass --rerun-from ingest to re-ingest, or re-run with the recorded settings."
        )


def _try_resume_from_checkpoint(
    src: Path,
    out: Path | None,
    raw_md_path: Path | None,
    *,
    source_format: str,
    current_flags: Mapping[str, Any] | None = None,
) -> IngestResult | None:
    """Reload an in-progress conversion from `<stem>.raw.md` + `images/`.

    Returns a hydrated `IngestResult` if a usable checkpoint exists,
    else `None` (caller runs the backend fresh). The checkpoint is
    valid when the raw markdown's mtime is at least as new as the
    source file — editing the source invalidates resume. With
    `current_flags`, a checkpoint the run record says was ingested with
    different settings raises instead (`assert_ingest_flags_match`).

    `source_format` is supplied by the caller (computed from the source
    suffix) so this module doesn't need to import the dispatcher's
    suffix tables, avoiding a circular import.
    """
    if out is None or raw_md_path is None:
        return None
    validator = SnapshotValidator(upstream_files=(src,))
    cached_text = try_resume_from_snapshot(raw_md_path, validator)
    if cached_text is None:
        return None
    if current_flags is not None:
        assert_ingest_flags_match(out, src.suffix.lower(), current_flags)
    images_dir = out / "images"
    images = sorted(images_dir.glob("*")) if images_dir.exists() else []
    return IngestResult(
        markdown=cached_text,
        images=images,
        source_format=source_format,
    )


def _try_resume_from_cleaned(
    out: Path | None,
    raw_md_path: Path | None,
    cleaned_md_path: Path | None,
    current_flags: dict[str, Any],
) -> str | None:
    """Return the cached cleaned markdown when the snapshot is valid for
    the current run, else None.

    vision-cache mtime is no longer checked. Vision injection
    moved out of Phase 3a (cleanup), so vision changes don't invalidate
    cleaned.md anymore.

    Validity rules (all must hold):
    1. cleaned.md exists.
    2. cleaned.md mtime ≥ raw.md mtime (raw didn't change).
    3. cleanup-affecting flags in the previous run.json match the
       current resolved flags.
    """
    if out is None or cleaned_md_path is None or raw_md_path is None:
        return None
    validator = SnapshotValidator(
        upstream_files=(raw_md_path,),
        run_record_path=out / ".pagespeak-run.json",
        flag_keys=_CLEANUP_AFFECTING_FLAGS,
        current_flags=current_flags,
    )
    cached: str | None = try_resume_from_snapshot(cleaned_md_path, validator)
    return cached
