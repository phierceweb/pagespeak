"""Tests for backends._layout_fields."""

from __future__ import annotations

import re

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout_fields import Section

DATA = {
    "n": 3,
    "x": 2.5,
    "t": "word",
    "on": True,
    "list": ["a", "b"],
    "ints": [1, 2],
    "box": [1, 2.5, 3, 4],
    "pairs": [["a", "b"]],
    "inner": {"k": "v"},
    "many": [{"k": "v"}],
}
KEYS = tuple(DATA)


def section() -> Section:
    return Section(DATA, "top", (*KEYS, "absent"))


def test_each_reader_returns_its_value_typed() -> None:
    s = section()
    assert (s.whole("n"), s.num("n"), s.num("x"), s.text("t"), s.flag("on")) == (
        3,
        3.0,
        2.5,
        "word",
        True,
    )
    assert s.texts("list") == ("a", "b") and s.wholes("ints") == frozenset({1, 2})
    assert s.nums("box", 4) == [1.0, 2.5, 3.0, 4.0] and s.pairs("pairs") == (("a", "b"),)
    assert s.pattern("t", re.I).match("WORD")
    assert s.child("inner", ("k",)).text("k") == "v"
    assert [c.text("k") for c in s.children("many", ("k",))] == ["v"]


def test_optional_fields_fall_back_and_required_ones_are_named() -> None:
    s = section()
    assert s.opt_text("absent") is None and s.flag("absent") is False
    assert s.pairs("absent") == () and s.children("absent", ("k",)) == []
    assert s.child("absent", ("k",), optional=True).data == {}
    for read in (s.num, s.whole, s.text, s.texts, s.wholes):
        with pytest.raises(InvalidInputError, match=r"top\.absent is missing"):
            read("absent")
    with pytest.raises(InvalidInputError, match=r"top\.absent is missing"):
        s.child("absent", ("k",))
    with pytest.raises(InvalidInputError, match=r"top\.t must be a mapping"):
        s.child("t", ("k",))


@pytest.mark.parametrize(
    ("read", "key", "message"),
    [
        ("num", "t", "must be a number"),
        ("num", "on", "must be a number"),
        ("whole", "x", "must be a whole number"),
        ("whole", "on", "must be a whole number"),
        ("text", "n", "must be text"),
        ("flag", "n", "must be true or false"),
        ("texts", "ints", "must be a list of text"),
        ("texts", "t", "must be a list"),
        ("wholes", "list", "must be a list of whole numbers"),
        ("pairs", "list", r"\[0\] must be 2 texts"),
        ("pattern", "n", "must be text"),
    ],
)
def test_a_value_of_the_wrong_type_is_refused_by_name(read: str, key: str, message: str) -> None:
    with pytest.raises(InvalidInputError, match=rf"layout profile: top\.{key}.*{message}"):
        getattr(section(), read)(key)


def test_a_box_needs_its_count_of_numbers() -> None:
    s = section()
    for key, count in (("box", 3), ("list", 2), ("t", 4), ("absent", 4)):
        with pytest.raises(InvalidInputError, match=rf"top\.{key} must be {count} numbers"):
            s.nums(key, count)


def test_an_unknown_key_or_a_non_mapping_is_refused() -> None:
    with pytest.raises(InvalidInputError, match=r"top has unknown key\(s\): t, x"):
        Section(DATA, "top", tuple(k for k in KEYS if k not in ("t", "x")))
    with pytest.raises(InvalidInputError, match=r"the profile has unknown key\(s\): n"):
        Section({"n": 1}, "", ())
    with pytest.raises(InvalidInputError, match="top must be a mapping"):
        Section(["a"], "top", None)
    assert Section({"anything": 1}, "top", None).at("k") == "top.k"
    assert Section({}, "", None).at("k") == "k"


def test_a_bad_pattern_is_named() -> None:
    with pytest.raises(InvalidInputError, match=r"top\.t is not a valid pattern"):
        Section({"t": "(unclosed"}, "top", None).pattern("t")


@pytest.mark.parametrize("pattern", ["", ".*", "^(Note:)?", "x?"])
def test_a_pattern_that_matches_the_empty_string_is_refused_unless_allowed(pattern: str) -> None:
    s = Section({"t": pattern}, "top", None)
    with pytest.raises(InvalidInputError, match=r"top\.t matches the empty string"):
        s.pattern("t")
    assert s.pattern("t", blank_ok=True).pattern == pattern
    assert not Section({"t": "(?!)"}, "top", None).pattern("t").search("anything")


def test_empty_text_is_refused_where_a_word_is_wanted() -> None:
    s = Section({"e": "", "w": "x", "list": ["a", ""]}, "top", None)
    assert s.text("e") == "" and s.word("w") == "x"
    with pytest.raises(InvalidInputError, match=r"top\.e must not be empty"):
        s.word("e")
    with pytest.raises(InvalidInputError, match=r"top\.list must not hold an empty text"):
        s.words("list")
    assert Section({"list": ["a", "b"]}, "top", None).words("list") == ("a", "b")
