"""Tests for services._table_words — the wording a table splice must keep."""

from __future__ import annotations

import pytest

from pagespeak.services._table_words import absorbs_other_table, lost_words, table_words


def test_ligatures_trailing_dots_and_breaks_are_not_lost() -> None:
    assert lost_words("| Lens | A wide ﬁeld.<br>Clear |", "| Lens | A wide field Clear |") == ()


def test_every_script_and_single_character_values_count() -> None:
    marker = "| Größe | 名前 | Значение | Channels | 2 | Mode | A |"
    docling = "| | | | Channels | | Mode | |"
    assert lost_words(marker, docling) == ("2", "a", "größe", "значение", "名前")


@pytest.mark.parametrize(
    ("marker", "docling"),
    [
        ("| Area | 10 m<sup>2</sup> |", "| Area | 10 m2 |"),
        ("| Area | 10 m<SUP>2</SUP> |", "| Area | 10 m² |"),
        ("| Scale | 10<sup>3</sup> |", "| Scale | 10³ |"),
        ("| Pins | Power &amp; ground |", "| Pins | Power & ground |"),
        ("| Size | 2 $\\times$ 3 |", "| Size | 2 × 3 |"),
        ("| Size | 5 $\\mu$m |", "| Size | 5 µm |"),
        ("| See | [Setup](#page-3-0) |", "| See | Setup |"),
        ("| <b>Mode</b> | Auto |", "| Mode | Auto |"),
        ("| Pin | a<BR />b |", "| Pin | a b |"),
        ("| Count | 1,000 |", "| Count | 1000 |"),
        ("| Temp | −5 |", "| Temp | -5 |"),
    ],
)
def test_markup_is_not_wording(marker: str, docling: str) -> None:
    assert lost_words(marker, docling) == ()


@pytest.mark.parametrize(
    ("marker", "docling"),
    [
        ("| Use | recom-<br>mended |", "| Use | recommended |"),
        ("| Use | re-<br>commended co-<br/>operate |", "| Use | recommended cooperate |"),
        ("| Drug | recom- |\n| name | mended |", "| Drug name | recommended |"),
    ],
)
def test_a_word_a_hyphen_split_at_a_line_break_counts_whole(marker: str, docling: str) -> None:
    assert lost_words(marker, docling) == ()


@pytest.mark.parametrize(
    ("marker", "docling", "lost"),
    [
        ("| Plug | in |", "| Plug | inserted |", ("in",)),
        ("| Fan | Off |", "| Fan | Office |", ("off",)),
        ("| Speed | 120 |", "| Speed | 1200 |", ("120",)),
        ("| A10 | 100 W | 2100 W |", "| A10 | W | 2100 W |", ("100",)),
        ("| Fuse | Do not replace |", "| Fuse | Do replace |", ("not",)),
        ("| Knob | Sets tone |", "| Knob | Sets hot one |", ("tone",)),
        ("| N | 1 | 2 |", "| N | 12 |", ("1", "2")),
        ("| Type | I<br>II<br>III<br>IV |", "| Type | I |\n| III |\n| IV |", ("ii",)),
        ("| Group | A<br>B<br>AB<br>O |", "| Group | A |\n| AB |\n| O |", ("b",)),
        ("| Area | 10 m2 |", "| Area | 10 m 2 |", ("m2",)),
        ("| Use | recom-<br>mended | recom |", "| Use | recommended |", ("recom",)),
    ],
)
def test_a_word_hidden_in_other_words_is_still_lost(marker: str, docling: str, lost: tuple) -> None:
    assert lost_words(marker, docling) == lost


@pytest.mark.parametrize(
    ("marker", "docling", "lost"),
    [
        (
            "| Glucose | <100 normal, >126 high |",
            "| Glucose | 126 high |",
            ("<100", ">126", "normal"),
        ),
        ("| Temp | -5 |", "| Temp | 5 |", ("-5",)),
        ("| Index | x[0](first) |", "| Index | x[0] |", ("first",)),
        ("| Rule | $a \\not= b$ |", "| Rule | a = b |", ("not",)),
    ],
)
def test_text_that_looks_like_markup_is_wording(marker: str, docling: str, lost: tuple) -> None:
    assert lost_words(marker, docling) == lost


@pytest.mark.parametrize(
    ("marker", "word"),
    [
        ("| Path | C:\\Users\\Admin\\Setup |", "users"),
        ("| 0 <i | lower bound |\n| Pressure | must stay low |\n| j > 5 | upper |", "pressure"),
    ],
)
def test_backslashes_and_stray_brackets_hide_no_words(marker: str, word: str) -> None:
    assert word in table_words(marker)


