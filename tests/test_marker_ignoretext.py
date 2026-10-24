"""Tests for backends._marker_ignoretext — Marker's repeated-text remover, keeping
the first copy of a text it would otherwise delete everywhere."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pagespeak.backends._marker_ignoretext import (
    IgnoreTextProcessor,
    marker_processor_list,
    sole_copies_to_restore,
)

# --- the decision ----------------------------------------------------


def test_restores_the_first_copy_of_a_text_left_with_none() -> None:
    marked = ["Using the Widget Menu"] * 3
    assert sole_copies_to_restore(marked, ["body text"], threshold=90) == [0]


def test_leaves_a_text_that_survives_elsewhere() -> None:
    assert sole_copies_to_restore(["Running Header"] * 4, ["Running Header"], threshold=90) == []


def test_restores_one_copy_per_text() -> None:
    marked = ["Charging the Widget", "Specs: Widget", "Charging the Widget", "Specs: Widget"]
    assert sole_copies_to_restore(marked, [], threshold=90) == [0, 1]


def test_near_identical_copies_count_as_one_text() -> None:
    marked = ["Charging the Widget", "Charging  the Widget"]
    assert sole_copies_to_restore(marked, [], threshold=90) == [0]


# --- the processor, on a minimal stand-in for Marker's document --------


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text
        self.structure: list[object] = []
        self.ignore_for_output = False

    def raw_text(self, document: object) -> str:
        return self.text


class _Page:
    def __init__(self, *blocks: _Block) -> None:
        self.blocks = list(blocks)

    def contained_blocks(self, document: object, block_types: object) -> list[_Block]:
        return self.blocks


def _pages_titled(title: str, n: int, *, extra: _Block | None = None) -> list[_Page]:
    pages = [_Page(_Block(title), _Block(f"body of page {i} " * 12)) for i in range(n)]
    if extra is not None:
        pages[0].blocks.insert(1, extra)
    return pages


def test_a_title_repeated_atop_every_page_keeps_its_first_copy() -> None:
    pages = _pages_titled("Using the Widget Menu", 5)
    IgnoreTextProcessor()(SimpleNamespace(pages=pages))
    assert [p.blocks[0].ignore_for_output for p in pages] == [False, True, True, True, True]


def test_a_running_header_with_a_copy_elsewhere_is_still_dropped() -> None:
    pages = _pages_titled("Owner's Manual", 5, extra=_Block("Owner's Manual"))
    IgnoreTextProcessor()(SimpleNamespace(pages=pages))
    assert all(p.blocks[0].ignore_for_output for p in pages)


def test_keep_sole_copy_off_restores_markers_own_behavior() -> None:
    pages = _pages_titled("Using the Widget Menu", 5)
    IgnoreTextProcessor({"IgnoreTextProcessor_keep_sole_copy": False})(SimpleNamespace(pages=pages))
    assert all(p.blocks[0].ignore_for_output for p in pages)


def test_markers_own_config_keys_still_reach_it() -> None:
    """Marker matches `IgnoreTextProcessor_*` keys by class name; a renamed
    subclass would silently drop the kwargs a document's conversion relies on."""
    proc = IgnoreTextProcessor({"IgnoreTextProcessor_max_streak": 100000})
    assert proc.max_streak == 100000


def test_processor_list_swaps_in_this_processor() -> None:
    from marker.converters.pdf import PdfConverter

    names = marker_processor_list(PdfConverter.default_processors)
    assert "pagespeak.backends._marker_ignoretext.IgnoreTextProcessor" in names
    assert "marker.processors.ignoretext.IgnoreTextProcessor" not in names
    assert len(names) == len(PdfConverter.default_processors)


def test_an_empty_text_is_never_kept() -> None:
    """A page number cleans to an empty text; keeping its first copy would leave
    a stray line."""
    assert sole_copies_to_restore(["", "", ""], ["body text"], threshold=90) == []


def test_a_block_hidden_before_this_step_stays_hidden() -> None:
    pages = _pages_titled("Using the Widget Menu", 5)
    hidden = _Block("A one-off note hidden by an earlier step")
    hidden.ignore_for_output = True
    pages[2].blocks.append(hidden)
    IgnoreTextProcessor()(SimpleNamespace(pages=pages))
    assert hidden.ignore_for_output is True


@pytest.mark.parametrize(
    "off",
    [
        "false",
        "False",
        " f ",
        "0",
        "0.0",
        "0x0",
        "nan",
        "no",
        "n",
        "off",
        "none",
        "null",
        "disabled",
        "",
    ],
)
def test_keep_sole_copy_given_as_text_false_is_off(off: str) -> None:
    pages = _pages_titled("Using the Widget Menu", 5)
    IgnoreTextProcessor({"IgnoreTextProcessor_keep_sole_copy": off})(SimpleNamespace(pages=pages))
    assert all(p.blocks[0].ignore_for_output for p in pages)


def test_a_match_at_exactly_the_threshold_is_not_a_copy() -> None:
    """Marker calls a text common only above `text_match_threshold`; this matches it."""
    assert sole_copies_to_restore(["abcdefghij"], ["abcdefghix"], threshold=90) == [0]
    assert sole_copies_to_restore(["abcdefghij"], ["abcdefghix"], threshold=89) == []
