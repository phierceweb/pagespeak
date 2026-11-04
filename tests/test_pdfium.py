"""Tests for utils._pdfium — the pypdfium2 calls that differ between 4.30 and 5."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pagespeak.utils._pdfium import object_bounds, outline


class _Dest:
    def __init__(self, index: int | None) -> None:
        self._index = index

    def get_index(self) -> int | None:
        return self._index


class _Bookmark:
    """A bookmark as pypdfium2 5 hands it out."""

    def __init__(self, level: int, title: str, dest: _Dest | None) -> None:
        self.level = level
        self._title = title
        self._dest = dest

    def get_title(self) -> str:
        return self._title

    def get_dest(self) -> _Dest | None:
        return self._dest


def test_bounds_are_read_under_either_release() -> None:
    four = SimpleNamespace(get_pos=lambda: (1.0, 2.0, 3.0, 4.0))
    five = SimpleNamespace(get_bounds=lambda: (5.0, 6.0, 7.0, 8.0))
    assert object_bounds(four) == (1.0, 2.0, 3.0, 4.0)
    assert object_bounds(five) == (5.0, 6.0, 7.0, 8.0)


def test_the_outline_is_read_under_either_release() -> None:
    four = SimpleNamespace(
        get_toc=lambda: iter(
            [
                SimpleNamespace(level=0, title="One", page_index=3),
                SimpleNamespace(level=1, title="Two", page_index=None),
            ]
        )
    )
    five = SimpleNamespace(
        get_toc=lambda: iter(
            [
                _Bookmark(0, "One", _Dest(3)),
                _Bookmark(1, "Two", None),
                _Bookmark(1, "Three", _Dest(None)),
            ]
        )
    )
    assert list(outline(four)) == [(0, "One", 3), (1, "Two", None)]
    assert list(outline(five)) == [(0, "One", 3), (1, "Two", None), (1, "Three", None)]


def test_the_installed_release_reads_a_real_pdf(tmp_path: Path) -> None:
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("fpdf")
    from tests.fixtures.pdf_pages import Page, body_lines, make_pdf

    pages = [
        Page(lines=body_lines(["The tower"]), bookmark=(0, "Chapter 1")),
        Page(bookmark=(1, "1.1 Lamps")),
    ]
    doc = pdfium.PdfDocument(str(make_pdf(tmp_path / "a.pdf", pages)))
    try:
        assert list(outline(doc)) == [(0, "Chapter 1", 0), (1, "1.1 Lamps", 1)]
        text = next(o for o in doc[0].get_objects() if o.type == 1)
        x0, y0, x1, y1 = object_bounds(text)
        assert 0 < x0 < x1 < 612 and 0 < y0 < y1 < 792
    finally:
        doc.close()
