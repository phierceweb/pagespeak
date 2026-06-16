"""Tests for services/_table_repair.py — surgical Docling table-splice.

The pure logic (find mega-cells, find table blocks, match by content overlap,
splice) is unit-tested directly; the orchestrator is tested with the Docling
page-ingest and PDF page-locate I/O injected as fakes (no real Docling / PDF).
"""

from __future__ import annotations

import pagespeak.services._table_repair as _tr
from pagespeak.services._table_repair import (
    RepairRecord,
    _markdown_table_blocks,
    _table_overlap,
    find_collapsed_cells,
    match_table,
    repair_collapsed_tables,
    repair_tables_in_markdown,
)

# A collapse shape: a 3-col table jammed into one mega-cell.
_MEGA = "<br>".join(
    [
        "Data Pump Export Profile",
        "Oracle",
        ".nbakora",
        "Data View Profile",
        "Redis",
        ".ndvredis",
        "ER Diagram File",
        "MySQL, Oracle, PostgreSQL, SQLite, SQL Server and MariaDB",
        ".ned",
    ]
    * 5  # 45 segments -> 44 <br>, above the 30 mega-cell threshold
)

# The clean Docling grid for the same table.
_DOCLING_GRID = (
    "| Profile Type | Database | Extension |\n"
    "| --- | --- | --- |\n"
    "| Data Pump Export Profile | Oracle | .nbakora |\n"
    "| Data View Profile | Redis | .ndvredis |\n"
    "| ER Diagram File | MySQL, Oracle, PostgreSQL, SQLite, SQL Server and MariaDB | .ned |\n"
)


# ── find_collapsed_cells ────────────────────────────────────────────────────


def test_find_collapsed_cells_flags_megacell() -> None:
    text = f"intro\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n\nafter\n"
    cells = find_collapsed_cells(text)
    assert len(cells) == 1
    assert cells[0].line_index == 2  # 0-based
    assert cells[0].br_count >= 30
    assert "Data Pump Export Profile" in cells[0].cell_text


def test_find_collapsed_cells_ignores_legit_multiline() -> None:
    text = "| a<br>b<br>c | x |\n| --- | --- |\n"
    assert find_collapsed_cells(text) == []


def test_find_collapsed_cells_ignores_fenced() -> None:
    text = f"```\n| {_MEGA} |\n```\n"
    assert find_collapsed_cells(text) == []


# ── find_split_tables ───────────────────────────────────────────────────────


def test_find_split_tables_flags_continuation_rows() -> None:
    """Marker splits a wrapped multi-line cell into one row per visual line — a
    'continuation row' has an empty leading (key) cell + content in a later
    cell. Such tables are flagged for Docling re-extraction."""
    from pagespeak.services._table_repair import find_split_tables

    text = (
        "| Member Rights | Privileges |\n"
        "| --- | --- |\n"
        "| Can Manage & Edit | Read, Write, Manage Members and Rename |\n"
        "|  | Projects |\n"  # continuation of the row above
        "| Can View | Read Objects |\n"
    )
    blocks = find_split_tables(text)
    assert len(blocks) == 1
    assert "Member Rights" in blocks[0].text


def test_find_split_tables_ignores_clean_table() -> None:
    """A table whose every row has content in BOTH cells is not split."""
    from pagespeak.services._table_repair import find_split_tables

    assert find_split_tables("| K | V |\n| --- | --- |\n| a | 1 |\n| b | 2 |\n") == []


def test_find_split_tables_flags_wrapped_key() -> None:
    """The other split shape: the KEY (option name) wraps, leaving the
    description cell empty on the continuation row — content in col 1, every
    later cell empty. Also flagged for Docling re-extraction."""
    from pagespeak.services._table_repair import find_split_tables

    text = (
        "| Option | Description |\n"
        "| --- | --- |\n"
        "| Analyze Tables / Analyze | Collect statistics about the table. |\n"
        "| Materialized Views |  |\n"  # wrapped KEY continuation: empty description
        "| Vacuum | Garbage-collect the table. |\n"
    )
    blocks = find_split_tables(text)
    assert len(blocks) == 1
    assert "Materialized Views" in blocks[0].text


