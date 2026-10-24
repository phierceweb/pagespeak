"""Tests for services._table_match — table blocks, and the Docling table that
matches a Marker one."""

from __future__ import annotations

from pagespeak.services._table_match import _markdown_table_blocks, _table_overlap, match_table

# A collapse shape: a 3-col table jammed into one mega-cell.
_MEGA = "<br>".join(
    [
        "Gear Housing Shell Part",
        "Brass",
        ".wghsp",
        "Spring Clip Mount",
        "Steel",
        ".wscm",
        "Pivot Arm Bracket",
        "Brass, Steel, Copper, Nickel, Zinc Alloy and Tin",
        ".wpa",
    ]
    * 5  # 45 segments -> 44 <br>, above the 30 mega-cell threshold
)

# The clean Docling grid for the same table.
_DOCLING_GRID = (
    "| Widget Type | Material | Suffix |\n"
    "| --- | --- | --- |\n"
    "| Gear Housing Shell Part | Brass | .wghsp |\n"
    "| Spring Clip Mount | Steel | .wscm |\n"
    "| Pivot Arm Bracket | Brass, Steel, Copper, Nickel, Zinc Alloy and Tin | .wpa |\n"
)


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
    assert ".wghsp" in matched and "Widget Type" in matched


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
