"""Decoration phash dedup: detect repeated page-headers / footers / watermarks.

The cleanup path calls `detect_and_strip_decorations` from
`_dispatch.py`; this module is the single source of truth for the logic.

A "decoration" is a phash cluster holding at least `threshold` images. What
happens to a clustered ref depends on how sure the match is — see
`_strip_decoration_refs`.
"""

from __future__ import annotations

import re
from pathlib import Path

from pf_core.log import get_logger

from ..utils._phash import cluster_phashes, compute_phash
from ._image_refs import ImageRef, replace_image_refs

logger = get_logger(__name__)

DEFAULT_DECORATION_THRESHOLD = 5
DEFAULT_PHASH_HAMMING_DISTANCE = 12
# Small but non-zero: re-encoding one asset perturbs a few bits.
EXACT_DUPLICATE_HAMMING_DISTANCE = 2

_BLANK_LINE_RUN_RE = re.compile(r"\n{3,}")


def _phash_to_basenames(images: list[Path]) -> dict[str, set[str]]:
    """Perceptual hash → the basenames carrying it, hashing each image once.

    Built here rather than via `detect_decoration_basenames` because this pass
    clusters the same hashes at two radii, and re-reading every image for the
    second is the dominant cost. An unreadable image is skipped, not fatal.
    """
    out: dict[str, set[str]] = {}
    for img in images:
        if not img.exists():
            logger.warning("decoration_image_missing path=%s", img)
            continue
        try:
            ph = compute_phash(img)
        except Exception as e:
            logger.warning("decoration_phash_failed path=%s error=%s", img, e)
            continue
        out.setdefault(ph, set()).add(img.name)
    return out


def _clustered_basenames(
    phash_to_basenames: dict[str, set[str]], *, threshold: int, hamming_distance: int
) -> set[str]:
    """Basenames in any cluster of at least `threshold` images at this radius."""
    found: set[str] = set()
    for cluster in cluster_phashes(list(phash_to_basenames), max_distance=hamming_distance):
        if sum(len(phash_to_basenames[ph]) for ph in cluster) >= threshold:
            for ph in cluster:
                found |= phash_to_basenames[ph]
    return found


def _strip_decoration_refs(
    markdown: str,
    decoration_basenames: set[str],
    exact_duplicate_basenames: set[str],
) -> str:
    """Rewrite decoration refs, dropping only what is provably furniture.

    A near-exact duplicate is the same image again, so it goes whatever its alt
    says; anything merely similar keeps its description as an italic caption, or
    is left alone. Collapses the blank-line runs a removal leaves behind.
    See `docs/pipeline-decorations.md`.
    """
    if not decoration_basenames:
        return markdown

    def repl(ref: ImageRef) -> str | None:
        basename = ref.target.rsplit("/", 1)[-1]
        if basename not in decoration_basenames:
            return None
        if basename in exact_duplicate_basenames:
            return ""
        alt = ref.alt.strip()
        # `_append_image_refs` synthesises `![<basename>](…)` for office zips;
        # that alt is the filename, not a description, and protects nothing.
        return f"_{alt}_" if alt and alt != basename else None

    stripped, _ = replace_image_refs(markdown, repl)
    return _BLANK_LINE_RUN_RE.sub("\n\n", stripped)


def detect_and_strip_decorations(
    markdown: str,
    *,
    images: list[Path],
    threshold: int | None = None,
    hamming_distance: int | None = None,
) -> str:
    """Detect decoration phash clusters across `images` and rewrite their refs
    in `markdown` per `_strip_decoration_refs`. Returns markdown unchanged if no
    images, threshold=0, or no clusters meet the threshold."""
    eff_threshold = DEFAULT_DECORATION_THRESHOLD if threshold is None else threshold
    eff_hamming = DEFAULT_PHASH_HAMMING_DISTANCE if hamming_distance is None else hamming_distance
    if not images or eff_threshold <= 0:
        return markdown
    by_phash = _phash_to_basenames(images)
    decorations = _clustered_basenames(
        by_phash, threshold=eff_threshold, hamming_distance=eff_hamming
    )
    if not decorations:
        return markdown
    # Re-clustered near-exact off the same hashes; only these are dropped.
    exact = _clustered_basenames(
        by_phash, threshold=eff_threshold, hamming_distance=EXACT_DUPLICATE_HAMMING_DISTANCE
    )
    logger.info(
        "decorations_detected count=%d exact=%d threshold=%d hamming=%d",
        len(decorations),
        len(exact),
        eff_threshold,
        eff_hamming,
    )
    return _strip_decoration_refs(markdown, decorations, exact)


__all__ = [
    "DEFAULT_DECORATION_THRESHOLD",
    "DEFAULT_PHASH_HAMMING_DISTANCE",
    "EXACT_DUPLICATE_HAMMING_DISTANCE",
    "detect_and_strip_decorations",
]
