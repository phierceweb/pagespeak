from __future__ import annotations

import pytest

from pagespeak.services._table_cells import split_table_row


def test_escaped_pipe_is_cell_content() -> None:
    assert split_table_row("| `a \\| b` | either |") == [" `a \\| b` ", " either "]


def test_trailing_escaped_pipe_is_cell_content() -> None:
    assert split_table_row("| a | b \\|") == [" a ", " b \\|"]


def test_unescaped_pipe_in_code_still_splits() -> None:
    # GFM splits cells before parsing inline code; only `\|` is literal.
    assert split_table_row("| `a | b` |") == [" `a ", " b` "]


@pytest.mark.parametrize(
    "row",
    [
        "| a | b |",
        "|a|b|",
        "| a | b",
        "a | b",
        "   | a | b |   ",
        "| a |  | c |",
        "| a || c |",
        "|| a |",
        "| a ||",
        "|  | b |",
        "| --- | :---: |",
        "| solo |",
    ],
)
def test_matches_plain_split_when_nothing_is_escaped(row: str) -> None:
    assert split_table_row(row) == row.strip().strip("|").split("|")
