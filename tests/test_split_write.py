"""Tests for services._split_write — the always-on relational section frontmatter.

Every written section file carries structure-derived identity fields
(doc_id / section_id / parent_id / order / depth) regardless of the opt-in
provenance source fields. This is the joinable-key layer for RAG consumers.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._split import split_into_sections

MD_NUMBERED = """# 1. Alpha

Alpha body text.

## 1.1. Beta

Beta body text.

## 1.2. Gamma

Gamma body text.
"""


def _read(paths: list[Path], name: str) -> str:
    matches = [p for p in paths if p.name == name]
    assert matches, f"{name} not in {[p.name for p in paths]}"
    return matches[0].read_text(encoding="utf-8")


def test_structural_frontmatter_always_on(tmp_path: Path) -> None:
    """No provenance args at all — sections still get the identity block."""
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out)
    assert written
    for p in written:
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{p.name} lacks frontmatter"
        assert 'doc_id: "guide-book"' in text
        # Source fields stay opt-in: never emitted without provenance.
        assert "source_type" not in text
        assert "source_label" not in text


def test_section_id_is_relative_path(tmp_path: Path) -> None:
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out, nested=True)
    beta = _read(written, "1-1-beta.md")
    assert 'section_id: "1/1-1-beta.md"' in beta
    alpha = _read(written, "1-alpha.md")
    assert 'section_id: "1/1-alpha.md"' in alpha


def test_parent_id_links_to_written_parent(tmp_path: Path) -> None:
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out, nested=True)
    beta = _read(written, "1-1-beta.md")
    assert 'parent_id: "1/1-alpha.md"' in beta
    # Root section has no written parent -> key omitted entirely.
    alpha = _read(written, "1-alpha.md")
    assert "parent_id" not in alpha


def test_parent_id_skips_unwritten_ancestor(tmp_path: Path) -> None:
    """An ancestor-only chapter (parsed below min_level, never written) is
    not a valid join target — the child emits no parent_id."""
    md = "# Book Chapter\n\n## Topic One\n\nTopic body text here.\n"
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(md, out, min_level=2)
    topic = _read(written, "topic-one.md")
    assert "parent_id" not in topic


def test_order_is_document_order(tmp_path: Path) -> None:
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out)
    assert "order: 1" in _read(written, "1-alpha.md")
    assert "order: 2" in _read(written, "1-1-beta.md")
    assert "order: 3" in _read(written, "1-2-gamma.md")


def test_depth_counts_ancestors(tmp_path: Path) -> None:
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out)
    assert "depth: 0" in _read(written, "1-alpha.md")
    assert "depth: 1" in _read(written, "1-1-beta.md")


def test_doc_id_param_overrides_derived(tmp_path: Path) -> None:
    written = split_into_sections(MD_NUMBERED, tmp_path / "sections", doc_id="my-custom-id")
    for p in written:
        assert 'doc_id: "my-custom-id"' in p.read_text(encoding="utf-8")


def test_provenance_fields_merge_with_structural(tmp_path: Path) -> None:
    """Opt-in source fields and the always-on identity fields coexist in one
    block; the provenance doc_title wins over the doc_title param."""
    out = tmp_path / "guide-book" / "sections"
    prov: dict[str, object] = {
        "source_type": "textbook",
        "source_label": "Guide Book",
        "doc_title": "From H1",
    }
    written = split_into_sections(MD_NUMBERED, out, provenance=prov, doc_title="From Param")
    text = _read(written, "1-1-beta.md")
    assert 'source_type: "textbook"' in text
    assert 'source_label: "Guide Book"' in text
    assert 'doc_title: "From H1"' in text
    assert 'doc_id: "guide-book"' in text
    assert "section_id:" in text


def test_doc_title_param_fills_when_no_provenance(tmp_path: Path) -> None:
    out = tmp_path / "guide-book" / "sections"
    written = split_into_sections(MD_NUMBERED, out, doc_title="Guide Book")
    assert 'doc_title: "Guide Book"' in _read(written, "1-alpha.md")
