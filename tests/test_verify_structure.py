"""Tests for services._verify_structure — heading and table shape notes."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._pdf_lines import OutlineEntry
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_structure import check_outline, check_structure


def _doc(tmp_path: Path, master: str) -> VerifyDoc:
    (tmp_path / "book.md").write_text(master, encoding="utf-8")
    return VerifyDoc(tmp_path, tmp_path / "book.md")


def test_structure_findings_are_notes(tmp_path: Path) -> None:
    master = (
        "# Book\n\nIntro.\n\n### Skipped a level\n\nText.\n\n## Shell\n\n## Parent\n\n### Child\n\nBody.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 | 3 |\n\n```\n# not a heading\n```\n"
    )
    findings = check_structure(_doc(tmp_path, master)).findings

    assert [(f.check, f.key) for f in findings] == [
        ("structure", "structure:skip:Skipped a level"),
        ("structure", "structure:empty:Shell"),
        ("structure", "structure:table:| 1 | 2 | 3 |"),
    ]
    assert not any(f.blocking for f in findings)


def test_frontmatter_is_not_read_as_a_table_or_heading(tmp_path: Path) -> None:
    master = "---\ndoc_id: book\n---\n# Book\n\nBody.\n"
    assert check_structure(_doc(tmp_path, master)).findings == ()


def test_line_numbers_count_the_frontmatter(tmp_path: Path) -> None:
    master = "---\ndoc_id: book\n---\n# Book\n\n### Deep\n\nBody.\n"
    (finding,) = check_structure(_doc(tmp_path, master)).findings
    assert finding.where == "book.md:6"


_OUTLINE = [
    OutlineEntry(0, "Chapter 1 Towers", 3),
    OutlineEntry(1, "1.1 Lamps", 4),
    OutlineEntry(1, "1.2 Lenses", 5),
    OutlineEntry(1, "1.3 Horns", 6),
]


def test_outline_entries_found_as_headings_pass(tmp_path: Path) -> None:
    master = "# 1 Towers\n\n## 1.1. Lamps\n\nText.\n\n## Lenses\n\nText.\n\n## 1.3 Horns\n\nText.\n"
    result = check_outline(_doc(tmp_path, master), _OUTLINE, claimed_pages={3, 4, 5, 6})
    assert result.findings == ()


def test_an_entry_in_the_text_but_not_a_heading_is_a_note(tmp_path: Path) -> None:
    master = "# 1 Towers\n\n## 1.1 Lamps\n\n1.2 Lenses\n\nText.\n\n## 1.3 Horns\n"
    (finding,) = check_outline(
        _doc(tmp_path, master), _OUTLINE, claimed_pages={3, 4, 5, 6}
    ).findings
    assert finding.key == "outline:not_heading:1.2 Lenses"
    assert not finding.blocking


def test_an_entry_found_nowhere_is_a_note(tmp_path: Path) -> None:
    master = "# 1 Towers\n\n## 1.1 Lamps\n\n## 1.2 Lenses\n\nText.\n"
    findings = check_outline(_doc(tmp_path, master), _OUTLINE, claimed_pages={3, 4, 5, 6}).findings
    assert [(f.key, f.blocking) for f in findings] == [("outline:missing:1.3 Horns", False)]


def test_a_bookmark_with_words_run_together_still_matches(tmp_path: Path) -> None:
    outline = [OutlineEntry(1, "4.1a Structural Layout: Frontand Rear Systems", 3)]
    master = "## 4.1a Structural Layout: Front and Rear Systems\n\nText.\n"
    assert check_outline(_doc(tmp_path, master), outline, claimed_pages=None).findings == ()


def test_entries_on_pages_the_build_did_not_read_are_skipped(tmp_path: Path) -> None:
    master = "# 1 Towers\n\n## 1.1 Lamps\n\n## 1.2 Lenses\n\nText.\n"
    assert check_outline(_doc(tmp_path, master), _OUTLINE, claimed_pages={3, 4, 5}).findings == ()


def test_no_outline_means_the_check_did_not_run(tmp_path: Path) -> None:
    assert check_outline(_doc(tmp_path, "# A\n"), [], claimed_pages=None).skipped is not None