# ── _markdown_table_blocks ──────────────────────────────────────────────────


def test_table_blocks_finds_contiguous_pipe_lines() -> None:
    text = "prose\n| a | b |\n| --- | --- |\n| 1 | 2 |\nmore prose\n| x | y |\n| --- | --- |\n"
    blocks = _markdown_table_blocks(text)
    assert len(blocks) == 2
    assert blocks[0].start == 1 and blocks[0].end == 3  # inclusive line range
    assert "| a | b |" in blocks[0].text


def test_table_blocks_treats_empty_rows_as_part_of_block() -> None:
    text = f"| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |\n"
    blocks = _markdown_table_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].end == 3


# ── _table_overlap / match_table ────────────────────────────────────────────


def test_overlap_high_for_same_content() -> None:
    assert _table_overlap(_MEGA, _DOCLING_GRID) > 0.8


def test_overlap_low_for_unrelated() -> None:
    assert _table_overlap(_MEGA, "| Color | Hex |\n| --- | --- |\n| Red | #f00 |\n") < 0.3


def test_match_table_picks_best_overlap() -> None:
    docling_md = (
        "## Page\n\nSome intro text.\n\n"
        "| Unrelated | Junk |\n| --- | --- |\n| a | b |\n\n"
        f"{_DOCLING_GRID}\n"
    )
    matched = match_table(_MEGA, docling_md)
    assert matched is not None
    assert ".nbakora" in matched and "Profile Type" in matched


def test_match_table_none_when_no_overlap() -> None:
    docling_md = "| Color | Hex |\n| --- | --- |\n| Red | #f00 |\n"
    assert match_table(_MEGA, docling_md) is None


def test_match_table_skips_docling_that_is_also_collapsed() -> None:
    """If Docling ALSO collapsed the table (>=30 <br> in a cell), don't splice
    a no-better table — return None so the orchestrator skips it."""
    collapsed_docling = f"| {_MEGA} |  |\n| --- | --- |\n"
    assert match_table(_MEGA, collapsed_docling) is None


def test_match_table_rejects_candidate_that_drops_a_distinctive_row() -> None:
    """Docling can silently OMIT a row when re-extracting a table. A candidate
    that drops a substantial value the original had must be REJECTED (no-match),
    not spliced in — a lost row is worse than the ugly-but-complete original.
    Regression: a whole row was lost while token overlap stayed high (one
    dropped row barely moves the set overlap)."""
    original = (
        "| Control | Function |\n| --- | --- |\n"
        "|  | MASTER level control adjusts the overall power amplification |\n"
        "|  | MIC IN XLR connector accepts low impedance dynamic microphone signals |\n"
        "|  | POWER switch energises the unit and lights the status indicator |\n"
    )
    dropped_mic_in = (
        "| Control | Function |\n| --- | --- |\n"
        "|  | MASTER level control adjusts the overall power amplification |\n"
        "|  | POWER switch energises the unit and lights the status indicator |\n"
    )
    assert match_table(original, dropped_mic_in) is None


def test_match_table_accepts_candidate_that_preserves_every_value() -> None:
    """The content guard must NOT reject a good repair: a Docling table that
    merges the split rows but keeps every distinctive value still matches."""
    original = (
        "| Key | Value |\n| --- | --- |\n"
        "| Alpha | the quick brown vixen leaps gracefully over |\n"
        "|  | the drowsy slumbering hound this morning |\n"
    )
    merged = (
        "| Key | Value |\n| --- | --- |\n"
        "| Alpha | the quick brown vixen leaps gracefully over the drowsy slumbering hound this morning |\n"
    )
    matched = match_table(original, merged)
    assert matched is not None
    assert "quick brown vixen" in matched


# ── repair_collapsed_tables (orchestrator, injected I/O) ────────────────────


