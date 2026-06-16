"""Degrade dangling local image refs to their alt text.

Complementary to the vision pass: vision resolves image refs whose files
exist (analyse them, embed Mermaid/captions); this rewrites refs whose
LOCAL target is missing on disk into their alt text, so the RAG-usable
description survives instead of a broken `![alt](missing)` link.

Mirrors the audit's `dangling_image_ref` rule exactly (local, non-empty
target that does not exist relative to `base_dir`). External `http`/`data`
refs resolve on their own and are left untouched.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

_IMG_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
_EXTERNAL_SCHEMES = ("http://", "https://", "data:")


def degrade_missing_image_refs(text: str, *, base_dir: Path | None) -> tuple[str, int]:
    """Rewrite each `![alt](target)` whose local target is missing on disk.

    Non-empty alt becomes an italic caption `_alt_`; an empty-alt ref is
    dropped. External refs, refs whose target exists, and — when `base_dir`
    is None — all refs are left unchanged. Idempotent (a degraded caption
    carries no `![…](…)` to match again).

    Returns `(rewritten_text, degraded_count)`.
    """
    if base_dir is None:
        return text, 0
    count = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal count
        alt = match.group(1).strip()
        target = match.group(2).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if target.startswith(_EXTERNAL_SCHEMES) or not target:
            return match.group(0)
        # A `%`-encoded target (`My%20Fig.png`) resolves to its decoded file
        # (`My Fig.png`) — check both so a real image isn't wrongly degraded.
        if (base_dir / target).exists() or (base_dir / unquote(target)).exists():
            return match.group(0)
        count += 1
        return f"_{alt}_" if alt else ""

    return _IMG_REF_RE.sub(_repl, text), count
