"""Tests for services._chunk_rewrite."""

from __future__ import annotations

from pagespeak.services._chunk_rewrite import (
    prefix_image_basenames,
    rewrite_anchor_ids_to_absolute,
)


def test_prefix_image_basenames_simple() -> None:
    md = "before\n\n![alt](images/_page_3_Figure_1.jpeg)\n\nafter"
    result, renames = prefix_image_basenames(md, page_range="0050-0099")
    assert "0050-0099-_page_3_Figure_1.jpeg" in result
    # The unprefixed form should not appear standalone (only as part of the prefixed name).
    assert "images/_page_3_Figure_1.jpeg" not in result
    assert renames == {"_page_3_Figure_1.jpeg": "0050-0099-_page_3_Figure_1.jpeg"}


def test_prefix_image_basenames_multiple() -> None:
    md = "![](images/_page_3_Figure_1.jpeg)\n![](images/_page_5_Figure_2.png)\n"
    result, renames = prefix_image_basenames(md, page_range="0050-0099")
    assert "0050-0099-_page_3_Figure_1.jpeg" in result
    assert "0050-0099-_page_5_Figure_2.png" in result
    assert renames == {
        "_page_3_Figure_1.jpeg": "0050-0099-_page_3_Figure_1.jpeg",
        "_page_5_Figure_2.png": "0050-0099-_page_5_Figure_2.png",
    }


def test_prefix_image_basenames_no_images_returns_unchanged() -> None:
    md = "# Heading\n\nText only.\n"
    result, renames = prefix_image_basenames(md, page_range="0050-0099")
    assert result == md
    assert renames == {}


def test_prefix_image_basenames_preserves_non_image_paths() -> None:
    md = '<a href="page.html">link</a> ![](images/foo.png)'
    result, renames = prefix_image_basenames(md, page_range="0000-0049")
    assert "0000-0049-foo.png" in result
    assert "page.html" in result
    assert renames == {"foo.png": "0000-0049-foo.png"}


def test_rewrite_anchor_ids_basic() -> None:
    md = '<span id="page-3-2"></span>\n\nbody\n\n[See foo](#page-3-2)\n'
    result = rewrite_anchor_ids_to_absolute(md, page_offset=50)
    assert 'id="page-53-2"' in result
    assert "(#page-53-2)" in result
    assert "page-3-2" not in result


def test_rewrite_anchor_ids_zero_offset() -> None:
    md = '<span id="page-3-2"></span>\n[ref](#page-3-2)\n'
    result = rewrite_anchor_ids_to_absolute(md, page_offset=0)
    assert result == md


def test_rewrite_anchor_ids_preserves_unrelated_anchors() -> None:
    md = (
        '<span id="page-3-2"></span>\n'
        '<a name="foo">x</a>\n'
        '<a name="page-3-2">should not be touched (different attr)</a>\n'
        "[#real-section](#real-section)\n"
        "[p](#page-3-2)\n"
    )
    result = rewrite_anchor_ids_to_absolute(md, page_offset=10)
    assert 'id="page-13-2"' in result
    assert '<a name="foo">x</a>' in result
    assert '<a name="page-3-2">' in result  # name= attr is NOT rewritten
    assert "#real-section" in result
    assert "(#page-13-2)" in result


def test_rewrite_anchor_ids_handles_multi_digit_pages() -> None:
    md = '<span id="page-12-34"></span>\n[r](#page-12-34)\n'
    result = rewrite_anchor_ids_to_absolute(md, page_offset=100)
    assert 'id="page-112-34"' in result
    assert "(#page-112-34)" in result


def test_rewrite_anchor_ids_negative_offset_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="page_offset must be >= 0"):
        rewrite_anchor_ids_to_absolute("x", page_offset=-1)


def test_prefix_image_basenames_preserves_subdirectory() -> None:
    md = "![](images/sub/foo.png)"
    result, renames = prefix_image_basenames(md, page_range="0050-0099")
    assert "images/sub/0050-0099-foo.png" in result
    assert renames == {"foo.png": "0050-0099-foo.png"}
