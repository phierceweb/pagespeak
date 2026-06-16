"""Chunk-worker output rewriting: basename prefixing + page-anchor absolutization.

When a multi-page PDF is split into N chunks and fed to Marker/docling, each
chunk's backend sees its slice as a standalone document numbered from page 1.
That produces two collisions when chunks are flattened into a single output
dir:

1. **Image basenames collide.** Chunk 0 (source pages 1-50) and chunk 1
   (source pages 51-100) both produce `_page_3_Figure_1.jpeg` because each
   chunk's "page 3" is local. Flattening drops one of them.

2. **Page-anchor IDs collide.** Marker emits `<span id="page-3-2">` for the
   first heading on its local page 3. After concat, multiple `id="page-3-2"`
   exist in one document; cross-refs `[label](#page-3-2)` from chunk B may
   resolve to chunk A's target.

This module rewrites both at the chunk-worker boundary (post-backend,
pre-write) so chunks are stored on disk in absolute-page form. The
rewriting is pure-function string manipulation; no I/O.
"""

from __future__ import annotations

import re

_IMAGE_REF_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")
_PAGE_ID_RE = re.compile(r'(id=")page-(\d+)-(\d+)(")')
_PAGE_REF_RE = re.compile(r"(\(#)page-(\d+)-(\d+)(\))")


def prefix_image_basenames(markdown: str, *, page_range: str) -> tuple[str, dict[str, str]]:
    """Prefix every `![...](images/<basename>)` ref's basename with
    `<page_range>-`. Returns the rewritten markdown plus the
    `old_basename → new_basename` map (used by the worker to rename
    the actual image files on disk).

    Only operates on refs whose path lives under `images/`. Other paths
    (URLs, HTML, real cross-doc refs) are untouched. Subdirectories
    inside `images/` are preserved — e.g. `images/sub/foo.png` becomes
    `images/sub/<page_range>-foo.png`.
    """
    renames: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        prefix, path, suffix = match.group(1), match.group(2), match.group(3)
        if not path.startswith("images/"):
            return match.group(0)
        dir_part, _, old_basename = path.rpartition("/")
        new_basename = f"{page_range}-{old_basename}"
        renames[old_basename] = new_basename
        return f"{prefix}{dir_part}/{new_basename}{suffix}"

    rewritten = _IMAGE_REF_RE.sub(repl, markdown)
    return rewritten, renames


def rewrite_anchor_ids_to_absolute(markdown: str, *, page_offset: int) -> str:
    """Rewrite `<span id="page-X-Y">` and `[label](#page-X-Y)` so X
    becomes `X + page_offset`. Zero offset returns unchanged.

    Raises:
        ValueError: if page_offset is negative (would produce invalid IDs).
    """
    if page_offset < 0:
        raise ValueError(f"page_offset must be >= 0, got {page_offset!r}")
    if page_offset == 0:
        return markdown

    def _offset(match: re.Match[str]) -> str:
        g = match.groups()
        return f"{g[0]}page-{int(g[1]) + page_offset}-{g[2]}{g[3]}"

    rewritten = _PAGE_ID_RE.sub(_offset, markdown)
    rewritten = _PAGE_REF_RE.sub(_offset, rewritten)
    return rewritten


__all__ = [
    "prefix_image_basenames",
    "rewrite_anchor_ids_to_absolute",
]
