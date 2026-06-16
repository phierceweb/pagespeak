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

from pathlib import Path
from typing import Any

from pf_core.pipeline.resume import SnapshotValidator, try_resume_from_snapshot

from ..models._models import IngestResult

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


def _try_resume_from_checkpoint(
    src: Path,
    out: Path | None,
    raw_md_path: Path | None,
    *,
    source_format: str,
) -> IngestResult | None:
    """Reload an in-progress conversion from `<stem>.raw.md` + `images/`.

    Returns a hydrated `IngestResult` if a usable checkpoint exists,
    else `None` (caller runs the backend fresh). The checkpoint is
    valid when the raw markdown's mtime is at least as new as the
    source file — editing the source invalidates resume.

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
