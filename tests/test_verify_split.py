"""Tests for services._verify_split — the section files hold the master exactly once."""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._split import split_into_sections
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_split import _front_end, _parse, check_split

_BODY = """# Chapter 1 Towers

Opening paragraph of the chapter, before any section.

## Table of Contents

- [Chapter 1 Towers](#chapter-1-towers)
  - [1.1 Lamps](#11-lamps)

## 1.1 Lamps

The lamp is a ring of lenses. See [the lenses section](#12-lenses).

![Figure 1.1 A lamp](images/fig-1-1.png)

| Part | Role |
|---|---|
| Prism | Bends light |

## 1.2 Lenses

Each lens gathers the beam into a narrow band.

______

______

## 1.3 Empty

## 1.4 Horns

Horns sound in fog.
"""


def _build(root: Path, body: str = _BODY) -> VerifyDoc:
    root.mkdir(parents=True)
    (root / "images").mkdir()
    (root / "images" / "fig-1-1.png").write_bytes(b"\x89PNG\r\n")
    (root / "book.md").write_text("---\ndoc_id: book\n---\n" + body, encoding="utf-8")
    split_into_sections(
        body,
        root / "sections",
        nested=True,
        min_level=2,
        min_body_chars=1,
        doc_title="Book",
    )
    return VerifyDoc(root, root / "book.md")


def _section(doc: VerifyDoc, title: str) -> Path:
    return next(p for p in doc.section_files if title in p.read_text(encoding="utf-8"))