def _fake_locate(_cell: str) -> list[int]:
    return [7]  # pretend the table is on page index 7


def _fake_docling(_page: int) -> str:
    return f"page text\n\n{_DOCLING_GRID}\n"


def test_repair_splices_clean_grid() -> None:
    text = f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n\ntail\n"
    repaired, records = repair_collapsed_tables(
        text, locate_pages=_fake_locate, docling_page_ingest=_fake_docling
    )
    assert "Profile<br>Oracle" not in repaired  # <br> blob gone
    assert "| Data Pump Export Profile | Oracle | .nbakora |" in repaired  # grid in
    assert "# Doc" in repaired and "tail" in repaired  # surrounding preserved
    assert len(records) == 1 and records[0].status == "repaired"


def test_repair_skips_when_no_page_found() -> None:
    text = f"| {_MEGA} |  |\n| --- | --- |\n"
    repaired, records = repair_collapsed_tables(
        text, locate_pages=lambda _c: [], docling_page_ingest=_fake_docling
    )
    assert repaired == text  # unchanged
    assert records[0].status == "no-page"


def test_repair_skips_when_no_matching_table() -> None:
    text = f"| {_MEGA} |  |\n| --- | --- |\n"
    repaired, records = repair_collapsed_tables(
        text,
        locate_pages=_fake_locate,
        docling_page_ingest=lambda _p: "| Color | Hex |\n| --- | --- |\n| Red | #f00 |\n",
    )
    assert repaired == text
    assert records[0].status == "no-match"


def test_repair_one_splice_per_block_with_two_megacells() -> None:
    """A single table can hold more than one collapsed mega-cell (a multi-row
    collapse). Splicing the whole block fixes them all, so the block must be
    replaced exactly ONCE — patching once per mega-cell double-applies the grid
    over a shifted range and duplicates rows."""
    # Two mega-cell rows inside one contiguous table block.
    text = f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n| {_MEGA} |  |  |\n\ntail\n"
    cells = find_collapsed_cells(text)
    assert len(cells) == 2  # both rows flagged, same block
    repaired, records = repair_collapsed_tables(
        text, locate_pages=_fake_locate, docling_page_ingest=_fake_docling
    )
    grid_row = (
        "| ER Diagram File | MySQL, Oracle, PostgreSQL, SQLite, SQL Server and MariaDB | .ned |"
    )
    assert repaired.count(grid_row) == 1  # spliced once, not duplicated
    assert "<br>" not in repaired  # both mega-cells gone
    assert "# Doc" in repaired and "tail" in repaired  # surrounding preserved
    assert [r.status for r in records] == ["repaired", "repaired"]


def test_repair_leaves_non_collapsed_sibling_table_untouched() -> None:
    """A clean table elsewhere in the doc passes through unchanged — repair only
    rewrites the block holding the mega-cell, never a healthy sibling table."""
    clean = "| Color | Hex |\n| --- | --- |\n| Red | #f00 |"
    text = f"{clean}\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n"
    repaired, records = repair_collapsed_tables(
        text, locate_pages=_fake_locate, docling_page_ingest=_fake_docling
    )
    assert clean in repaired  # healthy sibling untouched
    assert records[0].status == "repaired"


def test_repair_searches_later_candidate_page_for_the_match() -> None:
    """locate can yield several candidate pages — the cell's snippet also appears
    in body prose on an EARLIER page than the real table. The splice must try
    each candidate in order and use the first whose Docling grid matches, not
    give up on the first page's non-matching table. Regression for a mis-locate
    where the snippet appeared in prose on an earlier page than the real grid."""
    text = f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n\ntail\n"
    by_page = {
        0: "| Unrelated | Junk |\n| --- | --- |\n| a | b |\n",  # earlier page: wrong table
        1: f"page\n\n{_DOCLING_GRID}\n",  # later page: the real grid
    }
    repaired, records = repair_collapsed_tables(
        text,
        locate_pages=lambda _c: [0, 1],
        docling_page_ingest=lambda p: by_page[p],
    )
    assert "| Data Pump Export Profile | Oracle | .nbakora |" in repaired  # spliced
    assert "<br>" not in repaired
    assert records[0].status == "repaired"
    assert records[0].page == 1  # matched on the SECOND candidate, not the first


