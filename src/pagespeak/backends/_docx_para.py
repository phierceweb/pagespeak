"""What the python-docx reader reads off a paragraph: its `Heading N` level,
its style, its own left indent, and the indent-driven list depth; and whether a
document has any heading at all."""

from __future__ import annotations

import re
from typing import Any

from docx.oxml.ns import qn

from ._docx_numpr import paragraph_numbering
from ._docx_walk import iter_body

# Only a genuine `Heading N` paragraph style. Word's `Title` is the
# document-title style, NOT a section heading — it can appear on outline
# paragraphs as noise, and real Title-marked sections are always also at
# outline ilvl0 (which is the heading signal that covers them).
_HEADING_STYLE_RE = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    m = _HEADING_STYLE_RE.match(style_name.strip())
    if not m:
        return None
    return min(int(m.group(1)), 6)


def _para_style(paragraph: Any) -> Any:
    try:
        return paragraph.style
    except (KeyError, ValueError):
        return None


def _doc_has_heading(document: Any) -> bool:
    """True if the body contains any real heading (numbered outline or
    ``Heading*`` style). Title promotion only fires when one exists."""
    for item in iter_body(document):
        if item.kind == "table":
            continue
        style = _para_style(item.obj)
        if _heading_level(style.name if style else None) is not None:
            return True
        if paragraph_numbering(item.obj, style) is not None:
            return True
    return False


def _para_left_twips(paragraph: Any) -> int | None:
    """The paragraph's OWN left indent in twips (``w:pPr/w:ind/@w:left``)
    — the direct override Word stores. ``None`` when absent (caller
    falls back to the numbering-level indent, then to ilvl)."""
    ppr = paragraph._p.pPr
    if ppr is None:
        return None
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        return None
    left = ind.get(qn("w:left"))
    if left is None:
        return None
    try:
        return int(left)
    except ValueError:
        return None


def _indent_depth(stack: list[int], left_twips: int) -> int:
    """Relative markdown nesting depth from RESOLVED LEFT INDENT — the
    dimension Word actually lays the visual outline out by (consistent
    across numIds, unlike per-numId ``ilvl``). Monotonic stack of
    indents: shallower pops, deeper pushes, equal is a sibling.
    Mutates ``stack``; returns the new depth (``len(stack) - 1``)."""
    while len(stack) > 1 and left_twips < stack[-1]:
        stack.pop()
    if not stack or left_twips > stack[-1]:
        stack.append(left_twips)
    else:  # equal (sibling) — or the single base level
        stack[-1] = left_twips
    return len(stack) - 1
