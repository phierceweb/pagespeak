"""Tests for services._verify_line_place — placing a PDF line among the output's words."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_line_place import OutputWords, tokens


def _words(tmp_path: Path, master: str) -> OutputWords:
    (tmp_path / "book.md").write_text(master, encoding="utf-8")
    return OutputWords.of(VerifyDoc(tmp_path, tmp_path / "book.md"))


def test_letters_set_apart_read_as_their_word() -> None:
    assert tokens("C H A P T E R twelve") == ["chapter", "twelve"]


def test_alt_text_and_mermaid_are_not_output_words(tmp_path: Path) -> None:
    master = "Body words here.\n\n![Alt words](a.png)\n\n```mermaid\nA --> B\n```\n"
    assert _words(tmp_path, master).words == ["body", "words", "here"]


def test_one_copy_serves_a_text_on_the_next_page_but_not_pages_later(tmp_path: Path) -> None:
    out = _words(tmp_path, "the keeper climbs the stairs at dusk every night\n")
    inner = tokens("keeper climbs the stairs at dusk every night")
    assert out.place(inner, 0, 1) == [1]
    assert out.place(inner, 0, 2) == [1]
    assert out.place(inner, 0, 4) is None


def test_a_title_over_every_page_a_table_runs_on_shares_one_copy(tmp_path: Path) -> None:
    out = _words(tmp_path, "the keeper climbs the stairs at dusk every night\n")
    inner = tokens("keeper climbs the stairs at dusk every night")
    assert [out.place(inner, 0, page) for page in (1, 2, 3, 4)] == [[1]] * 4
    assert out.place(inner, 0, 6) is None


def test_a_line_printed_twice_on_one_page_needs_two_copies(tmp_path: Path) -> None:
    out = _words(tmp_path, "the keeper climbs the stairs at dusk every night\n")
    inner = tokens("keeper climbs the stairs at dusk every night")
    assert out.place(inner, 0, 1) == [1]
    assert out.place(inner, 0, 1) is None


def test_a_line_whose_last_two_words_are_lost_is_not_placed(tmp_path: Path) -> None:
    out = _words(tmp_path, "the keeper is one of the most famous sailors on this coast\n")
    assert out.place(tokens("keeper is one of the most patient men"), 0, 1) is None


def test_a_line_whose_first_two_words_are_lost_is_not_placed(tmp_path: Path) -> None:
    out = _words(
        tmp_path, "the bell rings at noon when keeper climbs down the long stair to the quay\n"
    )
    inner = tokens("dawn the keeper climbs down the long stair to the quay")
    assert out.place(inner, 0, 1) is None


def test_a_line_with_one_word_dropped_from_the_output_is_placed(tmp_path: Path) -> None:
    out = _words(tmp_path, "the keeper climbs the stair at dusk every night\n")
    assert out.place(tokens("keeper climbs the long stair at dusk every night"), 0, 1) is not None
