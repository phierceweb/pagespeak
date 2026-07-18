"""Per-image vision-call cache for resumable single-shot conversion.

Each successful call to a `VisionBackend` is persisted as
`<cache_dir>/<phash>.json` containing the resulting `Diagram` plus the
backend + model that produced it. On a subsequent run, a matching cache
entry is loaded and the live backend call is skipped — letting
`to_markdown()` resume mid-vision after a crash without redoing work.

Cache key is the image's perceptual hash (`compute_phash`), so the same
image at two paths still hits one entry — and the SAME image hits its
cached description on every later run, **regardless of which backend or
model produced it**. A diagram description is a function of the image
(captured by the phash), so switching engines must never silently re-spend
on images already analysed. `backend`/`model` are recorded for provenance
(a human can see which engine made a caption) but are NOT a reuse gate; a
model switch served from cache is surfaced by `warn_on_model_mismatch`,
never acted on.

To force fresh descriptions, delete the cache explicitly — `--rerun-from
vision` or `pagespeak invalidate <dir> vision`. Tinkering with upstream
stages (cleanup / normalize / repair) or re-ingesting PRESERVES and REUSES
this cache; that is the whole point of keying on image content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pf_core.log import get_logger
from pf_core.utils.io import atomic_write_json

from ..models._models import Diagram

logger = get_logger(__name__)


def load(cache_path: Path) -> dict[str, Any] | None:
    """Read a cached diagram JSON if present and parseable.

    The cache key is the filename (the image's perceptual hash), so a
    present, well-formed entry is a hit — REGARDLESS of which backend or
    model produced it. The description is a function of the image; reusing
    it is always correct, and switching engines must not silently re-spend
    on images already analysed. `backend`/`model` recorded by `write()` are
    provenance only, never a reuse gate. To force fresh descriptions, delete
    the cache explicitly (`--rerun-from vision` / `pagespeak invalidate`).

    Cache misses (file absent, JSON unreadable, not a dict) are NEVER
    fatal — they route to the live call and overwrite.
    """
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("vision_cache_unreadable path=%s error=%s", cache_path, e)
        return None
    if not isinstance(data, dict):
        return None
    return dict(data)


def write(
    cache_path: Path,
    *,
    diagram: Diagram,
    backend: str,
    model: str | None,
    phash: str | None = None,
    source_paths: list[str] | None = None,
) -> None:
    """Atomic write of a vision cache JSON. Tmp file in same dir then
    rename, so a crash mid-write can't leave a half-parseable file
    that resume reads as success.

    `phash` and `source_paths` are inspectability metadata only — lookup
    is filename-keyed so they're never read on cache load. Recording
    them lets a human open `<phash>.json` and see which image(s) the
    entry corresponds to without having to recompute every image's
    perceptual hash. Both are optional for backward compat with callers
    that haven't been updated; absent fields just don't appear in the
    JSON.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "phash": phash,
        "backend": backend,
        "model": model,
        "caption": diagram.caption,
        "mermaid": diagram.mermaid,
        "diagram_type": diagram.diagram_type,
        "source_paths": list(source_paths) if source_paths else [],
    }
    atomic_write_json(cache_path, payload)


def warn_on_model_mismatch(
    hit_models: dict[str | None, int],
    *,
    active_model: str | None,
) -> None:
    """One aggregate WARNING when served cache hits were recorded under a
    different model than this run's — e.g. the docs-recommended "switch to a
    stronger model for dense diagrams" on a finished conversion, which is
    100% cache hits and would otherwise change nothing silently. Log-only:
    reuse stays unconditional (see module docstring); `hit_models` maps each
    hit's recorded provenance model → hit count.
    """
    mismatched = {m: n for m, n in hit_models.items() if m != active_model}
    if not mismatched:
        return
    logger.warning(
        "vision_cache_model_mismatch cached=%s active=%s images=%d "
        'hint="--rerun-from vision to re-analyse"',
        ",".join(sorted(str(m) for m in mismatched)),
        active_model,
        sum(mismatched.values()),
    )


def diagram_from_cache(cached: dict[str, Any], image_path: Path) -> Diagram:
    """Reconstruct a `Diagram` from a cache hit's JSON dict."""
    return Diagram(
        image_path=image_path,
        caption=cached.get("caption") or f"Image at {image_path.name}.",
        mermaid=cached.get("mermaid"),
        diagram_type=cached.get("diagram_type"),
    )
