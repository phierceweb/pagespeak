"""Tests for services/_image_refs.degrade_missing_image_refs."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._image_refs import degrade_missing_image_refs


def _mk_image(base: Path, rel: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG")


def test_missing_local_ref_degrades_to_italic_caption(tmp_path: Path) -> None:
    text = "Intro.\n\n![A bar chart of quarterly sales](images/x.webp)\n\nMore."
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 1
    assert "![A bar chart of quarterly sales]" not in out
    assert "_A bar chart of quarterly sales_" in out


def test_existing_local_ref_is_kept(tmp_path: Path) -> None:
    _mk_image(tmp_path, "images/x.webp")
    text = "![alt](images/x.webp)"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 0
    assert out == text


def test_external_ref_is_kept(tmp_path: Path) -> None:
    text = "![alt](https://example.com/x.png) and ![b](data:image/png;base64,AAAA)"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 0
    assert out == text


def test_empty_alt_missing_ref_is_dropped(tmp_path: Path) -> None:
    text = "before ![](images/x.webp) after"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 1
    assert "![]" not in out
    assert "images/x.webp" not in out


def test_base_dir_none_is_noop() -> None:
    text = "![alt](images/x.webp)"
    out, n = degrade_missing_image_refs(text, base_dir=None)
    assert n == 0
    assert out == text


def test_idempotent(tmp_path: Path) -> None:
    text = "![alt](images/x.webp)\n\n![keep](https://e.com/y.png)"
    once, n1 = degrade_missing_image_refs(text, base_dir=tmp_path)
    twice, n2 = degrade_missing_image_refs(once, base_dir=tmp_path)
    assert n1 == 1
    assert n2 == 0
    assert twice == once


def test_angle_wrapped_target_is_resolved(tmp_path: Path) -> None:
    # The splitter angle-wraps targets containing spaces; a missing one still degrades.
    text = "![a caption](<images/my file.webp>)"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 1
    assert "_a caption_" in out


def test_mixed_present_and_missing(tmp_path: Path) -> None:
    _mk_image(tmp_path, "images/here.png")
    text = "![gone](images/gone.png)\n\n![here](images/here.png)\n\n![also gone](images/x.png)"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 2
    assert "![here](images/here.png)" in out  # present ref untouched
    assert "_gone_" in out
    assert "_also gone_" in out


def test_percent_encoded_target_matches_decoded_file(tmp_path: Path) -> None:
    # A ref may be %-encoded (`My%20Fig.png`) while the file on disk is decoded
    # (`My Fig.png`). It must NOT be treated as missing / degraded.
    _mk_image(tmp_path, "images/My Fig.png")
    text = "![real figure](images/My%20Fig.png)"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 0
    assert out == text
