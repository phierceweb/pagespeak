"""Audit check `lost_table_column`: a table whose label column never arrived.

Marker can drop a table's first column whole (the labels gone, their
descriptions left) or fold a table into one header cell, at exit 0.
The shape alone is ambiguous — an icon column is empty in the source too — so a
suspect table is flagged only when its source page has wording that reached the
document nowhere. Needs the source PDF: runs with `audit --text-coverage`.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

from ._audit_coverage import pdf_page_texts, visible_text, words_in_order
from ._audit_finding import AuditFinding
from ._table_cells import split_table_row
from ._table_match import _markdown_table_blocks

# A lost column empties (nearly) every row; a grouped spec table, whose
# continuation rows leave the label cell empty, fills each group's first row.
_EMPTY_FIRST_SHARE = 0.85
_MIN_DATA_ROWS = 2
_LOCATE_MIN_SHARE = 0.5  # share of a table's words on a page to call it the table's page
_FURNITURE_PAGES = 3  # a word pair on this many pages is a running header or footer
# Unreached pairs counted only in runs: a stripped header leaves one lone pair
# at each edge, a lost label a run of them.
_MIN_MISSING_PAIRS = 3
_PAIRS_SHOWN = 4
# The table's stretch of page text runs between its distinctive words, and back
# this many words per empty-first-cell row: a PDF often stores a column whole,
# so a lost first column sits just before the others.
_SPAN_MIN_WORD_LEN = 4
_SPAN_BACK_PER_ROW = 3
_ALIGN_RE = re.compile(r"^:?-{3,}:?$")
_LINE_HYPHEN_RE = re.compile(r"(\w+)-[ \t]*\r?\n\s*(\w+)")
_SOFT_HYPHEN_RE = re.compile("[\u00ad\x02]")

Pair = tuple[str, str]


def _words_of(text: str) -> list[str]:
    return words_in_order(unicodedata.normalize("NFKC", text))


def _page_words_in_order(page_text: str, file_words: set[str]) -> list[str]:
    """A page's words. A word hyphenated across a line break is rejoined when the
    file has it whole; a compound wrapped at its hyphen (`built-`/`in`) stays two."""

    def rejoin(m: re.Match[str]) -> str:
        whole = m[1] + m[2]
        return whole if "".join(_words_of(whole)) in file_words else f"{m[1]} {m[2]}"

    return _words_of(_LINE_HYPHEN_RE.sub(rejoin, _SOFT_HYPHEN_RE.sub("", page_text)))


def _pairs(words: list[str]) -> list[Pair]:
    return list(zip(words, words[1:], strict=False))  # uneven slices → stop at shorter


def _unreached_runs(span: list[str], found: set[Pair], recurring: set[Pair]) -> list[Pair]:
    """Pairs of `span` in runs of two or more that reached the file nowhere —
    a number, or a pair recurring across pages, never counts."""
    pairs = _pairs(span)
    hit = [
        p not in found and p not in recurring and not (p[0].isdigit() or p[1].isdigit())
        for p in pairs
    ]
    in_run = [
        h and ((i > 0 and hit[i - 1]) or (i + 1 < len(hit) and hit[i + 1]))
        for i, h in enumerate(hit)
    ]
    return list(dict.fromkeys(p for p, keep in zip(pairs, in_run, strict=True) if keep))


def _table_rows(table: str) -> list[list[str]]:
    """Cell texts per row; divider and all-empty rows left out."""
    rows = [[c.strip() for c in split_table_row(line)] for line in table.splitlines()]
    return [r for r in rows if not all(not c or _ALIGN_RE.match(c) for c in r)]


def _reached_pairs(md: str) -> set[Pair]:
    """The file's word pairs, its tables also read column by column: a PDF often
    stores a table that way, so a cell-crossing pair there reached the file too."""
    found = set(_pairs(_words_of(visible_text(md))))
    for block in _markdown_table_blocks(md):
        rows = _table_rows(block.text)
        width = max((len(r) for r in rows), default=0)
        by_column = " ".join(r[j] for j in range(width) for r in rows if j < len(r))
        found.update(_pairs(_words_of(visible_text(by_column))))
    return found


def suspect_tables(md: str) -> list[tuple[int, str, str, int]]:
    """`(1-based line, table text, why, rows missing a first cell)` for each table
    shaped like a lost column: one-column, or a first column empty on nearly every row."""
    out: list[tuple[int, str, str, int]] = []
    for block in _markdown_table_blocks(md):
        first, *rest = block.text.splitlines()
        header = [c.strip() for c in split_table_row(first)]
        data = _table_rows("\n".join(rest))
        if len(data) < _MIN_DATA_ROWS:
            continue
        if len(header) == 1:
            why, empty = "one-column table", len(data)
        else:
            empty = sum(1 for r in data if not r[0])
            if empty < _EMPTY_FIRST_SHARE * len(data):
                continue
            why = f"first column empty on {empty} of {len(data)} rows"
        out.append((block.start + 1, block.text, why, empty))
    return out


def _table_page(table_words: set[str], page_words: list[set[str]]) -> int | None:
    """The page holding most of the table's words. Numbers are left out: a
    multilingual manual repeats a spec table's numbers on every language's page."""
    words = {w for w in table_words if not w.isdigit()}
    if not words or not page_words:
        return None
    best = max(range(len(page_words)), key=lambda i: len(words & page_words[i]))
    return best if len(words & page_words[best]) >= _LOCATE_MIN_SHARE * len(words) else None


def _table_span(words: set[str], page: list[str], empty_rows: int) -> list[str]:
    """The stretch of the page's words around the table's own."""
    distinctive = {w for w in words if len(w) >= _SPAN_MIN_WORD_LEN} or words
    hits = [i for i, w in enumerate(page) if w in distinctive]
    if not hits:
        return []
    return page[max(0, hits[0] - _SPAN_BACK_PER_ROW * empty_rows) : hits[-1] + 1]


def check_lost_column(md: str, page_texts: list[str]) -> list[AuditFinding]:
    suspects = suspect_tables(md)
    if not suspects:
        return []
    file_words = set(_words_of(visible_text(md)))
    pages = [_page_words_in_order(t, file_words) for t in page_texts]
    seen_on = Counter(p for words in pages for p in set(_pairs(words)))
    recurring = {p for p, n in seen_on.items() if n >= _FURNITURE_PAGES}
    found = _reached_pairs(md)
    page_words = [set(words) for words in pages]
    findings: list[AuditFinding] = []
    for line, table, why, empty_rows in suspects:
        table_words = set(_words_of(visible_text(table)))
        page = _table_page(table_words, page_words)
        if page is None:
            continue
        missing = _unreached_runs(
            _table_span(table_words, pages[page], empty_rows), found, recurring
        )
        if len(missing) < _MIN_MISSING_PAIRS:
            continue
        sample = ", ".join(" ".join(p) for p in missing[:_PAIRS_SHOWN])
        findings.append(
            AuditFinding(
                check="lost_table_column",
                severity="warning",
                line=line,
                message=f"{why}; page {page + 1} has wording that reached the file nowhere: {sample}",
            )
        )
    return findings


def check_lost_column_against(md_path: Path, pdf: Path) -> list[AuditFinding]:
    """`check_lost_column` for a converted file and its source PDF; [] when unreadable."""
    page_texts = pdf_page_texts(pdf)
    if page_texts is None:
        return []
    return check_lost_column(md_path.read_text(encoding="utf-8", errors="replace"), page_texts)
