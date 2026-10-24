"""Surgical table repair: replace a Marker-collapsed `<br>` mega-cell with the
clean grid Docling extracts from the *same PDF page*.

Marker sometimes jams a whole multi-column / side-by-side table into one
`<br>`-joined cell (audit `collapsed_table`, ≥30 `<br>`). Docling reads those
correctly — but Docling is a TARGETED fix, not a blanket upgrade (it adds
OCR noise, drops headers, busts
the vision cache). So this splices ONLY Docling's clean table into the
otherwise-Marker markdown: Docling-ingest the collapse page, match the table
by content overlap, swap it in. No whole-doc re-ingest, no re-vision.

I/O (PDF page-locate, Docling page-ingest) is injected so the splice logic is
pure and unit-testable; the CLI wires the real backends.

A splice is kept only when Docling's table holds every word of the Marker table
it replaces (`_table_words`) and does not also carry a neighbouring Marker
table; otherwise Marker's stays and the record says why.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pw_foundation.log import get_logger

from ._table_cells import split_table_row
from ._table_match import (
    MEGA_CELL_MIN,
    TableBlock,
    _fenced_line_indices,
    _locate_and_match,
    _markdown_table_blocks,
)
from ._table_words import _BR_RE, absorbs_other_table, lost_words

logger = get_logger(__name__)

_DIVIDER_CELL_RE = re.compile(r"^:?-+:?$")
_CLOSING_PUNCT = ".!?:;)"


@dataclass(frozen=True)
class CollapsedCell:
    """A table row whose worst cell is a `<br>`-collapsed mega-cell."""

    line_index: int  # 0-based index into text.splitlines()
    cell_text: str  # the full `<br>`-joined mega-cell content
    br_count: int


@dataclass(frozen=True)
class RepairRecord:
    """The outcome of attempting to repair one collapsed table."""

    line: int  # 1-based line of the mega-cell
    br_count: int
    page: int | None  # 0-based PDF page it was located on (None if not found)
    status: str  # "repaired" | "no-page" | "no-match" | "loses-words" | "absorbs-table"
    lost: tuple[str, ...] = ()  # with "loses-words": the words Docling's table lacks


def find_collapsed_cells(text: str) -> list[CollapsedCell]:
    """Every table row holding a `<br>` mega-cell (≥30), outside fenced code."""
    lines = text.splitlines()
    fenced = _fenced_line_indices(lines)
    out: list[CollapsedCell] = []
    for i, line in enumerate(lines):
        if i in fenced or not line.strip().startswith("|"):
            continue
        cells = split_table_row(line)
        worst = max(cells, key=lambda c: len(_BR_RE.findall(c)), default="")
        n = len(_BR_RE.findall(worst))
        if n >= MEGA_CELL_MIN:
            out.append(CollapsedCell(line_index=i, cell_text=worst.strip(), br_count=n))
    return out


def find_split_tables(text: str) -> list[TableBlock]:
    """Table blocks where Marker split a wrapped multi-line cell into one row
    per visual line. The signal is a *continuation row* of either shape, below
    the header:

    - a wrapped VALUE — empty leading (key) cell, content in a later cell; or
    - a wrapped KEY — content in the leading cell, every later cell empty.

    - BOTH wrapped — every cell filled: the key is its second line, a
      parenthetical (`(lid side)` under `Power switch`), and a value picks up
      mid-sentence (lower case, two or more words, the cell above ending
      without closing punctuation).

    A divider row (`| --- | --- |`) trips none (its cells are all `---`).
    These re-extract cleanly via Docling, which reads the PDF's real cell spans
    rather than the visual line breaks. Over-flagging a table with a legitimately
    empty value cell is harmless: the symmetric-overlap match gate only splices a
    genuinely-better Docling table."""
    out: list[TableBlock] = []
    for block in _markdown_table_blocks(text):
        above: list[str] | None = None
        for raw in block.text.splitlines()[1:]:  # skip the header row
            parts = [c.strip() for c in split_table_row(raw)]
            if len(parts) < 2 or all(_DIVIDER_CELL_RE.match(c) for c in parts):
                continue
            wrapped_value = parts[0] == "" and any(parts[1:])
            wrapped_key = parts[0] != "" and not any(parts[1:])
            if wrapped_value or wrapped_key or _both_wrapped(above, parts):
                out.append(block)
                break
            above = parts
    return out


def _both_wrapped(above: list[str] | None, parts: list[str]) -> bool:
    if above is None or not parts[0].startswith("("):
        return False
    return any(
        len(cell.split()) >= 2
        and cell[0].islower()
        and j < len(above)
        and above[j]
        and above[j][-1] not in _CLOSING_PUNCT
        for j, cell in enumerate(parts[1:], start=1)
        if cell
    )


def _refusal(
    block: TableBlock, matched: str, blocks: list[TableBlock]
) -> tuple[str, tuple[str, ...]] | None:
    """`(status, missing words)` when `matched` may not replace `block`, else None."""
    lost = lost_words(block.text, matched)
    if lost:
        return "loses-words", lost
    i = blocks.index(block)
    neighbours = [b.text for b in blocks[max(0, i - 1) : i] + blocks[i + 1 : i + 2]]
    if absorbs_other_table(block.text, matched, neighbours):
        return "absorbs-table", ()
    return None


def _refused_splice(
    line: int, br_count: int, page: int, status: str, lost: tuple[str, ...]
) -> RepairRecord:
    logger.warning(
        "table_repair_kept_marker line=%d page=%d reason=%s missing=%s",
        line,
        page,
        status,
        ", ".join(lost[:12]),
    )
    return RepairRecord(line, br_count, page, status, lost)


def _search_snippet(cell_text: str) -> str | None:
    """A distinctive substring of the mega-cell to grep the PDF for — the
    longest `<br>`-segment (most distinctive), capped so minor PDF-vs-extract
    spacing differences don't break the match."""
    segments = [s.strip() for s in _BR_RE.split(cell_text) if len(s.strip()) >= 6]
    if not segments:
        return None
    return max(segments, key=len)[:48]


