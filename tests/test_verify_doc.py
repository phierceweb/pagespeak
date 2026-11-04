"""Tests for services._verify_doc — which converted documents verify checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.services._verify_doc import (
    default_in_dir,
    delivery_dir,
    find_documents,
    strip_frontmatter,
)


def _doc(root: Path, stem: str = "book") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{stem}.md").write_text("# Book\n", encoding="utf-8")
    (root / f"{stem}.raw.md").write_text("# Book\n", encoding="utf-8")
    (root / f"{stem}.visioned.md").write_text("# Book\n", encoding="utf-8")
    return root


def test_a_folder_holding_two_masters_is_refused(tmp_path: Path) -> None:
    root = _doc(tmp_path / "out" / "book")
    (root / "book.orig.md").write_text("# Old\n", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="book.orig.md"):
        find_documents(root)


def test_a_file_or_a_sections_folder_holds_no_document(tmp_path: Path) -> None:
    root = _doc(tmp_path / "out" / "book")
    (root / "sections").mkdir()
    (root / "sections" / "One.md").write_text("# One\n", encoding="utf-8")
    assert find_documents(root / "sections") == []
    with pytest.raises(InvalidInputError):
        find_documents(root / "book.md")


def test_a_dot_file_in_sections_is_not_a_section(tmp_path: Path) -> None:
    root = _doc(tmp_path / "out" / "book")
    (root / "sections").mkdir()
    (root / "sections" / "One.md").write_text("# One\n", encoding="utf-8")
    (root / "sections" / ".pagespeak-verdict.md").write_text("# Verify\n", encoding="utf-8")
    (doc,) = find_documents(root)
    assert [p.name for p in doc.section_files] == ["One.md"]


def test_a_document_dir_is_its_master_not_its_checkpoints(tmp_path: Path) -> None:
    docs = find_documents(_doc(tmp_path / "out" / "book"))
    assert [d.master.name for d in docs] == ["book.md"]


def test_an_export_is_walked_into_each_document(tmp_path: Path) -> None:
    export = tmp_path / "out" / "exams"
    _doc(export / "exam-1", "exam-1")
    _doc(export / "exam-2", "exam-2")
    assert [d.root.name for d in find_documents(export)] == ["exam-1", "exam-2"]


def test_dot_files_and_working_dirs_are_not_documents(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / ".pagespeak-verdict.md").write_text("# Verify\n", encoding="utf-8")
    for sub in ("images", "sections", "chunks", ".vision-cache"):
        _doc(root / sub, "inner")
    assert [d.master.name for d in find_documents(root)] == ["book.md"]


def test_section_files_leave_out_the_index(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / "sections" / "1").mkdir(parents=True)
    (root / "sections" / "INDEX.md").write_text("# Split\n", encoding="utf-8")
    (root / "sections" / "1" / "1.1. Towers.md").write_text("# Towers\n", encoding="utf-8")
    (doc,) = find_documents(root)
    assert [p.name for p in doc.section_files] == ["1.1. Towers.md"]


def test_flags_come_from_the_run_record(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    record = {"version": "0.20.0", "resolved_flags": {"diagrams": True}}
    (root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    (doc,) = find_documents(root)
    assert doc.flags == {"diagrams": True}
    assert doc.checkpoint(".visioned.md") == root / "book.visioned.md"
    assert doc.checkpoint(".structured.md") is None


def test_flags_are_empty_without_a_run_record(tmp_path: Path) -> None:
    (doc,) = find_documents(_doc(tmp_path / "book"))
    assert doc.flags == {}


def test_delivery_dir_mirrors_the_last_out_folder(tmp_path: Path) -> None:
    root = tmp_path / "conversions" / "out" / "exams" / "exam-1"
    assert delivery_dir(root) == tmp_path / "conversions" / "delivery" / "exams" / "exam-1"
    assert delivery_dir(tmp_path / "elsewhere" / "book") is None


def test_the_folders_beside_out_are_found_from_inside_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _doc(tmp_path / "conversions" / "out" / "book")
    monkeypatch.chdir(root)
    assert default_in_dir(Path(".")) == tmp_path / "conversions" / "in"
    assert delivery_dir(Path(".")) == tmp_path / "conversions" / "delivery" / "book"
    assert default_in_dir(Path("../book")) == tmp_path / "conversions" / "in"


def test_strip_frontmatter() -> None:
    assert strip_frontmatter("---\ndoc_id: x\n---\n# Title\nbody\n") == "# Title\nbody\n"
    assert strip_frontmatter("# Title\n---\nbody\n") == "# Title\n---\nbody\n"
