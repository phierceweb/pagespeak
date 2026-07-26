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
from ._fences import fence_flags

_TOC_HEADING_RE = re.compile(r"^\s*#+\s*Table of Contents\s*$", re.IGNORECASE)

# Entries cap at H4 (listing every H5/H6 is noise); the block boundary must not
# — a heading of any depth ends the TOC.
_HEADING_LINE_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# Shapes a contents block is made of: table rows, list entries, leader lines,
# and bare titles ending in a page number.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_LEADER_RE = re.compile(r"[.·_]{3,}|\s\d{1,4}\s*$")
_SENTENCE_RE = re.compile(r"[.!?]\s*$")


def _is_toc_block_line(line: str) -> bool:
    """Whether a line belongs to the contents block rather than the body.

    The block used to run to the next heading, so a manual placing safety copy
    between its contents and the first section had that copy replaced along with
    the table. Prose ends the block; only contents-shaped lines extend it.
    """
    s = line.strip()
    if not s:
        return True
    if _TABLE_ROW_RE.match(s) or _LIST_ITEM_RE.match(s) or _LEADER_RE.search(s):
        return True
    # A short bare title is plausibly an entry; a sentence is body text.
    return len(s.split()) <= 8 and not _SENTENCE_RE.search(s)


def regenerate_toc(markdown: str) -> str:
    """Replace whatever's between the `## Table of Contents` heading and the
    next heading with a bullet list of the document's actual headings.

    No-op if no Table-of-Contents heading is present in the markdown.
    """
    lines = markdown.splitlines()
    fenced = fence_flags(lines)

    toc_idx = next(
        (i for i, line in enumerate(lines) if not fenced[i] and _TOC_HEADING_RE.match(line)),
        None,
    )
    if toc_idx is None:
        return markdown

    # A fence bounds the block too: crossing one swallows a document whose
    # remaining headings all sit inside it. Body prose bounds it as well — see
    # `_is_toc_block_line`.
    block_end = len(lines)
    for i in range(toc_idx + 1, len(lines)):
        if fenced[i] or _ANY_HEADING_RE.match(lines[i]) or not _is_toc_block_line(lines[i]):
            block_end = i
            break
    # don't carry the blank run that preceded the terminator into the new block
    while block_end - 1 > toc_idx and not lines[block_end - 1].strip():
        block_end -= 1
    next_heading_idx = block_end

    entries: list[tuple[int, str, str]] = []  # (depth, title, slug)
    for i in range(next_heading_idx, len(lines)):
        if fenced[i]:
            continue
        line = lines[i]
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
