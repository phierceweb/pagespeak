"""Tests for services._image_files."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._image_files import image_files


def test_image_files_lists_top_level_files_only(tmp_path: Path) -> None:
    images = tmp_path / "images"
    (images / "sub").mkdir(parents=True)
    for name in ("b.svg", "a.png", ".DS_Store", "sub/deep.png", "c.tif"):
        (images / name).write_bytes(b"x")
    (images / ".thumbs").mkdir()
    assert [p.name for p in image_files(images)] == ["a.png", "b.svg", "c.tif"]


def test_image_files_of_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert image_files(tmp_path / "images") == []
