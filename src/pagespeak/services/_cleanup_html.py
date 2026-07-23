"""Convert embedded raw-HTML blocks in prose (`<table>`, `<figure>`, `<img>`)
to markdown via `utils._html.html_fragment_to_markdown`.

Narrow by design: only line-anchored blocks that close within
`_MAX_BLOCK_LINES`, outside fenced code. Tag soup, mid-line tag mentions, and
failed conversions pass through untouched — this pass may never drop content.
"""

from __future__ import annotations

import re

from ..utils._html import html_fragment_to_markdown

_FENCE_SPLIT_RE = re.compile(r"(^```.*?^```[ \t]*$)", re.M | re.S)
_BLOCK_OPEN_RE = re.compile(r"^<(table|figure)\b", re.IGNORECASE)
_IMG_LINE_RE = re.compile(r"^<img\b[^>]*>\s*$", re.IGNORECASE)
_MAX_BLOCK_LINES = 400


def _convert_block(block: list[str], tag: str) -> list[str]:
    """Markdown replacement for one balanced block, or the block unchanged."""
    converted = html_fragment_to_markdown("\n".join(block))
    if not converted.strip():
        return block
    if tag == "table" and "|" not in converted:
        return block
    return converted.splitlines()


def _convert_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        m = _BLOCK_OPEN_RE.match(stripped)
        if m:
            tag = m.group(1).lower()
            close = f"</{tag}>"
            depth = 0
            end = None
            for j in range(i, min(i + _MAX_BLOCK_LINES, len(lines))):
                low = lines[j].lower()
                depth += low.count(f"<{tag}")
                depth -= low.count(close)
                if depth <= 0:
                    end = j
                    break
            if end is not None:
                out.extend(_convert_block(lines[i : end + 1], tag))
                i = end + 1
                continue
        elif _IMG_LINE_RE.match(stripped):
            out.extend(_convert_block([lines[i]], "img"))
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def convert_embedded_html_blocks(text: str) -> str:
    """Convert line-anchored `<table>`/`<figure>`/`<img>` blocks to markdown,
    outside fenced code."""
    if (
        "<table" not in text.lower()
        and "<figure" not in text.lower()
        and "<img" not in text.lower()
    ):
        return text
    parts = _FENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2:  # fenced block — verbatim
            out.append(part)
        else:
            out.append("\n".join(_convert_lines(part.split("\n"))))
    return "".join(out)


__all__ = ["convert_embedded_html_blocks"]
