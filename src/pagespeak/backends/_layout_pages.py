"""Layout backend: one page's record — its size, crop box, text lines and drawn geometry."""

from __future__ import annotations

from typing import Any

from ._layout_geometry import page_geometry
from ._layout_lines import page_lines

PageRecord = dict[str, Any]


def render_page(page: Any, scale: float) -> Any:
    """The page as a PIL image in the space its text and drawings are read in: a page rotation is undone."""
    return page.render(scale=scale, rotation=(360 - page.get_rotation()) % 360).to_pil()


def read_page(doc: Any, index: int, *, acute_as_prime: bool = False) -> PageRecord:
    """The record the layout reader works from, for 0-based page `index` of an open pdfium document."""
    page = doc[index]
    geo = page_geometry(page)
    return {
        "page": index,
        "size": list(page.get_size()),
        "box": [round(v, 2) for v in page.get_cropbox()],
        "lines": page_lines(page, page.get_textpage(), acute_as_prime=acute_as_prime),
        "images": geo.images,
        "fills": geo.fills,
        "rules": geo.rules,
        "art": geo.art,
        "strokes": geo.strokes,
        "slim": geo.slim,
    }