def test_a_table_carrying_a_neighbours_own_words_absorbs_it() -> None:
    first = "| Control | Use |\n| Power switch | Toggles the widget |"
    second = "| Control | Use |\n| Mute button | Silences output |"
    merged = f"{first}\n| Mute button | Silences output |"
    assert absorbs_other_table(first, merged, [second])
    assert not absorbs_other_table(first, first, [second])
    assert not absorbs_other_table(first, merged, ["| Control | Use |"])


def test_half_of_a_neighbours_own_words_is_enough() -> None:
    """The neighbour's words the original shares (its header) don't count."""
    first = "| Control | Use |\n| Power switch | Toggles the widget |"
    second = "| Control | Use |\n| Mute | Silences |"
    assert absorbs_other_table(first, f"{first}\n| Mute | |", [second])
    assert not absorbs_other_table(first, f"{first}\n| Dim | |", [second])


@pytest.mark.parametrize(
    ("marker", "docling", "lost"),
    [
        ("| Export | ✓ |\n| Print | ✗ |", "| Export | |\n| Print | |", ("✓", "✗")),
        ("| Price | $5 | 50% |", "| Price | 5 | 50 |", ("$", "%")),
        ("| Price | $5 or $10 |", "| Price | 5 or 10 |", ("$",)),
        ("| pH | 7.4 | 4.7 |", "| pH | 7.4 | |", ("4.7",)),
        ("| Range | <LLN or >ULN |", "| Range | ULN |", ("<", ">", "lln", "or")),
        ("| Run | convert <input> |", "| Run | convert |", ("<", ">", "input")),
        ("| Set | a <i and j> b |", "| Set | a b |", ("<", ">", "and", "i", "j")),
        ("| Temp | < 5 |", "| Temp | 5 |", ("<5",)),
        ("| Temp | ‒5 |", "| Temp | 5 |", ("-5",)),
    ],
)
def test_symbols_numbers_and_bracketed_words_count(marker: str, docling: str, lost: tuple) -> None:
    assert lost_words(marker, docling) == lost


def test_a_dropped_row_whose_values_recur_elsewhere_is_lost() -> None:
    marker = "| mg | mL |\n| 1 | 0.5 |\n| 10 | 5.0 |\n| 50 | 10.0 |\n| 5 | 1.0 |"
    docling = "| mg | mL |\n| 1 | 0.5 |\n| 50 | 10.0 |\n| 5 | 1.0 |"
    assert lost_words(marker, docling) == ("10", "5.0")


@pytest.mark.parametrize(
    ("marker", "docling"),
    [
        ("| N | 1 000 |", "| N | 1000 |"),
        ("| Gas | $\\mathrm{CO}_2$ |", "| Gas | CO2 |"),
        ("| Scale | $10^{-3}$ |", "| Scale | 10⁻³ |"),
        ("| Emph | _italic_ |", "| Emph | italic |"),
        ('| <span id="p">Set</span>up |', "| Setup |"),
        ("| a<p>b |", "| a b |"),
        ("| See | [Home](/index) |", "| See | Home |"),
    ],
)
def test_more_markup_is_not_wording(marker: str, docling: str) -> None:
    assert lost_words(marker, docling) == ()


def test_a_latex_command_with_a_symbols_name_as_prefix_is_not_that_symbol() -> None:
    assert table_words("| \\pmatrix x |") == {"pmatrix", "x"}


def test_a_hyphen_split_counts_whole_only_when_the_replacement_has_the_word() -> None:
    marker = "| A |\n|---|\n| recom-<br>mended |"
    assert lost_words(marker, "| A |\n|---|\n| other |") == ("mended", "recom")


def test_a_half_rejoins_once() -> None:
    """`fix` closes `pre-` into `prefix`; it is not there again to open `fixes`."""
    marker = "| W |\n| pre- |\n| fix- |\n| es |"
    assert lost_words(marker, "| W |\n| prefix | fixes |") == ("es",)


def test_a_neighbour_repeating_the_originals_rows_is_absorbed_too() -> None:
    first = "| K | V |\n| Alpha | one |\n| Beta | two |"
    repeat = "| K | V |\n| Alpha | one |"
    assert absorbs_other_table(first, f"{first}\n| Alpha | one |", [repeat])


@pytest.mark.parametrize(
    ("marker", "docling", "lost"),
    [
        ("| Wi-Fi | yes |\n| Radio | yes |", "| Wi-Fi | yes |\n| Radio | |", ("yes",)),
        ("| a | 10 |\n| b | 10 |", "| a | 10 |\n| b | |", ("10",)),
    ],
)
def test_a_value_lost_once_counts_though_it_appears_again(
    marker: str, docling: str, lost: tuple
) -> None:
    assert lost_words(marker, docling) == lost
