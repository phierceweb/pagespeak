"""Decoration phash dedup: detect repeated page-headers / footers / watermarks.

The cleanup path calls `detect_and_strip_decorations` from
`_dispatch.py`; this module is the single source of truth for the logic.

A "decoration" is a phash cluster holding at least `threshold` images. What
happens to a clustered ref depends on how sure the match is — see
`_strip_decoration_refs`.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from PIL import Image
from pw_foundation.log import get_logger
from pw_foundation.utils.env import resolve_int

from ..utils._phash import cluster_phashes, compute_phash
from ._image_refs import ImageRef, parse_image_refs, ref_file_names, replace_image_refs
from ._verify_captions import describes_picture

logger = get_logger(__name__)

DEFAULT_DECORATION_THRESHOLD = 5
DEFAULT_PHASH_HAMMING_DISTANCE = 12
# Small but non-zero: re-encoding one asset perturbs a few bits.
EXACT_DUPLICATE_HAMMING_DISTANCE = 2

_KEEP_MIN_PX_DEFAULT = 200
_KEEP_MIN_PX_ENV_VAR = "PAGESPEAK_DECORATION_KEEP_MIN_PX"
_KEEP_MAX_USES_DEFAULT = 2
_KEEP_MAX_USES_ENV_VAR = "PAGESPEAK_DECORATION_KEEP_MAX_USES"

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


def _look_alike_groups(
    phash_to_basenames: dict[str, set[str]], *, threshold: int, hamming_distance: int
) -> list[set[str]]:
    """The basenames of each cluster of at least `threshold` images at this radius."""
    clusters = cluster_phashes(list(phash_to_basenames), max_distance=hamming_distance)
    return _large_clusters(phash_to_basenames, clusters, threshold=threshold)


def _large_clusters(
    phash_to_basenames: dict[str, set[str]], clusters: list[set[str]], *, threshold: int
) -> list[set[str]]:
    groups = ({n for ph in cluster for n in phash_to_basenames[ph]} for cluster in clusters)
    return [names for names in groups if len(names) >= threshold]


def _ref_name(ref: ImageRef, names: set[str]) -> str | None:
    """The file in `names` a ref points at, if any."""
    return next((n for n in ref_file_names(ref.target) if n in names), None)


def _is_large(path: Path, min_px: int) -> bool:
    try:
        with Image.open(path) as im:
            width, height = im.size
    except (OSError, ValueError):
        return False
    return width >= min_px and height >= min_px


def _label_key(alt: str) -> str:
    return " ".join(alt.split()).casefold()


def _distinct_pictures(
    markdown: str,
    groups: list[set[str]],
    exact: set[str],
    *,
    phash_to_basenames: dict[str, set[str]],
    exact_clusters: list[set[str]],
    paths: dict[str, Path],
    threshold: int,
) -> set[str]:
    """Look-alikes that are large and whose near-exact copies the text uses at most a few times.

    Uses are counted over every ref to any near-exact copy, so one picture saved
    as a file per page counts once per page. A description (case and spacing aside)
    that `threshold` or more refs in the picture's own look-alike group share labels
    furniture, however far apart the copies hash; a filler label does not count.
    """
    max_uses = resolve_int(None, _KEEP_MAX_USES_ENV_VAR, default=_KEEP_MAX_USES_DEFAULT)
    min_px = resolve_int(None, _KEEP_MIN_PX_ENV_VAR, default=_KEEP_MIN_PX_DEFAULT)
    group_of = {name: i for i, group in enumerate(groups) for name in group}
    candidates = set(group_of) - exact
    if not candidates or max_uses <= 0:
        return set()
    look_alikes = set(group_of)
    refs = [(r, _ref_name(r, look_alikes)) for r in parse_image_refs(markdown)]
    named = [(r, name) for r, name in refs if name is not None]
    refs_per_name = Counter(name for _, name in named)
    shared = Counter((group_of[name], _label_key(r.alt)) for r, name in named)
    alt_of = {name: r.alt.strip() for r, name in reversed(named)}
    uses: dict[str, int] = {}
    for cluster in exact_clusters:
        names = {n for ph in cluster for n in phash_to_basenames[ph]}
        total = sum(refs_per_name[n] for n in names)
        uses.update(dict.fromkeys(names, total))

    def furniture_label(name: str) -> bool:
        alt = alt_of.get(name, "")
        return describes_picture(alt) and shared[(group_of[name], _label_key(alt))] >= threshold

    return {
        name
        for name in candidates
        if uses.get(name, refs_per_name[name]) <= max_uses
        and not furniture_label(name)
        and name in paths
        and _is_large(paths[name], min_px)
    }


def _strip_decoration_refs(
    markdown: str,
    decoration_basenames: set[str],
    exact_duplicate_basenames: set[str],
    distinct_basenames: frozenset[str] | set[str] = frozenset(),
) -> str:
    """Rewrite decoration refs, dropping only what is provably furniture.

    A near-exact duplicate is the same image again, so it goes whatever its alt
    says; a large picture used once or twice under its own description (`distinct_basenames`) is kept;
    anything else merely similar keeps its description as an italic caption, or
    is left alone. Collapses the blank-line runs a removal leaves behind.
    See `docs/pipeline-decorations.md`.
    """
    if not decoration_basenames:
        return markdown

    def repl(ref: ImageRef) -> str | None:
        basename = _ref_name(ref, decoration_basenames)
        if basename is None:
            return None
        if basename in exact_duplicate_basenames:
            return ""
        if basename in distinct_basenames:
            return None
        alt = ref.alt.strip()
        # `_append_image_refs` synthesises `![<basename>](…)` for office zips;
        # that alt is the filename, not a description, and protects nothing.
        return f"_{alt}_" if alt and alt not in ref_file_names(ref.target) else None

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
    groups = _look_alike_groups(by_phash, threshold=eff_threshold, hamming_distance=eff_hamming)
    decorations = set().union(*groups)
    if not decorations:
        return markdown
    # Re-clustered near-exact off the same hashes; only these are dropped.
    exact_clusters = cluster_phashes(list(by_phash), max_distance=EXACT_DUPLICATE_HAMMING_DISTANCE)
    exact = set().union(*_large_clusters(by_phash, exact_clusters, threshold=eff_threshold))
    distinct = _distinct_pictures(
        markdown,
        groups,
        exact,
        phash_to_basenames=by_phash,
        exact_clusters=exact_clusters,
        paths={p.name: p for p in images},
        threshold=eff_threshold,
    )
    logger.info(
        "decorations_detected count=%d exact=%d kept_distinct=%d threshold=%d hamming=%d",
        len(decorations),
        len(exact),
        len(distinct),
        eff_threshold,
        eff_hamming,
    )
    return _strip_decoration_refs(markdown, decorations, exact, distinct)


__all__ = [
    "DEFAULT_DECORATION_THRESHOLD",
    "DEFAULT_PHASH_HAMMING_DISTANCE",
    "EXACT_DUPLICATE_HAMMING_DISTANCE",
    "detect_and_strip_decorations",
]