def test_repair_evaluates_all_candidate_pages_deduped() -> None:
    """The splice evaluates ALL candidate pages (each Docling-ingested once) and
    takes the GLOBAL-best match — not the first page that clears the floor.
    (First-match-wins spliced a wrong neighbour table on pages holding several
    similar tables.)"""
    text = f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n"
    ingested: list[int] = []

    def _docling(p: int) -> str:
        ingested.append(p)
        return f"page\n\n{_DOCLING_GRID}\n"

    _repaired, records = repair_collapsed_tables(
        text, locate_pages=lambda _c: [0, 1, 2], docling_page_ingest=_docling
    )
    assert records[0].status == "repaired"
    assert ingested == [0, 1, 2]  # all candidate pages evaluated once each (no early stop)


# ── repair_split_tables (Docling re-extraction of split multi-line cells) ───


def test_repair_split_tables_reextracts_via_docling() -> None:
    """A Marker split table (continuation rows) is matched to a Docling table on
    its source page and replaced by the merged grid."""
    from pagespeak.services._table_repair import repair_split_tables

    text = (
        "intro\n\n"
        "| Key | Value |\n| --- | --- |\n"
        "| Alpha | first part of |\n|  | a wrapped value |\n"
        "| Beta | short |\n\ntail\n"
    )
    clean = "| Key | Value |\n| --- | --- |\n| Alpha | first part of a wrapped value |\n| Beta | short |\n"
    repaired, records = repair_split_tables(
        text,
        locate_pages=lambda _s: [0],
        docling_page_ingest=lambda _p: f"page text\n\n{clean}\n",
    )
    assert "| Alpha | first part of a wrapped value |" in repaired  # wrapped cell merged
    assert "|  | a wrapped value |" not in repaired  # the continuation row is gone
    assert records[0].status == "repaired"
    assert "intro" in repaired and "tail" in repaired  # surrounding preserved


def test_repair_split_tables_dedupes_docling_per_page() -> None:
    """Two split tables on the same page trigger ONE Docling ingest, not two."""
    from pagespeak.services._table_repair import repair_split_tables

    text = (
        "| A | B |\n| --- | --- |\n| x | wrapped one |\n|  | more |\n\n"
        "| C | D |\n| --- | --- |\n| y | wrapped two |\n|  | extra |\n"
    )
    ingests: list[int] = []

    def _docling(p: int) -> str:
        ingests.append(p)
        return (
            "| A | B |\n| --- | --- |\n| x | wrapped one more |\n"
            "| C | D |\n| --- | --- |\n| y | wrapped two extra |\n"
        )

    _repaired, records = repair_split_tables(
        text, locate_pages=lambda _s: [0], docling_page_ingest=_docling
    )
    assert ingests == [0]  # page 0 ingested once and reused for the second table
    assert [r.status for r in records] == ["repaired", "repaired"]


def test_repair_split_picks_best_page_not_first_match() -> None:
    """The snippet can locate several pages; the splice must take the BEST match
    across all of them, not the first page that clears the floor. Regression:
    an earlier page held a TAIL of the table, a later page the full one."""
    from pagespeak.services._table_repair import repair_split_tables

    text = (
        "| K | V |\n| --- | --- |\n| Alpha | first value |\n|  | wrapped here |\n"
        "| Beta | second value |\n| Gamma | third value |\n"
    )
    tail = "| K | V |\n| --- | --- |\n| Beta | second value |\n| Gamma | third value |\n"
    full = (
        "| K | V |\n| --- | --- |\n| Alpha | first value wrapped here |\n"
        "| Beta | second value |\n| Gamma | third value |\n"
    )
    repaired, records = repair_split_tables(
        text,
        locate_pages=lambda _s: [0, 1],
        docling_page_ingest=lambda p: f"x\n\n{tail if p == 0 else full}\n",
    )
    assert "| Alpha | first value wrapped here |" in repaired  # full table on page 1, not the tail
    assert records[0].page == 1