def locate_pages_in_pdf(cell_text: str, pdf_path: str) -> list[int]:
    """Every 0-based PDF page whose text contains a distinctive snippet of the
    collapsed cell, in page order. The splice tries them in turn and takes the
    first whose Docling grid matches — so a snippet that also appears in body
    prose *before* the real table no longer anchors the splice to the wrong page
    (a first-page-wins mis-locate). Real I/O — wired by the CLI, not unit-tested."""
    import pypdfium2 as pdfium

    snippet = _search_snippet(cell_text)
    if not snippet:
        return []
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        return [i for i in range(len(pdf)) if snippet in pdf[i].get_textpage().get_text_bounded()]
    finally:
        pdf.close()


def docling_page_md(pdf_path: str, page: int) -> str:
    """Markdown for a single PDF page via Docling, no image side-effects. Real
    I/O — wired by the CLI, not unit-tested."""
    from pathlib import Path

    from ..backends._pdf_docling import convert_pdf_docling

    result = convert_pdf_docling(Path(pdf_path), page_range=f"{page}-{page}", output_dir=None)
    return result.markdown


def repair_collapsed_tables(
    text: str,
    *,
    locate_pages: Callable[[str], list[int]],
    docling_page_ingest: Callable[[int], str],
) -> tuple[str, list[RepairRecord]]:
    """Splice Docling's clean grid in for each collapsed table in `text`.

    For each mega-cell: locate its candidate PDF page(s), Docling-ingest each in
    turn until one yields a matching table, and replace the whole collapsed table
    block. Tables whose page can't be found or whose Docling table doesn't match
    (or is itself collapsed) on any candidate page are left untouched and
    recorded. Returns the repaired markdown and one `RepairRecord` per collapsed
    table.
    """
    lines = text.splitlines()
    cells = find_collapsed_cells(text)
    blocks = _markdown_table_blocks(text)
    records: list[RepairRecord] = []
    replacements: list[tuple[int, int, str]] = []
    repaired_blocks: set[int] = set()
    page_cache: dict[int, str] = {}
    for cell in cells:
        block = next((b for b in blocks if b.start <= cell.line_index <= b.end), None)
        pages = locate_pages(cell.cell_text)
        if not pages:
            records.append(RepairRecord(cell.line_index + 1, cell.br_count, None, "no-page"))
            continue
        if block is not None and block.start in repaired_blocks:
            # A table can hold >1 mega-cell (a multi-row collapse). The whole-block
            # splice queued by the first mega-cell already fixes this one — splice
            # the block ONCE, or the second replacement lands on shifted indices and
            # duplicates rows.
            records.append(RepairRecord(cell.line_index + 1, cell.br_count, pages[0], "repaired"))
            continue
        m = _locate_and_match(cell.cell_text, pages, docling_page_ingest, page_cache)
        if m is None or block is None:
            records.append(RepairRecord(cell.line_index + 1, cell.br_count, pages[0], "no-match"))
            continue
        matched, page = m
        refusal = _refusal(block, matched, blocks)
        if refusal:
            records.append(_refused_splice(cell.line_index + 1, cell.br_count, page, *refusal))
            continue
        replacements.append((block.start, block.end, matched))
        repaired_blocks.add(block.start)
        records.append(RepairRecord(cell.line_index + 1, cell.br_count, page, "repaired"))
    # Apply back-to-front so earlier line indices stay valid.
    for start, end, repl in sorted(replacements, reverse=True):
        lines[start : end + 1] = repl.splitlines()
    repaired = "\n".join(lines)
    if text.endswith("\n") and not repaired.endswith("\n"):
        repaired += "\n"
    return repaired, records


