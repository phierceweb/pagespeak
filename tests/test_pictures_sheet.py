"""Tests for services._pictures_sheet."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._pictures import Picture, PictureReport
from pagespeak.services._pictures_sheet import SHEET_FILENAME, render_sheet, write_sheet
from pagespeak.services._verify_doc import VerifyDoc


def _report(tmp_path: Path) -> PictureReport:
    images = tmp_path / "images"
    doc = VerifyDoc(tmp_path, tmp_path / "doc.md")
    pictures = (
        Picture(images / "my shot.png", True, "<script>x</script> step", (300, 200), True),
        Picture(images / "b.png", True, "User-added image", None, False),
        Picture(images / "c.png", True, "", (10, 10), False),
        Picture(images / "logo.png", False, "", (20, 20), False),
    )
    return PictureReport(doc, tmp_path / "doc.structured.md", pictures, ())


def test_sheet_groups_pictures_and_escapes_text(tmp_path: Path) -> None:
    html = render_sheet(_report(tmp_path))
    silent = html.index("with no label or one that says nothing (2)")
    labelled = html.index("In the text (1)")
    unused = html.index("not in the text (1)")
    assert silent < labelled < unused
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert 'src="images/my%20shot.png"' in html
    assert "300×200" in html and "size unknown" in html
    assert html.count("label says nothing</span>") == 1
    assert html.count("no label</span>") == 1
    assert html.count("caption cached</span>") == 1


def test_sheet_is_written_beside_the_master(tmp_path: Path) -> None:
    path = write_sheet(_report(tmp_path))
    assert path == tmp_path / SHEET_FILENAME
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")
