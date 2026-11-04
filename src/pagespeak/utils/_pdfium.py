"""The pypdfium2 calls that differ between 4.30, which Marker's `pdf` extra pins,
and 5, which other installs get. Callers import pypdfium2 themselves."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

Box = tuple[float, float, float, float]


def object_bounds(obj: Any) -> Box:
    """A page object's left, bottom, right and top. Inside a form they are in the form's
    space: its /Matrix applied, its placement on the page not."""
    read = obj.get_bounds if hasattr(obj, "get_bounds") else obj.get_pos
    left, bottom, right, top = read()
    return (left, bottom, right, top)


def outline(doc: Any) -> Iterator[tuple[int, str, int | None]]:
    """Each bookmark's level (0 = top), title and 0-based page, None when it points at none."""
    for item in doc.get_toc():
        if hasattr(item, "get_title"):
            dest = item.get_dest()
            yield item.level, item.get_title(), None if dest is None else dest.get_index()
        else:
            yield item.level, item.title, item.page_index
