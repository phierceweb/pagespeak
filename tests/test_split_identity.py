"""Direct unit tests for services._split_identity (frontmatter construction).

End-to-end behavior (through `split_into_sections`) is covered by
tests/test_split_write.py; these pin the field set and merge rules.
"""

from __future__ import annotations

from pagespeak.services._split_identity import (
    _section_frontmatter,
    _section_path,
    _strip_embedded_links,
)
from pagespeak.services._split_parse import _Section


def _make_section(
    title: str, level: int = 1, number: str | None = None, parent: _Section | None = None
) -> _Section:
    prefix = f"{number}. " if number else ""
    s = _Section(
        title=title,
        level=level,
        number=number,
        heading_line=f"{'#' * level} {prefix}{title}",
        content_lines=["body"],
    )
    s.parent = parent
    return s


def test_strip_embedded_links_idempotent() -> None:
    assert _strip_embedded_links("a[b](c)d") == "abd"
    assert _strip_embedded_links("plain") == "plain"


def test_section_path_walks_ancestors_root_first() -> None:
    root = _make_section("Root", level=1, number="1")
    child = _make_section("Child", level=2, number="1.1", parent=root)
    grand = _make_section("Grand", level=3, number="1.1.1", parent=child)
    assert _section_path(grand) == ["1. Root", "1.1. Child"]
    assert _section_path(root) == []


def test_frontmatter_structural_fields_without_provenance() -> None:
    root = _make_section("Root", number="1")
    child = _make_section("Child", level=2, number="1.1", parent=root)
    block = _section_frontmatter(
        child,
        None,
        doc_id="book",
        doc_title="Book",
        section_id="1/1.1. Child.md",
        parent_id="1/1. Root.md",
        order=2,
    )
    assert block.startswith("---\n")
    assert 'doc_id: "book"' in block
    assert 'section_id: "1/1.1. Child.md"' in block
    assert 'parent_id: "1/1. Root.md"' in block
    assert "depth: 1" in block
    assert "order: 2" in block
    assert "source_type" not in block


def test_frontmatter_none_fields_skipped() -> None:
    root = _make_section("Root", number="1")
    block = _section_frontmatter(
        root, None, doc_id="book", doc_title=None, section_id="1. Root.md", parent_id=None, order=1
    )
    assert "parent_id" not in block
    assert "doc_title" not in block
    assert "section_path" not in block


def test_frontmatter_provenance_doc_title_wins() -> None:
    root = _make_section("Root", number="1")
    block = _section_frontmatter(
        root,
        {"source_label": "Lbl", "doc_title": "From Prov"},
        doc_id="book",
        doc_title="From Param",
        section_id="1. Root.md",
        parent_id=None,
        order=1,
    )
    assert 'doc_title: "From Prov"' in block
    assert 'source_label: "Lbl"' in block


def test_frontmatter_source_identity_fields() -> None:
    root = _make_section("Root", number="1")
    block = _section_frontmatter(
        root,
        None,
        doc_id="book",
        doc_title=None,
        section_id="1. Root.md",
        parent_id=None,
        order=1,
        source_id="widget-guide-2e",
        source_sha256="c" * 64,
    )
    assert 'source_id: "widget-guide-2e"' in block
    assert f'source_sha256: "{"c" * 64}"' in block


def test_frontmatter_source_identity_omitted_when_none() -> None:
    root = _make_section("Root", number="1")
    block = _section_frontmatter(
        root, None, doc_id="book", doc_title=None, section_id="1. Root.md", parent_id=None, order=1
    )
    assert "source_id" not in block
    assert "source_sha256" not in block
