"""Tests for services._split_paths — section filename slugs."""

from __future__ import annotations

from pagespeak.services._split_paths import _sanitize_filename


def test_sanitize_filename_strips_markdown_breakers() -> None:
    """Filenames feed breadcrumb / Subsections link TARGETS, so pipes + brackets
    must be stripped there too (not just `/ \\ : * ? " < >`)."""
    out = _sanitize_filename("Widget 3 | Parts Tray [v2]")
    assert "|" not in out
    assert "[" not in out and "]" not in out


def test_sanitize_filename_punctuation_only_falls_back() -> None:
    """A degenerate heading (`## #`, `## ·`) sanitizes to a stem with no word
    content — `#.md` / `·.md`. Downstream indexers (QMD `handelize`) reject a
    filename with no valid content, so fall back to a generic stem."""
    assert _sanitize_filename("#") == "section.md"
    assert _sanitize_filename("·") == "section.md"
    assert _sanitize_filename("***") == "section.md"
    assert _sanitize_filename("   ") == "section.md"


def test_sanitize_filename_keeps_non_latin_word_content() -> None:
    """CJK / Cyrillic section names are valid content (Unicode word chars) and
    must NOT be clobbered by the punctuation-only fallback."""
    assert _sanitize_filename("产品注册") == "产品注册.md"
    assert _sanitize_filename("Благодарность") == "благодарность.md"
