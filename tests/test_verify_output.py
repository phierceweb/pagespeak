"""Tests for services._verify_output — picture links and pictures nothing shows."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_output import check_image_links, check_orphan_images
from tests.fixtures.pictures import picture


def _doc(root: Path, master: str) -> VerifyDoc:
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.md").write_text(master, encoding="utf-8")
    return VerifyDoc(root, root / "book.md")


def test_a_missing_picture_file_is_named_with_its_file(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path, "![a](images/here.png)\n\n![b](images/gone.png)\n![c](https://x.org/y.png)\n"
    )
    picture(tmp_path / "images" / "here.png", 0)
    section = tmp_path / "sections" / "1" / "One.md"
    section.parent.mkdir(parents=True)
    section.write_text("# One\n\n![b](../../images/gone2.png)\n", encoding="utf-8")

    result = check_image_links(doc)

    assert [f.where for f in result.findings] == ["book.md:3", "sections/1/One.md:3"]
    assert all(f.blocking for f in result.findings)
    assert "gone.png" in result.findings[0].message


def test_a_picture_outside_the_document_folder_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = picture(tmp_path / "in" / "src" / "fig.png", 0)
    doc = _doc(Path("out") / "book", f"![abs]({outside})\n\n![rel](../../in/src/fig.png)\n")
    result = check_image_links(doc)
    assert [f.where for f in result.findings] == ["book.md:1", "book.md:3"]
    assert all("outside the document folder" in f.message for f in result.findings)


def test_a_picture_in_the_folder_that_deliver_leaves_behind_fails(tmp_path: Path) -> None:
    targets = ["figures/a.png", "b.png", "images/.hidden.png", "images/d.png"]
    doc = _doc(tmp_path, "\n\n".join(f"![x]({t})" for t in targets) + "\n")
    for i, target in enumerate(targets):
        picture(tmp_path / target, i)
    result = check_image_links(doc)
    assert [f.where for f in result.findings] == ["book.md:1", "book.md:3", "book.md:5"]
    assert all("deliver leaves it behind" in f.message for f in result.findings)


def test_a_picture_named_in_another_letter_case_says_so(tmp_path: Path) -> None:
    picture(tmp_path / "images" / "a.png", 0)
    if not (tmp_path / "IMAGES" / "a.png").exists():
        pytest.skip("this disk tells letter cases apart, so the link is simply not found")
    doc = _doc(tmp_path, "![x](Images/a.png)\n")
    (finding,) = check_image_links(doc).findings
    assert "letter case" in finding.message
    assert "images/a.png" in finding.message


def test_uppercase_and_scheme_relative_urls_are_remote(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "![a](HTTPS://example.com/a.png)\n\n![b](//example.com/b.png)\n")
    assert check_image_links(doc).findings == ()


def test_an_unused_picture_is_a_note_unless_the_build_cut_it(tmp_path: Path) -> None:
    doc = _doc(tmp_path, '![a](images/a.png)\n\n```mermaid pagespeak-image="images/m.png"\n```\n')
    for i, name in enumerate(("a.png", "m.png", "unused.png")):
        picture(tmp_path / "images" / name, i)
    section = tmp_path / "sections" / "S.md"
    section.parent.mkdir()
    section.write_text("![a](../images/a.png)\n", encoding="utf-8")

    plain = check_orphan_images(doc, pictures=None)
    assert [(f.key, f.blocking) for f in plain.findings] == [("orphan_images:unused.png", False)]

    cut = check_orphan_images(doc, pictures={"unused.png"})
    assert [f.blocking for f in cut.findings] == [True]