def _table_snippet(block_text: str) -> str | None:
    """A distinctive, clean (no pipe / divider) phrase from a split table, to
    locate its source PDF page. Split tables aren't `<br>`-joined, so the
    mega-cell `_search_snippet` doesn't apply — pick the longest real cell value."""
    vals = [
        cell.strip()
        for line in block_text.splitlines()
        for cell in split_table_row(line)
        if len(cell.strip()) >= 8 and "---" not in cell
    ]
    return max(vals, key=len)[:48] if vals else None


def repair_split_tables(
    text: str,
    *,
    locate_pages: Callable[[str], list[int]],
    docling_page_ingest: Callable[[int], str],
) -> tuple[str, list[RepairRecord]]:
    """Re-extract Marker's split-multi-line-cell tables via Docling and splice
    the merged grid in. Each split block (`find_split_tables`) is matched to a
    Docling table on its source page; pages are Docling-ingested at most once
    (dedup), since many split tables share a page. One `RepairRecord` per split
    table (`br_count` is 0 — these are not `<br>` collapses)."""
    lines = text.splitlines()
    blocks = _markdown_table_blocks(text)
    records: list[RepairRecord] = []
    replacements: list[tuple[int, int, str]] = []
    page_cache: dict[int, str] = {}
    for block in find_split_tables(text):
        snippet = _table_snippet(block.text)
        pages = locate_pages(snippet) if snippet else []
        if not pages:
            records.append(RepairRecord(block.start + 1, 0, None, "no-page"))
            continue
        m = _locate_and_match(block.text, pages, docling_page_ingest, page_cache)
        if m is None:
            records.append(RepairRecord(block.start + 1, 0, pages[0], "no-match"))
            continue
        matched, page = m
        refusal = _refusal(block, matched, blocks)
        if refusal:
            records.append(_refused_splice(block.start + 1, 0, page, *refusal))
            continue
        replacements.append((block.start, block.end, matched))
        records.append(RepairRecord(block.start + 1, 0, page, "repaired"))
    for start, end, repl in sorted(replacements, reverse=True):
        lines[start : end + 1] = repl.splitlines()
    repaired = "\n".join(lines)
    if text.endswith("\n") and not repaired.endswith("\n"):
        repaired += "\n"
    return repaired, records


def repair_tables_in_markdown(markdown: str, pdf_path: str) -> tuple[str, list[RepairRecord]]:
    """Re-extract Marker's broken tables from `pdf_path` via Docling and splice
    the clean grids in — BOTH `<br>`-collapsed mega-cells and split
    multi-line-cell tables (Marker emitting one row per wrapped line). Returns
    `(repaired_markdown, records)`; a no-op `(markdown, [])` when neither defect
    is present (so Docling is never even imported for a clean doc). Raises
    `ImportError` only if a repair is actually attempted and Docling isn't
    installed — the caller decides whether to warn and skip. The shared entry
    point for the `--repair-tables` convert sub-step."""

    def _locate(snippet: str) -> list[int]:
        return locate_pages_in_pdf(snippet, pdf_path)

    def _ingest(page: int) -> str:
        return docling_page_md(pdf_path, page)

    out = markdown
    records: list[RepairRecord] = []
    if find_collapsed_cells(out):
        out, recs = repair_collapsed_tables(out, locate_pages=_locate, docling_page_ingest=_ingest)
        records += recs
    if find_split_tables(out):
        out, recs = repair_split_tables(out, locate_pages=_locate, docling_page_ingest=_ingest)
        records += recs
    return out, records
