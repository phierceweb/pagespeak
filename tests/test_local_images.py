"""Tests for backends/_local_images.py — sibling-image localization.

A saved-webpage / doc-site HTML bundle ships `doc.html` + a sibling
`images/` dir. These tests cover the copy-into-output pass that makes those
files visible to the vision phase's `<out>/images/` glob.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.backends._local_images import localize_local_images_in_markdown

_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepixels"


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Source doc + sibling `images/foo.webp`, plus a separate output dir."""
    src_dir = tmp_path / "bundle"
    (src_dir / "images").mkdir(parents=True)
    src = src_dir / "doc.html"
    src.write_text("<html></html>", encoding="utf-8")
    (src_dir / "images" / "foo.webp").write_bytes(_PNG)
    out = tmp_path / "out"
    out.mkdir()
    return src, out


def test_sibling_images_ref_copied_ref_unchanged(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    md = "![fig](images/foo.webp)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert rewritten == md  # already the canonical out-relative form
    assert (out / "images" / "foo.webp").read_bytes() == _PNG
    assert out / "images" / "foo.webp" in images


def test_non_canonical_ref_copied_and_retargeted(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    assets = src.parent / "assets"
    assets.mkdir()
    (assets / "bar.png").write_bytes(_PNG)
    md = "![fig](assets/bar.png)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert "](images/assets-bar.png)" in rewritten
    assert (out / "images" / "assets-bar.png").read_bytes() == _PNG
    assert out / "images" / "assets-bar.png" in images


def test_nested_images_ref_flattened(tmp_path: Path) -> None:
    """`images/sub/x.webp` flattens: the vision glob is non-recursive."""
    src, out = _bundle(tmp_path)
    sub = src.parent / "images" / "sub"
    sub.mkdir()
    (sub / "x.webp").write_bytes(_PNG)
    md = "![fig](images/sub/x.webp)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert "](images/sub-x.webp)" in rewritten
    assert (out / "images" / "sub-x.webp").exists()


def test_out_equals_in_no_copy_onto_self(tmp_path: Path) -> None:
    src, _ = _bundle(tmp_path)
    out = src.parent  # converting in place
    md = "![fig](images/foo.webp)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert rewritten == md
    assert out / "images" / "foo.webp" in images
    assert (out / "images" / "foo.webp").read_bytes() == _PNG  # intact


def test_traversal_ref_skipped(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    secret = tmp_path / "secret.png"
    secret.write_bytes(_PNG)
    md = "![fig](../secret.png)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert rewritten == md  # ref kept
    assert not (out / "images").exists() or not list((out / "images").glob("*"))
    assert images == []


def test_missing_file_ref_skipped(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    md = "![fig](images/nope.png)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert rewritten == md
    assert images == []


def test_toggle_off_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_COPY_LOCAL_IMAGES", "0")
    src, out = _bundle(tmp_path)
    md = "![fig](images/foo.webp)\n"
    rewritten, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert rewritten == md
    assert images == []
    assert not (out / "images").exists()


def test_duplicate_refs_copied_once(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    md = "![a](images/foo.webp)\n\n![b](images/foo.webp)\n"
    _, images = localize_local_images_in_markdown(md, out, source_path=src)
    assert images.count(out / "images" / "foo.webp") == 1


def test_merge_dedupes_against_passed_images(tmp_path: Path) -> None:
    src, out = _bundle(tmp_path)
    dest = out / "images" / "foo.webp"
    md = "![fig](images/foo.webp)\n"
    _, images = localize_local_images_in_markdown(md, out, source_path=src, images=[dest])
    assert images == [dest]


def test_md_source_end_to_end_via_pipeline(tmp_path: Path) -> None:
    """Integration: a .md source with a sibling images/ dir gets its images
    co-located by the real pipeline (no mocks), so vision could see them."""
    from pagespeak import to_markdown

    src_dir = tmp_path / "bundle"
    (src_dir / "images").mkdir(parents=True)
    src = src_dir / "notes.md"
    src.write_text("# Notes\n\n![fig](images/foo.webp)\n", encoding="utf-8")
    (src_dir / "images" / "foo.webp").write_bytes(_PNG)
    out = tmp_path / "out"
    result = to_markdown(src, output_dir=out, diagrams=False, cleanup="off")
    assert (out / "images" / "foo.webp").read_bytes() == _PNG
    assert out / "images" / "foo.webp" in result.images
