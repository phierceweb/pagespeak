"""Raw-HTML blocks in prose.

Embedded `<table>`, `<figure>` and `<img>` blocks convert to markdown via
`utils._html.html_fragment_to_markdown`: only line-anchored blocks that close
within `_MAX_BLOCK_LINES`, outside fenced code. Tag soup, mid-line tag
mentions, and failed conversions pass through untouched — this pass may never
drop content.

`<script>` and `<style>` blocks render as no text and are dropped; `<pre>` and
`<textarea>` blocks are preformatted and left as written. Both follow
CommonMark's raw-HTML block start (at most 3 spaces of indent) and need a
closing tag.
"""

from __future__ import annotations

import re

from ..utils._html import html_fragment_to_markdown
from ._fences import transform_outside_fences

_BLOCK_OPEN_RE = re.compile(r"^<(table|figure)\b", re.IGNORECASE)
_IMG_LINE_RE = re.compile(r"^<img\b[^>]*>\s*$", re.IGNORECASE)
_MAX_BLOCK_LINES = 400
_SCRIPT_STYLE_OPEN_RE = re.compile(r"^ {0,3}<(script|style)(?=[\s>]|$)", re.IGNORECASE)
_PREFORMATTED_OPEN_RE = re.compile(r"^ {0,3}<(pre|textarea)(?=[\s>]|$)", re.IGNORECASE)


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
    return transform_outside_fences(text, lambda seg: "\n".join(_convert_lines(seg.split("\n"))))


def _closing_line(lines: list[str], start: int, tag: str) -> int | None:
    """Index of the first line from ``start`` holding ``</tag>``, or None."""
    close = f"</{tag.lower()}>"
    return next((j for j in range(start, len(lines)) if close in lines[j].lower()), None)


def _strip_lines(lines: list[str]) -> tuple[list[str], int]:
    lines = list(lines)
    out: list[str] = []
    stripped = 0
    i = 0
    while i < len(lines):
        m = _SCRIPT_STYLE_OPEN_RE.match(lines[i])
        end = _closing_line(lines, i, m.group(1)) if m else None
        if m is None or end is None:
            out.append(lines[i])
            i += 1
            continue
        stripped += 1
        close = f"</{m.group(1).lower()}>"
        tail = lines[end][lines[end].lower().index(close) + len(close) :]
        if tail.strip():
            # Text after the closing tag is visible, and may open the next block.
            lines[end] = tail
            i = end
        else:
            i = end + 1
    return out, stripped


def strip_script_style_blocks(text: str) -> tuple[str, int]:
    """Drop line-anchored `<script>` / `<style>` blocks outside fenced code.

    Returns the text and the number of blocks dropped.
    """
    low = text.lower()
    if "<script" not in low and "<style" not in low:
        return text, 0
    total = 0

    def strip(segment: str) -> str:
        nonlocal total
        lines, n = _strip_lines(segment.split("\n"))
        total += n
        return "\n".join(lines)

    return transform_outside_fences(text, strip), total


def preformatted_block_flags(lines: list[str], fenced: list[bool]) -> list[bool]:
    """True for each line of a closed, line-anchored `<pre>` / `<textarea>` block
    outside fenced code (``fenced`` from `fence_flags`)."""
    flags = [False] * len(lines)
    i = 0
    while i < len(lines):
        m = None if fenced[i] else _PREFORMATTED_OPEN_RE.match(lines[i])
        end = _closing_line(lines, i, m.group(1)) if m else None
        if end is None:
            i += 1
            continue
        flags[i : end + 1] = [True] * (end + 1 - i)
        i = end + 1
    return flags


__all__ = [
    "convert_embedded_html_blocks",
    "preformatted_block_flags",
    "strip_script_style_blocks",
]
