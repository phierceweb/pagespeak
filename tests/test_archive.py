"""Tests for pagespeak.backends._archive — capped, contained zip reads."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from pagespeak.backends._archive import ArchiveBudget, copy_member, extract_zip


def _zip(path: Path, members: dict[str, bytes], *, symlinks: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return path


def test_extract_zip_writes_regular_members(tmp_path: Path) -> None:
    src = _zip(tmp_path / "a.zip", {"top.xml": b"<m/>", "sub/dir/img.png": b"png"})
    dest = tmp_path / "out"
    dest.mkdir()
    extract_zip(src, dest)
    assert (dest / "top.xml").read_bytes() == b"<m/>"
    assert (dest / "sub" / "dir" / "img.png").read_bytes() == b"png"


@pytest.mark.parametrize("name", ["../escaped.txt", "sub/../../escaped.txt", "/abs/escaped.txt"])
def test_extract_zip_refuses_a_member_outside_the_dest(tmp_path: Path, name: str) -> None:
    src = _zip(tmp_path / "a.zip", {name: b"x"})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        extract_zip(src, dest)
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_zip_skips_symlink_members(tmp_path: Path) -> None:
    src = _zip(tmp_path / "a.zip", {"keep.txt": b"k"}, symlinks={"link.png": "/etc/passwd"})
    dest = tmp_path / "out"
    dest.mkdir()
    extract_zip(src, dest)
    assert (dest / "keep.txt").exists()
    assert not (dest / "link.png").exists()


def test_the_cap_counts_inflated_bytes_across_members(tmp_path: Path, monkeypatch) -> None:
    """A zip bomb is tiny compressed and huge inflated; the cap is charged as
    bytes inflate, summed over every member."""
    src = _zip(tmp_path / "a.zip", {"one.bin": b"\0" * 3000, "two.bin": b"\0" * 3000})
    assert src.stat().st_size < 1000
    monkeypatch.setenv("PAGESPEAK_MAX_ARCHIVE_BYTES", "5000")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="PAGESPEAK_MAX_ARCHIVE_BYTES"):
        extract_zip(src, dest)


def test_copy_member_leaves_no_partial_file(tmp_path: Path) -> None:
    src = _zip(tmp_path / "a.zip", {"big.bin": b"\0" * 5000})
    target = tmp_path / "big.bin"
    with zipfile.ZipFile(src) as zf, pytest.raises(ValueError):
        copy_member(zf, "big.bin", target, ArchiveBudget(src, limit=100))
    assert not target.exists()


def test_budget_defaults_to_the_env_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_MAX_ARCHIVE_BYTES", "1234")
    assert ArchiveBudget(tmp_path / "a.zip").limit == 1234
