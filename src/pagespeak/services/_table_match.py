"""Marker's markdown tables as blocks, and the Docling table on a page that
matches one: content overlap scored both ways, a candidate that drops a value
the original had skipped. `_table_repair` splices what this matches.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ._fences import fence_flags
from ._table_cells import split_table_row
from ._table_words import _BR_RE

_TOKEN_RE = re.compile(r"[A-Za-z0-9.]+")
MEGA_CELL_MIN = 30  # <br> in one cell marking a collapse (matches the audit)
_MATCH_MIN_OVERLAP = 0.5  # token overlap to accept a Docling table as the match
# Cap candidate pages tried per cell — bounds Docling cost if a snippet recurs widely.
_MAX_LOCATE_PAGES = 12
# Content-preservation guard: reject a Docling candidate that silently OMITS a
# substantial value the original had. One dropped row barely moves token-set
# overlap, so judge per-value on bigrams — a dropped value's word-pairs vanish.
_VALUE_MIN_BIGRAMS = 4  # a value with >=4 token-bigrams is substantial enough to judge
_VALUE_PRESERVED_MIN = 0.5  # a substantial value keeping <50% of its bigrams was dropped


@dataclass(frozen=True)
class TableBlock:
    """A contiguous run of markdown table lines (`|`-prefixed)."""

    start: int  # 0-based first line, inclusive
    end: int  # 0-based last line, inclusive
    text: str


def _fenced_line_indices(lines: list[str]) -> set[int]:
    """0-based indices of lines inside a fence, delimiters included.

    A pipe table inside a fence is example markup, never a repair candidate.
    """
    return {i for i, is_fenced in enumerate(fence_flags(lines)) if is_fenced}


def _markdown_table_blocks(text: str) -> list[TableBlock]:
    """Maximal contiguous runs of `|`-prefixed lines (a table + its empty rows),
    outside fenced code."""
    lines = text.splitlines()
    fenced = _fenced_line_indices(lines)
    blocks: list[TableBlock] = []
    start: int | None = None
    for i, line in enumerate(lines):
        is_table = i not in fenced and line.strip().startswith("|")
        if is_table and start is None:
            start = i
        elif not is_table and start is not None:
            blocks.append(TableBlock(start, i - 1, "\n".join(lines[start:i])))
            start = None
    if start is not None:
        blocks.append(TableBlock(start, len(lines) - 1, "\n".join(lines[start:])))
    return blocks


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(_BR_RE.sub(" ", s)) if len(t) > 1}


def _table_overlap(cell_text: str, table_text: str) -> float:
    """Fraction of the mega-cell's distinctive tokens present in a candidate
    table — the matcher's content-similarity score."""
    ct = _tokens(cell_text)
    if not ct:
        return 0.0
    return len(ct & _tokens(table_text)) / len(ct)


def _token_list(s: str) -> list[str]:
    """Ordered distinctive tokens (bigram form of `_tokens`, which is the set)."""
    return [t.lower() for t in _TOKEN_RE.findall(_BR_RE.sub(" ", s)) if len(t) > 1]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:], strict=False))  # uneven slices → stop at shorter


def _cell_values(text: str) -> list[str]:
    """Each non-divider cell value of a table block (or `<br>`-segment of a raw
    mega-cell) — the units a Docling re-extraction could silently drop."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|"):
            out.extend(c.strip() for c in split_table_row(s) if c.strip() and "---" not in c)
        elif _BR_RE.search(s):
            out.extend(seg.strip() for seg in _BR_RE.split(s) if seg.strip())
    return out


def _drops_content(original: str, candidate: str) -> bool:
    """True when `candidate` OMITS a substantial value `original` had — that
    value's word-pairs are largely absent. Catches a silently dropped row that
    token-set overlap misses (the dropped row's unique tokens are a small
    fraction of the table, so the set overlap stays above the floor)."""
    cand_bigrams = _bigrams(_token_list(candidate))
    for value in _cell_values(original):
        vb = _bigrams(_token_list(value))
        if len(vb) < _VALUE_MIN_BIGRAMS:
            continue
        if len(vb & cand_bigrams) / len(vb) < _VALUE_PRESERVED_MIN:
            return True
    return False


def _is_collapsed(table_text: str) -> bool:
    return any(
        len(_BR_RE.findall(c)) >= MEGA_CELL_MIN
        for line in table_text.splitlines()
        for c in split_table_row(line)
    )


def _best_table_match(cell_text: str, docling_md: str) -> tuple[str, float] | None:
    """The Docling table on the page that best matches `cell_text`, scored by
    SYMMETRIC token overlap (the MIN of both directions). The symmetry is what
    rejects a wrong neighbour: a bigger DIFFERENT table that merely *contains*
    the block has high forward but low reverse overlap; a TAIL of the block has
    high reverse but low forward. Only the exact table scores high both ways.
    A candidate that silently DROPS a substantial original value is also skipped
    (`_drops_content`) — a lost row is worse than the ugly-but-complete original.
    Returns `(table_text, score)`, or None below the floor / all-collapsed /
    content-dropping."""
    best: TableBlock | None = None
    best_score = 0.0
    for block in _markdown_table_blocks(docling_md):
        if _is_collapsed(block.text):
            continue
        if _drops_content(cell_text, block.text):
            continue  # candidate omits an original value — keep Marker's complete table
        score = min(_table_overlap(cell_text, block.text), _table_overlap(block.text, cell_text))
        if score > best_score:
            best, best_score = block, score
    if best is None or best_score < _MATCH_MIN_OVERLAP:
        return None
    return best.text, best_score


def match_table(cell_text: str, docling_md: str) -> str | None:
    """The best-matching Docling table's text, or None. Thin wrapper over
    `_best_table_match` (symmetric overlap, `_MATCH_MIN_OVERLAP` floor) — never
    splices a no-better (collapsed / non-overlapping / wrong-neighbour) table."""
    res = _best_table_match(cell_text, docling_md)
    return res[0] if res else None


def _locate_and_match(
    cell_text: str,
    pages: list[int],
    docling_page_ingest: Callable[[int], str],
    page_cache: dict[int, str],
) -> tuple[str, int] | None:
    """Across the candidate `pages`, the GLOBAL best symmetric match
    `(table_text, page)` or None. Evaluates ALL candidate pages — not the first
    that clears the floor — so a better match on a later page wins (a page with
    several near-identical tables can't hand back a wrong neighbour). Each page
    is Docling-ingested at most once via `page_cache`."""
    best: tuple[str, int] | None = None
    best_score = 0.0
    for page in pages[:_MAX_LOCATE_PAGES]:
        if page not in page_cache:
            page_cache[page] = docling_page_ingest(page)
        res = _best_table_match(cell_text, page_cache[page])
        if res is not None and res[1] > best_score:
            best, best_score = (res[0], page), res[1]
    return best
