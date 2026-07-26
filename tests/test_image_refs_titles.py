"""Titled image refs — `![alt](path "title")`.

The CommonMark title is not part of the destination; folding it in makes a
present image resolve to a path that cannot exist, so it is degraded away.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._image_refs import degrade_missing_image_refs


def _with_image(tmp_path: Path) -> Path:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "cell.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_titled_ref_to_an_existing_file_is_untouched(tmp_path: Path) -> None:
    base = _with_image(tmp_path)
    src = '![Fig 1](images/cell.png "Figure 1")\n'
    assert degrade_missing_image_refs(src, base_dir=base) == (src, 0)


def test_single_quoted_and_paren_titles_are_untouched(tmp_path: Path) -> None:
    base = _with_image(tmp_path)
    for src in ("![F](images/cell.png 'T')\n", "![F](images/cell.png (T))\n"):
        assert degrade_missing_image_refs(src, base_dir=base) == (src, 0)


def test_titled_ref_to_a_missing_file_still_degrades(tmp_path: Path) -> None:
    out, n = degrade_missing_image_refs('![Fig](images/gone.png "T")\n', base_dir=tmp_path)
    assert (out, n) == ("_Fig_\n", 1)


def test_angle_bracket_destination_with_a_title(tmp_path: Path) -> None:
    base = _with_image(tmp_path)
    src = '![F](<images/cell.png> "T")\n'
    assert degrade_missing_image_refs(src, base_dir=base) == (src, 0)


def test_untitled_refs_are_unaffected(tmp_path: Path) -> None:
    base = _with_image(tmp_path)
    src = "![A](images/cell.png)\n\n![B](images/gone.png)\n"
    out, n = degrade_missing_image_refs(src, base_dir=base)
    assert n == 1
    assert "![A](images/cell.png)" in out and "_B_" in out
