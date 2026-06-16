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

    Detect→correct, not brute-force. The defect — a Word "Multilevel
    List" whose section hierarchy was flattened into list indentation —
    is diagnosed by EITHER fingerprint:

    * a leading **bullet marker-stack** (``* + 1.``, ``* + - * 1.``):
      the MarkItDown/Pandoc/Docling serialization of a Word multilevel
      list (may sit under a real chapter heading); OR
    * an **entirely un-headed numbered outline** — depth-1 numbered
      items at ``h==0`` AND **no** depth-1 item already under a real
      ``#`` heading: the document's whole structure IS the list (pure
      4-space Pandoc output, no markers, no headings). If even one
      depth-1 item is headed, the doc has a real section spine and the
      un-headed items are just a preamble (a "Before you begin" list
      before the first heading) — NOT flattened; reconstructing it
      would cascade the genuine headed sections.

    The python-docx structured reader has **neither**: it writes clean
    ``1.`` / ``  1.`` nested lists that are *always* already under the
    real ``#`` headings it emitted. So reader output (and any
    correctly-structured doc / genuine content list) matches no
    fingerprint and is returned **unchanged** — this function is
    structurally incapable of "promoting" a list that isn't a
    flattened Word outline.

    Returns ``(rewritten_text, promoted_count)`` (``promoted_count``
    drives the caller's ``is_outline_doc`` flag). Returns ``(text, 0)``
    when neither fingerprint is present, or < 3 depth-1 items, or no
    deeper item — a flat/short sequence or a non-flattened doc.
    """
    lines = text.splitlines()

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
    has_marker_stack = False
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
        m = LIST_LINE_RE.match(line)
        if m is None:
            pass_lines[idx] = line
            continue
        if m.group("markers"):
            # The MarkItDown/Pandoc/Docling Word-multilevel-list
            # fingerprint. The python-docx reader never emits it.
            has_marker_stack = True
        col = len(m.group("markers")) + len(m.group("indent"))
        while stack and col < stack[-1]:
            stack.pop()
        if not stack or col > stack[-1]:
            stack.append(col)
        depth = len(stack)
        list_items.append((idx, h_level, depth, m.group("num"), m.group("content")))

    # Diagnosis: a flattened Word outline shows EITHER a marker-stack OR a
    # numbered outline that is *entirely* un-headed (depth-1 items at h==0
    # AND no depth-1 item already under a real `#`). If any depth-1 item is
    # headed, the doc has a real section spine and the un-headed items are
    # just a preamble (e.g. a "Before you begin" list) — reconstructing
    # would shred it. The reader's normal output has neither fingerprint;
    # depth guards then reject a flat/short ordered list.
    unheaded_d1 = any(h == 0 and d == 1 for _, h, d, _, _ in list_items)
    headed_d1 = any(h >= 1 and d == 1 for _, h, d, _, _ in list_items)
    has_unheaded_outline = unheaded_d1 and not headed_d1
    depth1 = sum(1 for _, _, d, _, _ in list_items if d == 1)
    deeper = any(d >= 2 for _, _, d, _, _ in list_items)
    if (not has_marker_stack and not has_unheaded_outline) or depth1 < 3 or not deeper:
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