def test_repair_split_rejects_bigger_overlapping_table() -> None:
    """A bigger DIFFERENT table that merely CONTAINS the block's rows (forward
    overlap 1.0, but full of extra rows) must lose to the exact table. Symmetric
    overlap: the bigger table has low reverse overlap. Regression: a superset
    table on an adjacent page wrongly matched."""
    from pagespeak.services._table_repair import repair_split_tables

    text = "| K | V |\n| --- | --- |\n| Alpha | first value |\n|  | wrapped here |\n| Beta | second value |\n"
    bigger = (
        "| K | V |\n| --- | --- |\n| Alpha | first value wrapped here |\n| Beta | second value |\n"
        "| Cee | extra one |\n| Dee | extra two |\n| Eee | extra three |\n| Eff | extra four |\n"
    )
    exact = (
        "| K | V |\n| --- | --- |\n| Alpha | first value wrapped here |\n| Beta | second value |\n"
    )
    repaired, records = repair_split_tables(
        text,
        locate_pages=lambda _s: [0, 1],
        docling_page_ingest=lambda p: f"x\n\n{bigger if p == 0 else exact}\n",
    )
    assert records[0].page == 1  # the exact table, not the bigger superset on page 0
    assert "Cee" not in repaired


# ── repair_tables_in_markdown (real-wiring convenience; I/O monkeypatched) ──


def test_repair_tables_in_markdown_noop_when_clean(monkeypatch) -> None:
    """No collapsed cells → return the markdown untouched and NEVER call the
    PDF/Docling I/O (a clean doc must not even reach Docling)."""

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("I/O must not be touched when there are no collapses")

    monkeypatch.setattr(_tr, "locate_pages_in_pdf", _boom)
    monkeypatch.setattr(_tr, "docling_page_md", _boom)
    md = "# Doc\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    out, records = repair_tables_in_markdown(md, "missing.pdf")
    assert out == md
    assert records == []


def test_repair_tables_in_markdown_splices_with_real_wiring(monkeypatch) -> None:
    """With a collapsed table it wires the module's real `locate_page_in_pdf` +
    `docling_page_md` (here monkeypatched — no real PDF/Docling) and splices the
    clean grid in."""
    monkeypatch.setattr(_tr, "locate_pages_in_pdf", lambda _cell, _pdf: [3])
    monkeypatch.setattr(_tr, "docling_page_md", lambda _pdf, _page: f"page\n\n{_DOCLING_GRID}\n")
    md = f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n"
    out, records = repair_tables_in_markdown(md, "whatever.pdf")
    assert "| Data Pump Export Profile | Oracle | .nbakora |" in out
    assert "<br>" not in out
    assert records and records[0].status == "repaired"


def test_repair_tables_in_markdown_also_repairs_split_tables(monkeypatch) -> None:
    """The single entry point fixes split multi-line-cell tables too, not just
    `<br>` collapses — so `--repair-tables` covers both."""
    monkeypatch.setattr(_tr, "locate_pages_in_pdf", lambda _s, _pdf: [2])
    clean = "| Key | Value |\n| --- | --- |\n| Alpha | first part of a wrapped value |\n"
    monkeypatch.setattr(_tr, "docling_page_md", lambda _pdf, _p: f"page\n\n{clean}\n")
    md = "| Key | Value |\n| --- | --- |\n| Alpha | first part of |\n|  | a wrapped value |\n"
    out, records = repair_tables_in_markdown(md, "whatever.pdf")
    assert "| Alpha | first part of a wrapped value |" in out  # split cell merged
    assert records and records[0].status == "repaired"


def test_repair_record_is_frozen() -> None:
    r = RepairRecord(line=1, br_count=40, page=7, status="repaired")
    try:
        r.line = 2  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("RepairRecord must be frozen")
