"""Generate a clean Table of Contents from extracted headings.

Marker emits TOCs as pipe tables, but on real-world PDFs those tables are
structurally broken (cell boundaries split words mid-character: `ARCHIT` |
`ECTURE`, `DATA` | `BASE`, etc.). Re-deriving the TOC from the headings the
parser already extracted produces a markdown bullet list that's both
human-readable and machine-parseable.

This is a stitch-time concern — it needs the whole document to walk every
heading. Lives in its own module so `_stitch.py` stays under budget.
"""

from __future__ import annotations

import re

from ._cleanup import heading_slug

_TOC_HEADING_RE = re.compile(r"^\s*#+\s*Table of Contents\s*$", re.IGNORECASE)
_HEADING_LINE_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


def regenerate_toc(markdown: str) -> str:
    """Replace whatever's between the `## Table of Contents` heading and the
    next heading with a bullet list of the document's actual headings.

    No-op if no Table-of-Contents heading is present in the markdown.
    """
    lines = markdown.splitlines()

    toc_idx = next(
        (i for i, line in enumerate(lines) if _TOC_HEADING_RE.match(line)),
        None,
    )
    if toc_idx is None:
        return markdown

    # Boundary: next heading line after the TOC heading.
    next_heading_idx = next(
        (i for i in range(toc_idx + 1, len(lines)) if _HEADING_LINE_RE.match(lines[i])),
        len(lines),
    )

    entries: list[tuple[int, str, str]] = []  # (depth, title, slug)
    for line in lines[next_heading_idx:]:
        m = _HEADING_LINE_RE.match(line)
        if not m:
            continue
        title = m.group(2).strip().rstrip("*").strip()
        if not title or _TOC_HEADING_RE.match(line):
            continue
        entries.append((len(m.group(1)), title, heading_slug(line)))

    # Indent relative to the SHALLOWEST heading present, so a doc whose top
    # heading is H2 (no H1) still renders a flat top-level list rather than one
    # nested under a nonexistent H1.
    min_depth = min((d for d, _, _ in entries), default=1)
    bullets: list[str] = []
    for depth, title, slug in entries:
        indent = "  " * (depth - min_depth)
        if slug:
            bullets.append(f"{indent}- [{title}](#{slug})")
        else:
            bullets.append(f"{indent}- {title}")

    new_block: list[str] = ["## Table of Contents", ""]
    if bullets:
        new_block.extend(bullets)
        new_block.append("")

    return "\n".join(lines[:toc_idx] + new_block + lines[next_heading_idx:])
