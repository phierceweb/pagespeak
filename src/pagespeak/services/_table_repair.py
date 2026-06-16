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
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z0-9.]+")
_MEGA_CELL_MIN = 30  # <br> in one cell marking a collapse (matches the audit)
_MATCH_MIN_OVERLAP = 0.5  # token overlap to accept a Docling table as the match
# Cap candidate pages tried per cell — bounds Docling cost if a snippet recurs widely.
_MAX_LOCATE_PAGES = 12
# Content-preservation guard: reject a Docling candidate that silently OMITS a
# substantial value the original had. One dropped row barely moves token-set
# overlap, so judge per-value on bigrams — a dropped value's word-pairs vanish.
_VALUE_MIN_BIGRAMS = 4  # a value with >=4 token-bigrams is substantial enough to judge
_VALUE_PRESERVED_MIN = 0.5  # a substantial value keeping <50% of its bigrams was dropped


@dataclass(frozen=True)
class CollapsedCell:
    """A table row whose worst cell is a `<br>`-collapsed mega-cell."""

    line_index: int  # 0-based index into text.splitlines()
    cell_text: str  # the full `<br>`-joined mega-cell content
    br_count: int


@dataclass(frozen=True)
class TableBlock:
    """A contiguous run of markdown table lines (`|`-prefixed)."""

    start: int  # 0-based first line, inclusive
    end: int  # 0-based last line, inclusive
    text: str


@dataclass(frozen=True)
class RepairRecord:
    """The outcome of attempting to repair one collapsed table."""

    line: int  # 1-based line of the mega-cell
    br_count: int
    page: int | None  # 0-based PDF page it was located on (None if not found)
    status: str  # "repaired" | "no-page" | "no-match"


def _fenced_line_indices(lines: list[str]) -> set[int]:
    fenced: set[int] = set()
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced.add(i)
            in_fence = not in_fence
            continue
        if in_fence:
            fenced.add(i)
    return fenced


def find_collapsed_cells(text: str) -> list[CollapsedCell]:
    """Every table row holding a `<br>` mega-cell (≥30), outside fenced code."""
    lines = text.splitlines()
    fenced = _fenced_line_indices(lines)
    out: list[CollapsedCell] = []
    for i, line in enumerate(lines):
        if i in fenced or not line.strip().startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        worst = max(cells, key=lambda c: len(_BR_RE.findall(c)), default="")
        n = len(_BR_RE.findall(worst))
        if n >= _MEGA_CELL_MIN:
            out.append(CollapsedCell(line_index=i, cell_text=worst.strip(), br_count=n))
    return out


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


def find_split_tables(text: str) -> list[TableBlock]:
    """Table blocks where Marker split a wrapped multi-line cell into one row
    per visual line. The signal is a *continuation row* of either shape, below
    the header:

    - a wrapped VALUE — empty leading (key) cell, content in a later cell; or
    - a wrapped KEY — content in the leading cell, every later cell empty.

    A divider row (`| --- | --- |`) trips neither (its cells are all `---`).
    These re-extract cleanly via Docling, which reads the PDF's real cell spans
    rather than the visual line breaks. Over-flagging a table with a legitimately
    empty value cell is harmless: the symmetric-overlap match gate only splices a
    genuinely-better Docling table."""
    out: list[TableBlock] = []
    for block in _markdown_table_blocks(text):
        for raw in block.text.splitlines()[1:]:  # skip the header row
            parts = [c.strip() for c in raw.strip().strip("|").split("|")]
            if len(parts) < 2:
                continue
            wrapped_value = parts[0] == "" and any(parts[1:])
            wrapped_key = parts[0] != "" and not any(parts[1:])
            if wrapped_value or wrapped_key:
                out.append(block)
                break
    return out


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
            out.extend(c.strip() for c in s.strip("|").split("|") if c.strip() and "---" not in c)
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
    return any(len(_BR_RE.findall(c)) >= _MEGA_CELL_MIN for c in table_text.split("|"))


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
        for cell in line.strip().strip("|").split("|")
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
