"""Tests for services._verify_delivery — the delivered copy is the current build."""

from __future__ import annotations

import shutil
from pathlib import Path

from pagespeak.services._verify_delivery import check_delivery
from pagespeak.services._verify_doc import VerifyDoc


def _deliverable(root: Path) -> VerifyDoc:
    (root / "images").mkdir(parents=True)
    (root / "book.md").write_text("# Book\n\n![a](images/a.png)\n", encoding="utf-8")
    (root / "book.raw.md").write_text("# Book\n", encoding="utf-8")
    (root / "images" / "a.png").write_bytes(b"\x89PNG\r\n")
    (root / "sections").mkdir()
    (root / "sections" / "One.md").write_text("# One\n", encoding="utf-8")
    (root / "sections" / "INDEX.md").write_text("# Split\n", encoding="utf-8")
    return VerifyDoc(root, root / "book.md")


def test_the_delivered_copy_must_match_the_build(tmp_path: Path) -> None:
    doc = _deliverable(tmp_path / "out" / "book")
    dest = tmp_path / "delivery" / "book"
    shutil.copytree(doc.root, dest, ignore=shutil.ignore_patterns(".*", "*.raw.md"))
    assert check_delivery(doc, dest).findings == ()

    (dest / "book.md").write_text("# Book (old)\n", encoding="utf-8")
    (dest / "images" / "a.png").unlink()
    (dest / "sections" / "Old.md").write_text("# Old\n", encoding="utf-8")

    result = check_delivery(doc, dest)

    keys = [f.key for f in result.findings]
    assert keys == ["delivery_match:differs", "delivery_match:missing", "delivery_match:extra"]
    assert "images/a.png" in result.findings[1].message


def test_dot_files_on_either_side_are_not_compared(tmp_path: Path) -> None:
    doc = _deliverable(tmp_path / "out" / "book")
    dest = tmp_path / "delivery" / "book"
    shutil.copytree(doc.root, dest, ignore=shutil.ignore_patterns(".*", "*.raw.md"))
    (doc.root / "images" / ".DS_Store").write_bytes(b"\0")
    (doc.root / "sections" / ".pagespeak-verdict.md").write_text("# Verify\n", encoding="utf-8")
    (dest / "images" / ".DS_Store").write_bytes(b"\1")
    assert check_delivery(doc, dest).findings == ()


def test_other_documents_in_an_export_delivery_are_not_extra(tmp_path: Path) -> None:
    doc = _deliverable(tmp_path / "out" / "book")
    dest = tmp_path / "delivery" / "book"
    shutil.copytree(doc.root, dest, ignore=shutil.ignore_patterns(".*", "*.raw.md"))
    (dest / "exam-2").mkdir()
    (dest / "exam-2" / "exam-2.md").write_text("# Exam 2\n", encoding="utf-8")
    assert check_delivery(doc, dest).findings == ()


def test_delivery_is_skipped_when_there_is_none(tmp_path: Path) -> None:
    doc = _deliverable(tmp_path / "out" / "book")
    assert check_delivery(doc, None).skipped is not None
    assert check_delivery(doc, tmp_path / "delivery" / "book").skipped is not None
    (tmp_path / "delivery").mkdir()
    (tmp_path / "delivery" / "book.zip").write_bytes(b"PK")
    assert "book.zip" in (check_delivery(doc, tmp_path / "delivery" / "book").skipped or "")
