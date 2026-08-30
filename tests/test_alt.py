"""Tests for `flatten_alt` — the alt-text normalizer both ref-construction
sites share. Its contract is asserted here, not only through its callers.
"""

from __future__ import annotations

from pagespeak.services._cleanup_regexes import IMAGE_ONLY_RE
from pagespeak.services._image_refs import parse_image_refs
from pagespeak.utils._alt import flatten_alt


def test_blank_line_is_collapsed_so_the_ref_parses() -> None:
    alt = flatten_alt("A diagram of a company\n\nDescription automatically generated")
    refs = parse_image_refs(f"![{alt}](images/a.png)\n")
    assert [r.target for r in refs] == ["images/a.png"]


def test_single_line_alt_is_unchanged() -> None:
    assert flatten_alt("A widget") == "A widget"


def test_runs_of_whitespace_collapse_to_one_space() -> None:
    assert flatten_alt("left\t\r\n  right") == "left right"


def test_empty_alt_stays_empty() -> None:
    assert flatten_alt("") == ""


def test_whitespace_only_alt_keeps_a_space() -> None:
    """Emptying it would make the ref match `IMAGE_ONLY_RE`, and aggressive
    cleanup deletes those as decoration — losing the image."""
    assert flatten_alt("   ") == " "
    assert not IMAGE_ONLY_RE.match(f"![{flatten_alt('   ')}](images/a.png)")


def test_non_breaking_space_is_normalized() -> None:
    assert flatten_alt("a b") == "a b"
