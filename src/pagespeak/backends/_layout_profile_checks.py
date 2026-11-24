"""Layout backend: a loaded profile's values checked against each other — page numbers
inside the pages read, bands in order, heading levels, templates and boxes that hold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._layout_fields import bad

if TYPE_CHECKING:
    from ._layout_profile import LayoutProfile


def _named_pages(prof: LayoutProfile) -> list[tuple[str, int]]:
    block = prof.title_block
    named = [("pages.skip", page) for page in sorted(prof.skip_pages)]
    named += [("pages.flow_charts", page) for page in sorted(prof.flow_chart_pages)]
    named.append(("document.title_block.cover_page", block.cover_page))
    named += [
        (f"document.title_block.lines[{i}].page", page) for i, (page, _) in enumerate(block.lines)
    ]
    named += [
        (f"document.drop_lines[{i}].page", page) for i, (page, _) in enumerate(prof.drop_lines)
    ]
    named += [("document.raster_tables", page) for page in sorted(prof.raster_tables)]
    return named


def _box(where: str, box: list[float]) -> None:
    if not (box[0] < box[2] and box[1] < box[3]):
        raise bad(
            f"{where} must be a box [left, bottom, right, top] with left < right and "
            f"bottom < top, got {box!r}"
        )


def _template(where: str, text: str, **sample: object) -> None:
    try:
        text.format(**sample)
    except (KeyError, IndexError, ValueError) as exc:
        names = ", ".join("{" + name + "}" for name in sample)
        raise bad(
            f"{where} is not a valid template ({type(exc).__name__}: {exc}); it may use {names}"
        ) from exc


def check_profile(prof: LayoutProfile) -> None:
    """Raise `InvalidInputError`, naming the field, for a value that cannot work with the others."""
    first, last = prof.pages
    if not 0 <= first <= last:
        raise bad(f"pages.first must be between 0 and pages.last, got {first} and {last}")
    for where, page in _named_pages(prof):
        if not first <= page <= last:
            raise bad(
                f"{where} names page {page} (0-based), outside pages.first–last ({first}–{last})"
            )
    if not prof.floor_y < prof.head_y:
        raise bad(
            f"bands.floor_y must be below bands.head_y, got {prof.floor_y:g} and {prof.head_y:g}"
        )
    inner = prof.page_number_inner
    if not inner[0] < inner[1]:
        raise bad(f"bands.page_number_inner must run from left to right, got {list(inner)!r}")
    for i, rule in enumerate(prof.headings):
        if not 1 <= rule.level <= 6:
            raise bad(f"fonts.headings[{i}].level must be between 1 and 6, got {rule.level}")
    _template("document.opener.heading", prof.opener.heading, n=1, title="")
    _template("document.opener.picture_label", prof.opener.picture_label, n=1)
    for name, box in prof.crop_overrides.items():
        _box(f"document.crop_overrides.{name}", box)
    for page, spec in prof.raster_tables.items():
        _box(f"document.raster_tables.{page}.figure", spec["figure"])
        width = len(spec["header"])
        for i, row in enumerate(spec["rows"]):
            if len(row) != width:
                raise bad(
                    f"document.raster_tables.{page}.rows[{i}] must have {width} cells, as the "
                    f"header has, got {len(row)}"
                )
