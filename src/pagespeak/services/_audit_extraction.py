"""Audit checks for extraction damage a backend leaves at exit 0.

Whole-document signatures, run on the master file (a section of one-line
shell commands is ordinary):

- `collapsed_code_blocks` — every fenced code block is one line. A backend
  that flattens code (Docling does) keeps the fence count and loses the
  lines, so a copied command is unusable. Mermaid fences don't count.
- `unclosed_code_fence` — a fence opened and never closed: everything after
  it renders as code, and every fence-aware pass skips it.
- `formula_glyph_codes` — formulas rendered as glyph-code tokens (`n01`,
  `n2a`) instead of math, at a density prose never reaches.
"""

from __future__ import annotations

import re

from ._audit_checks import AuditFinding
from ._fences import fence_flags, fenced_blocks

_COLLAPSED_MIN_BLOCKS = 8  # fewer one-line blocks is ordinary inline-sized code

_GLYPH_RE = re.compile(r"\bn(?:\d[0-9a-f]|[0-9a-f]\d)\b")
_WORD_RE = re.compile(r"\w+")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_GLYPH_MIN = 5
_GLYPH_PER_1K_WORDS = 1.0


def _code_block_lengths(lines: list[str]) -> list[tuple[int, int]]:
    """`(opening line number, content line count)` per closed, non-Mermaid block."""
    return [
        (b.start + 1, b.end - b.start - 1)
        for b in fenced_blocks(lines)
        if b.end is not None and not b.info.lower().startswith("mermaid")
    ]


def check_collapsed_code_blocks(text: str) -> list[AuditFinding]:
    blocks = _code_block_lengths(text.splitlines())
    if len(blocks) < _COLLAPSED_MIN_BLOCKS or any(n != 1 for _, n in blocks):
        return []
    return [
        AuditFinding(
            check="collapsed_code_blocks",
            severity="warning",
            line=blocks[0][0],
            message=(
                f"all {len(blocks)} fenced code blocks are one line — multi-line code "
                "collapsed by the backend (Docling does this), or non-code text fenced"
            ),
        )
    ]


def check_unclosed_code_fence(text: str) -> list[AuditFinding]:
    lines = text.splitlines()
    blocks = fenced_blocks(lines)
    k = next((k for k, b in enumerate(blocks) if b.end is None), None)
    if k is None:
        return []
    opened_at = blocks[k].start + 1
    if k + 1 < len(blocks):
        message = (
            f"code fence never closed — read as ending where the next fence opens "
            f"(line {blocks[k + 1].start + 1}); the source likely lost a closing fence"
        )
    else:
        message = (
            f"code fence never closed — the remaining {len(lines) - opened_at} "
            "line(s) render as code and are skipped by every fence-aware pass"
        )
    return [
        AuditFinding(
            check="unclosed_code_fence", severity="warning", line=opened_at, message=message
        )
    ]


def check_formula_glyph_codes(text: str) -> list[AuditFinding]:
    lines = text.splitlines()
    prose = [
        _INLINE_CODE_RE.sub(" ", line)
        for line, fenced in zip(lines, fence_flags(lines), strict=True)
        if not fenced
    ]
    joined = "\n".join(prose)
    hits = _GLYPH_RE.findall(joined)
    words = len(_WORD_RE.findall(joined))
    if len(hits) < _GLYPH_MIN or not words or 1000 * len(hits) / words < _GLYPH_PER_1K_WORDS:
        return []
    return [
        AuditFinding(
            check="formula_glyph_codes",
            severity="warning",
            line=1,
            message=(
                f"{len(hits)} glyph-code tokens (e.g. {hits[0]}) — formulas were not "
                "recovered; use Marker, or Docling with do_formula_enrichment"
            ),
        )
    ]


def run_extraction_checks(text: str) -> list[AuditFinding]:
    return [
        *check_collapsed_code_blocks(text),
        *check_unclosed_code_fence(text),
        *check_formula_glyph_codes(text),
    ]
