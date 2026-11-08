"""Tests for services._pictures."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._pictures import picture_report, render_report
from pagespeak.services._verify_doc import VerifyDoc


def _doc(tmp_path: Path, *, checkpoint: bool = True) -> VerifyDoc:
    from PIL import Image, ImageDraw

    from pagespeak.utils._phash import compute_phash

    root = tmp_path / "out" / "doc"
    (root / "images").mkdir(parents=True)
    # A different bar per picture, so no two share a perceptual hash.
    for i, (name, size) in enumerate(
        (("a.png", (300, 200)), ("b.png", (40, 40)), ("c.png", (64, 64)), ("unused.png", (50, 50)))
    ):
        im = Image.new("L", size, 255)
        w, h = size
        ImageDraw.Draw(im).rectangle([w * i // 4, 0, w * (i + 1) // 4, h], fill=0)
        im.save(root / "images" / name)
    text = (
        "# Doc\n\n![A wiring diagram of the input stage](images/a.png)\n\n"
        "![User-added image](images/b.png)\n\n![](images/c.png)\n"
    )
    (root / "doc.md").write_text("# Doc\n\n![captioned](images/a.png)\n", encoding="utf-8")
    if checkpoint:
        (root / "doc.structured.md").write_text(text, encoding="utf-8")
    cache = root / ".vision-cache"
    cache.mkdir()
    for cached in ("a.png", "unused.png"):  # a cache entry alone does not put a picture in the text
        (cache / f"{compute_phash(root / 'images' / cached)}.json").write_text("{}")
    return VerifyDoc(root, root / "doc.md")


def test_report_reads_labels_from_the_checkpoint_before_vision(tmp_path: Path) -> None:
    report = picture_report(_doc(tmp_path), in_dir=tmp_path / "in")
    by_name = {p.path.name: p for p in report.pictures}
    assert report.labels_from.name == "doc.structured.md"
    assert [p.path.name for p in report.referenced] == ["a.png", "b.png", "c.png"]
    assert by_name["unused.png"].referenced is False
    assert by_name["unused.png"].captioned is False
    assert by_name["a.png"].size == (300, 200)
    assert by_name["a.png"].captioned and not by_name["b.png"].captioned
    assert not by_name["a.png"].label_says_nothing
    assert by_name["b.png"].label_says_nothing and not by_name["b.png"].unlabelled
    assert by_name["c.png"].unlabelled and not by_name["c.png"].label_says_nothing


def test_report_falls_back_to_the_master_for_labels(tmp_path: Path) -> None:
    report = picture_report(_doc(tmp_path, checkpoint=False), in_dir=tmp_path / "in")
    assert report.labels_from.name == "doc.md"
    assert [p.path.name for p in report.referenced] == ["a.png"]


def test_picture_checks_say_why_they_did_not_run(tmp_path: Path) -> None:
    report = picture_report(_doc(tmp_path), in_dir=tmp_path / "in")
    assert {r.check for r in report.checks} == {"picture_coverage", "printed_titles"}
    assert all(not r.ran and "no source PDF" in (r.skipped or "") for r in report.checks)


def test_summary_counts_and_lists_silent_labels(tmp_path: Path) -> None:
    report = picture_report(_doc(tmp_path), in_dir=tmp_path / "in")
    text = render_report(report, tmp_path / "sheet.html")
    assert "3 pictures in the text, 1 more in images/ not in the text" in text
    assert "captions cached: 1; without one: 2" in text
    assert "with no label: 1" in text
    assert "images/b.png  'User-added image'" in text
    assert "picture_coverage: did not run" in text
    assert str(tmp_path / "sheet.html") in text


def test_summary_caps_the_list(tmp_path: Path) -> None:
    report = picture_report(_doc(tmp_path), in_dir=tmp_path / "in")
    text = render_report(report, tmp_path / "s.html", list_limit=0)
    assert "images/b.png" not in text
    assert "… and 1 more on the contact sheet" in text


def test_every_file_vision_may_send_is_listed(tmp_path: Path) -> None:
    from PIL import Image

    doc = _doc(tmp_path)
    (doc.images_dir / "meta.emf").write_bytes(b"not a raster")
    (doc.images_dir / "sub").mkdir()
    Image.new("L", (20, 20)).save(doc.images_dir / "sub" / "deep.png")
    (doc.images_dir / ".DS_Store").write_bytes(b"")
    text = "![Front panel controls](images/meta.emf)\n\n![Fig](images/sub/deep.png)\n"
    (doc.root / "doc.structured.md").write_text(text, encoding="utf-8")
    report = picture_report(doc, in_dir=tmp_path / "in")
    names = {p.path.relative_to(doc.images_dir).as_posix(): p for p in report.pictures}
    assert ".DS_Store" not in names
    assert "sub/deep.png" not in names  # vision sends only the top of images/
    assert names["meta.emf"].referenced and names["meta.emf"].size is None
    text = render_report(report, tmp_path / "s.html")
    assert "doc: 1 picture in the text, 4 more in images/ not in the text" in text
    assert "images/meta.emf" not in text  # "Front panel controls" describes it


def test_encoded_ref_counts_as_in_the_text(tmp_path: Path) -> None:
    from PIL import Image

    doc = _doc(tmp_path)
    Image.new("L", (20, 20)).save(doc.images_dir / "my shot.png")
    text = "![Settings screen](images/my%20shot.png?v=2)\n"
    (doc.root / "doc.structured.md").write_text(text, encoding="utf-8")
    report = picture_report(doc, in_dir=tmp_path / "in")
    shot = next(p for p in report.pictures if p.path.name == "my shot.png")
    assert shot.referenced and shot.label == "Settings screen"


def test_an_oversized_picture_does_not_stop_the_report(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    doc = _doc(tmp_path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    report = picture_report(doc, in_dir=tmp_path / "in")
    assert all(p.size is None and not p.captioned for p in report.pictures)