def test_the_splitters_own_output_conserves_the_master(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    result = check_split(doc)
    assert result.ran
    assert [f.message for f in result.findings] == []


def test_a_line_missing_from_every_section_blocks(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    path = _section(doc, "Horns sound in fog.")
    path.write_text(
        path.read_text(encoding="utf-8").replace("Horns sound in fog.", ""), encoding="utf-8"
    )

    result = check_split(doc)

    assert [f.key for f in result.findings] == ["split_conservation:lost:Horns sound in fog."]
    assert result.findings[0].blocking


def test_a_line_in_two_sections_blocks(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    path = _section(doc, "Horns sound in fog.")
    path.write_text(
        path.read_text(encoding="utf-8") + "\nEach lens gathers the beam into a narrow band.\n",
        encoding="utf-8",
    )

    result = check_split(doc)

    assert [f.key for f in result.findings] == [
        "split_conservation:repeated:Each lens gathers the beam into a narrow band."
    ]


def test_a_dropped_section_with_a_body_is_lost_content(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    _section(doc, "Each lens gathers").unlink()

    keys = [f.key for f in check_split(VerifyDoc(doc.root, doc.master)).findings]

    assert "split_conservation:heading:1.2 Lenses" in keys
    assert "split_conservation:lost:Each lens gathers the beam into a narrow band." in keys


def test_a_title_block_left_out_of_the_sections_is_a_note(tmp_path: Path) -> None:
    """Quiz splitters write one file per question and leave the title block out."""
    root = tmp_path / "quiz"
    (root / "sections").mkdir(parents=True)
    master = "# Quiz 1\n\n_8 questions_\n\n## Question 1\n\nWhich tower?\n"
    (root / "quiz.md").write_text(master, encoding="utf-8")
    (root / "sections" / "Question 001.md").write_text(
        "## Question 1\n\nWhich tower?\n", encoding="utf-8"
    )

    findings = check_split(VerifyDoc(root, root / "quiz.md")).findings

    assert {f.key for f in findings} == {
        "split_conservation:heading:Quiz 1",
        "split_conservation:lost:8 questions",
    }
    assert not any(f.blocking for f in findings)


def test_emphasis_and_generated_lists_are_not_differences(tmp_path: Path) -> None:
    root = tmp_path / "book"
    (root / "sections").mkdir(parents=True)
    master = "# Title\n\nIntro.\n\n## Folders\n\n**You** must read *this*.\n"
    (root / "book.md").write_text(master, encoding="utf-8")
    (root / "sections" / "Folders.md").write_text(
        "## Folders\n\n> ↑ [Title](INDEX.md)\n\n***You*** must read this.\n\n"
        "## Subsections\n\n- [Notes.txt [file]](folders/notes.md)\n- [Scripts]\n",
        encoding="utf-8",
    )
    (root / "sections" / "Title.md").write_text("# Title\n\nIntro.\n", encoding="utf-8")
    assert check_split(VerifyDoc(root, root / "book.md")).findings == ()


def test_a_boilerplate_line_with_one_copy_fewer_is_a_note(tmp_path: Path) -> None:
    root = tmp_path / "book"
    (root / "sections").mkdir(parents=True)
    master = "# A\n\nNote\n\nBody A.\n\n# B\n\nNote\n\nBody B.\n\nNote\n"
    (root / "book.md").write_text(master, encoding="utf-8")
    (root / "sections" / "A.md").write_text("# A\n\nNote\n\nBody A.\n", encoding="utf-8")
    (root / "sections" / "B.md").write_text("# B\n\nNote\n\nBody B.\n", encoding="utf-8")

    (finding,) = check_split(VerifyDoc(root, root / "book.md")).findings

    assert finding.key == "split_conservation:fewer:Note"
    assert not finding.blocking


def test_rewritten_link_tails_and_picture_headings_match(tmp_path: Path) -> None:
    root = tmp_path / "book"
    (root / "sections" / "help").mkdir(parents=True)
    master = (
        "# Title\n\nIntro.\n\n## ![logo](images/a.png) New device?\n\n"
        "Use the [Low\nBand](#low-band) and [High Band] menus.\n"
    )
    (root / "book.md").write_text(master, encoding="utf-8")
    (root / "sections" / "Title.md").write_text("# Title\n\nIntro.\n", encoding="utf-8")
    (root / "sections" / "help" / "device.md").write_text(
        "## ![logo](../../images/a.png) New device?\n\nUse the [Low\nBand](../bands/low-band.md) and [High Band] menus.\n",
        encoding="utf-8",
    )
    assert check_split(VerifyDoc(root, root / "book.md")).findings == ()


def test_a_contents_entry_the_splitter_drops_is_a_note(tmp_path: Path) -> None:
    root = tmp_path / "book"
    (root / "sections").mkdir(parents=True)
    master = "# Book\n\nIntro.\n\n## Contents\n\nList.\n\n## 8 Signal Paths 226\n\nFast Paths 227\n\n## Real\n\nBody.\n"
    (root / "book.md").write_text(master, encoding="utf-8")
    (root / "sections" / "Book.md").write_text("# Book\n\nIntro.\n", encoding="utf-8")
    (root / "sections" / "Contents.md").write_text("## Contents\n\nList.\n", encoding="utf-8")
    (root / "sections" / "Real.md").write_text("## Real\n\nBody.\n", encoding="utf-8")

    findings = check_split(VerifyDoc(root, root / "book.md")).findings

    assert {f.key for f in findings} == {
        "split_conservation:heading:8 Signal Paths 226",
        "split_conservation:lost:Fast Paths 227",
    }
    assert not any(f.blocking for f in findings)


def test_a_sections_folder_holding_only_its_index_loses_every_section(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    for path in doc.section_files:
        path.unlink()
    result = check_split(VerifyDoc(doc.root, doc.master))
    assert result.ran
    assert "split_conservation:lost:Horns sound in fog." in {
        f.key for f in result.findings if f.blocking
    }


def test_a_line_lost_from_a_title_block_the_sections_keep_blocks(tmp_path: Path) -> None:
    doc = _build(tmp_path / "book")
    opening = "Opening paragraph of the chapter, before any section."
    path = _section(doc, opening)
    path.write_text(path.read_text(encoding="utf-8").replace(opening, ""), encoding="utf-8")
    findings = check_split(VerifyDoc(doc.root, doc.master)).findings
    assert [(f.key, f.blocking) for f in findings] == [(f"split_conservation:lost:{opening}", True)]


def test_a_title_block_lost_under_a_title_its_breadcrumbs_cut_short_blocks(tmp_path: Path) -> None:
    """The splitter cuts a breadcrumb at 50 characters; the cut title still names the block."""
    title = "Chapter 1 Towers, Lamps and Horns of the Northern Lighthouses"
    doc = _build(tmp_path / "book", _BODY.replace("Chapter 1 Towers", title))
    opening = "Opening paragraph of the chapter, before any section."
    _section(doc, opening).unlink()
    findings = check_split(VerifyDoc(doc.root, doc.master)).findings
    assert (f"split_conservation:lost:{opening}", True) in [(f.key, f.blocking) for f in findings]


def test_only_a_breadcrumb_the_splitter_cut_short_stands_for_a_longer_title() -> None:
    master = _parse(
        "# Lamps and Lenses\n\nThe lamp burns.\n\n## Wicks\n\nTrim them.\n", section=False
    )
    whole = _parse("> ↑ [Lamps](a.md)\n\n## Wicks\n\nTrim them.\n", section=True)
    cut = _parse("> ↑ [Lamps and Le…](a.md)\n\n## Wicks\n\nTrim them.\n", section=True)
    assert _front_end(master, whole) == master.headings[1].line
    assert _front_end(master, cut) == master.headings[0].line


def test_english_only_makes_a_lost_line_a_note(tmp_path: Path) -> None:
    """English-only leaves non-English branches out of the sections on purpose."""
    doc = _build(tmp_path / "book")
    record = {"resolved_flags": {"english_only": True}}
    (doc.root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    path = _section(doc, "Horns sound in fog.")
    path.write_text(
        path.read_text(encoding="utf-8").replace("Horns sound in fog.", ""), encoding="utf-8"
    )
    (finding,) = check_split(VerifyDoc(doc.root, doc.master)).findings
    assert (finding.key, finding.blocking) == ("split_conservation:lost:Horns sound in fog.", False)


def test_no_sections_means_nothing_to_check(tmp_path: Path) -> None:
    root = tmp_path / "book"
    root.mkdir()
    (root / "book.md").write_text("# Book\n", encoding="utf-8")
    assert check_split(VerifyDoc(root, root / "book.md")).skipped == "no sections/ folder"
