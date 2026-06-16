"""Tests for backends._markdown — the markdown/text passthrough backend."""

from __future__ import annotations

from pathlib import Path

from pagespeak.backends._markdown import convert_markdown


def test_convert_markdown_preserves_content_verbatim(tmp_path: Path) -> None:
    """A markdown deliverable is already the target format: pass it through byte-for-byte."""
    src = tmp_path / "doc.md"
    body = "# Title\n\nSome **bold** prose.\n\n- a\n- b\n\n## Section\n\nMore.\n"
    src.write_text(body, encoding="utf-8")

    result = convert_markdown(src)

    assert result.markdown == body


def test_convert_markdown_extracts_no_images(tmp_path: Path) -> None:
    """Remote image refs are localized later (cleanup); the backend extracts nothing."""
    src = tmp_path / "doc.md"
    src.write_text("# Title\n\n![remote](https://example.com/a.png)\n", encoding="utf-8")

    result = convert_markdown(src)

    assert result.images == []


def test_convert_markdown_reports_source_format(tmp_path: Path) -> None:
    src = tmp_path / "doc.markdown"
    src.write_text("# Title\n", encoding="utf-8")

    result = convert_markdown(src)

    assert result.source_format == "markdown"


def test_convert_markdown_preserves_unicode(tmp_path: Path) -> None:
    """Non-ASCII content (accents, CJK, emoji) survives the round-trip."""
    src = tmp_path / "doc.md"
    body = "# Café ☕ — 日本語\n\nEmoji 🚀 and accents é.\n"
    src.write_text(body, encoding="utf-8")

    result = convert_markdown(src)

    assert result.markdown == body


def test_convert_markdown_handles_empty_file(tmp_path: Path) -> None:
    src = tmp_path / "empty.md"
    src.write_text("", encoding="utf-8")

    result = convert_markdown(src)

    assert result.markdown == ""
    assert result.images == []
