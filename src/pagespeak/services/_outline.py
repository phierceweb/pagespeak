"""Word multilevel-list → heading/list structure (Phase-3 cleanup pre-pass).

MarkItDown / Pandoc / Docling convert Word's "Multilevel List" feature
to nested numbered markdown lists with a bullet-wrapper marker stack on
the first item of each (sub)list (`* + 1.`, `* + - * 1.`); siblings and
children are space-indented. To markdown-aware tools that is zero
headings. This module reconstructs the indent/marker-encoded hierarchy
into real headings (top `MAX_HEADING_LEVELS` levels) plus a clean nested
markdown list (deeper), so the splitter yields retrievable sections.

Pure text, deterministic, $0. Handles marker-prefixed first items,
keeps marker stacks out of body text, and levels siblings correctly on
irregular indents.
"""

from __future__ import annotations

import re

from ._fences import fence_flags

# Optional leading marker stack (`* `, `* + `, `* + - * `), then the
# residual space indent, then `N. content`. The `markers` group lets the
# pattern match a marker-prefixed first item like `* + 1.`.
LIST_LINE_RE = re.compile(
    r"^(?P<markers>(?:[*+\-]\s+)*)(?P<indent>\s*)(?P<num>\d+)\.\s+(?P<content>\S.*)$"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")

# Promote at most this many list levels to headings; deeper levels are
# re-emitted as a normalized nested markdown list. Fixed, no config —
# a leaf bullet must never become an H6 heading.
MAX_HEADING_LEVELS = 2
MAX_HEADING_DEPTH = 6  # markdown ATX cap


def _enclosing_heading_level(line: str) -> int | None:
    """ATX depth of a `#`-prefixed heading line (1–6), else None."""
    m = _HEADING_RE.match(line)
    return len(m.group(1)) if m else None


def promote_outline(text: str) -> tuple[str, int]:
    """Reconstruct a flattened Word multilevel-list outline.

    Fires only when most of the document's bullet marker stacks are
    wrappers (``* + 1.``, ``* + - * 1.``): how MarkItDown/Pandoc/Docling
    serialize a Word multilevel list. A wrapper sits on a nested list's
    first item, which MarkItDown numbers 1; a stacked item numbered
    otherwise (``* 3. Setup``) is a bullet whose text starts with a number.
    The python-docx reader never emits a stack. Lists that start at the
    outline's top level carry none, so the wrappers mark the whole
    document. Without them, a nested numbered list stays a list, headed
    document or not — promoted, its items would become body-less headings
    that the splitter drops.

    Returns ``(rewritten_text, promoted_count)`` (``promoted_count``
    drives the caller's ``is_outline_doc`` flag). Returns ``(text, 0)``
    unless wrappers outnumber the other stacked items, or with < 3
    depth-1 items or no deeper item.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)

    # Pass 1: classify.
    # pass_lines: raw lines to emit unchanged, keyed by index.
    # list_items: (index, h_level, depth, num, content).
    # `H` = enclosing Word-style heading level, frozen per list line.
    # `stack` holds the column of each open relative level; reset at
    # every real `#` heading and blank line (block boundaries).
    pass_lines: dict[int, str] = {}
    list_items: list[tuple[int, int, int, str, str]] = []
    h_level = 0
    stack: list[int] = []
    wrappers = 0
    numbered_bullets = 0
    for idx, line in enumerate(lines):
        hl = _enclosing_heading_level(line)
        if hl is not None:
            h_level = hl
            stack = []
            pass_lines[idx] = line
            continue
        if line.strip() == "":
            stack = []
            pass_lines[idx] = line
            continue
        m = None if _fenced[idx] else LIST_LINE_RE.match(line)
        if m is None:
            pass_lines[idx] = line
            continue
        if m.group("markers"):
            if m.group("num") == "1":
                wrappers += 1
            else:
                numbered_bullets += 1
        col = len(m.group("markers")) + len(m.group("indent"))
        while stack and col < stack[-1]:
            stack.pop()
        if not stack or col > stack[-1]:
            stack.append(col)
        depth = len(stack)
        list_items.append((idx, h_level, depth, m.group("num"), m.group("content")))

    depth1 = sum(1 for _, _, d, _, _ in list_items if d == 1)
    deeper = any(d >= 2 for _, _, d, _, _ in list_items)
    if wrappers <= numbered_bullets or depth1 < 3 or not deeper:
        return text, 0

    # Pass 2: render — reconstruct in original line order.
    list_map: dict[int, tuple[int, int, str, str]] = {
        idx: (h, depth, num, content) for idx, h, depth, num, content in list_items
    }
    out: list[str] = []
    promoted = 0
    for idx in range(len(lines)):
        if idx in pass_lines:
            out.append(pass_lines[idx])
        else:
            h, depth, num, content = list_map[idx]
            if depth <= MAX_HEADING_LEVELS:
                level = min(h + depth, MAX_HEADING_DEPTH)
                out.append("#" * level + " " + num + ". " + content)
                promoted += 1
            else:
                indent = "  " * (depth - MAX_HEADING_LEVELS - 1)
                out.append(indent + "- " + num + ". " + content)

    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, promoted
