"""Decoration phash dedup: detect repeated page-headers / footers / watermarks.

The cleanup path calls `detect_and_strip_decorations` from
`_dispatch.py`; this module is the single source of truth for the logic.

A "decoration" is a phash cluster whose total `source_paths` count meets
`threshold`. The detector strips `![...](images/<basename>)` refs whose
basename is in any such cluster.
"""

from __future__ import annotations

import re
from pathlib import Path

from pf_core.log import get_logger

from ..utils._phash import detect_decoration_basenames

logger = get_logger(__name__)

DEFAULT_DECORATION_THRESHOLD = 5
DEFAULT_PHASH_HAMMING_DISTANCE = 12

_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_BLANK_LINE_RUN_RE = re.compile(r"\n{3,}")


def _strip_decoration_refs(markdown: str, decoration_basenames: set[str]) -> str:
    """Remove `![alt](path)` refs whose basename is a known decoration.
    Collapses resulting blank-line runs."""
    if not decoration_basenames:
        return markdown

    def repl(match: re.Match[str]) -> str:
        path = match.group(1)
        basename = path.rsplit("/", 1)[-1]
        return "" if basename in decoration_basenames else match.group(0)

    stripped = _IMAGE_REF_RE.sub(repl, markdown)
    return _BLANK_LINE_RUN_RE.sub("\n\n", stripped)


def detect_and_strip_decorations(
    markdown: str,
    *,
    images: list[Path],
    threshold: int | None = None,
    hamming_distance: int | None = None,
) -> str:
    """Detect decoration phash clusters across `images`, strip their refs
    from `markdown`. Returns markdown unchanged if no images, threshold=0,
    or no clusters meet the threshold."""
    eff_threshold = DEFAULT_DECORATION_THRESHOLD if threshold is None else threshold
    eff_hamming = DEFAULT_PHASH_HAMMING_DISTANCE if hamming_distance is None else hamming_distance
    if not images or eff_threshold <= 0:
        return markdown
    decorations = detect_decoration_basenames(
        images,
        threshold=eff_threshold,
        hamming_distance=eff_hamming,
    )
    if not decorations:
        return markdown
    logger.info(
        "decorations_detected count=%d threshold=%d hamming=%d",
        len(decorations),
        eff_threshold,
        eff_hamming,
    )
    return _strip_decoration_refs(markdown, decorations)


__all__ = [
    "DEFAULT_DECORATION_THRESHOLD",
    "DEFAULT_PHASH_HAMMING_DISTANCE",
    "detect_and_strip_decorations",
]
