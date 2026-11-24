"""Layout backend: a document's profile — the structural signals the reader takes from one book.

A profile is YAML: page bands, the faces for body text and headings, the patterns that
name captions, titles, credits and list marks, and the pages read differently (skipped,
flow charts, picture-only tables transcribed by hand). It carries no code; the reader in
`_layout_*` applies it. See docs/layout-backend.md for the schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pw_foundation.exceptions import InvalidInputError
from pw_foundation.utils.yaml import safe_load

from ._layout_fields import Section, bad
from ._layout_profile_checks import check_profile

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HeadingRule:
    """A line in the heading face is a heading at `level` when every condition holds."""

    level: int
    min_cap: float
    max_len: int
    caps: bool = False
    font_suffix: str | None = None
    no_period: bool = False


@dataclass(frozen=True)
class Opener:
    """A chapter's opening page: found by a line, headed from `titles`, its display type dropped."""

    text: str
    above: float
    font_contains: str
    heading: str
    titles: tuple[str, ...]
    drop_taller_than: float
    drop_font_suffix: str
    drop_min_cap: float
    picture_label: str


@dataclass(frozen=True)
class TitleBlock:
    heading: str
    cover_page: int
    keep: re.Pattern[str]
    lines: tuple[tuple[int, re.Pattern[str]], ...] = ()
    replace: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LayoutProfile:
    head_y: float
    table_rules_below: float
    floor_y: float
    page_number_below: float
    page_number: re.Pattern[str]
    page_number_inner: tuple[float, float]
    furniture_fonts: tuple[str, ...]
    body_font: str
    heading_font: str
    label_head_min_cap: float
    headings: tuple[HeadingRule, ...]
    figure_caption: re.Pattern[str]
    table_title: re.Pattern[str]
    reference_line: re.Pattern[str]
    reference_run: re.Pattern[str]
    credit: re.Pattern[str]
    cell_credit: re.Pattern[str]
    cell_credit_fragment: re.Pattern[str]
    label_credit: re.Pattern[str]
    label_credit_exact: tuple[str, ...]
    note_prefix: re.Pattern[str]
    list_mark: re.Pattern[str]
    checkbox: str
    instruction: re.Pattern[str]
    key_entry: re.Pattern[str]
    stops_heading: re.Pattern[str]
    stops_exclude: str
    item_heading: re.Pattern[str]
    aside_heading: re.Pattern[str]
    opener: Opener
    title_block: TitleBlock
    pages: tuple[int, int]
    skip_pages: frozenset[int]
    flow_chart_pages: frozenset[int]
    front_headings: dict[str, str]
    drop_lines: tuple[tuple[int, re.Pattern[str]], ...]
    group_after_empty_head: bool = False
    acute_as_prime: bool = False
    raster_tables: dict[int, dict[str, Any]] = field(default_factory=dict)
    crop_overrides: dict[str, list[float]] = field(default_factory=dict)
    left_out_text: tuple[tuple[str, str], ...] = ()


_PATTERN_NAMES = (
    "page_number",
    "figure_caption",
    "table_title",
    "reference_line",
    "reference_run",
    "credit",
    "cell_credit",
    "cell_credit_fragment",
    "label_credit",
    "note_prefix",
    "list_mark",
    "instruction",
    "key_entry",
    "stops_heading",
    "item_heading",
)
_TOP = ("version", "bands", "fonts", "patterns", "pages", "document", "source_map")
_BANDS = ("head_y", "table_rules_below", "floor_y", "page_number_below", "page_number_inner")
_FONTS = ("furniture", "body", "heading", "label_head_min_cap", "headings", "acute_as_prime")
_RULE = ("level", "min_cap", "max_len", "caps", "font_suffix", "no_period")
_PATTERNS = (*_PATTERN_NAMES, "aside_heading", "checkbox", "label_credit_exact", "stops_exclude")
_PAGES = ("first", "last", "skip", "flow_charts")
_DOCUMENT = (
    "opener",
    "title_block",
    "front_headings",
    "drop_lines",
    "group_after_empty_head",
    "raster_tables",
    "crop_overrides",
)
_OPENER = (
    "text",
    "above",
    "font_contains",
    "heading",
    "titles",
    "drop_taller_than",
    "drop_font_suffix",
    "drop_min_cap",
    "picture_label",
)
_TITLE_BLOCK = ("heading", "cover_page", "keep", "lines", "replace")
_RASTER = ("top", "figure", "label", "title", "header", "rows")


def _heading_rule(s: Section) -> HeadingRule:
    return HeadingRule(
        level=s.whole("level"),
        min_cap=s.num("min_cap"),
        max_len=s.whole("max_len"),
        caps=s.flag("caps"),
        font_suffix=s.opt_text("font_suffix"),
        no_period=s.flag("no_period"),
    )


def _opener(s: Section) -> Opener:
    return Opener(
        text=s.word("text"),
        above=s.num("above"),
        font_contains=s.text("font_contains"),
        heading=s.word("heading"),
        titles=s.texts("titles"),
        drop_taller_than=s.num("drop_taller_than"),
        drop_font_suffix=s.text("drop_font_suffix"),
        drop_min_cap=s.num("drop_min_cap"),
        picture_label=s.word("picture_label"),
    )


def _title_block(s: Section) -> TitleBlock:
    return TitleBlock(
        heading=s.word("heading"),
        cover_page=s.whole("cover_page"),
        keep=s.pattern("keep", blank_ok=True),
        lines=tuple(
            (d.whole("page"), d.pattern("pattern", blank_ok=True))
            for d in s.children("lines", ("page", "pattern"))
        ),
        replace=s.pairs("replace"),
    )


def _raster_tables(s: Section) -> dict[int, dict[str, Any]]:
    """Each page's hand-transcribed table, checked and kept as written."""
    out: dict[int, dict[str, Any]] = {}
    for page, raw in s.data.items():
        if not isinstance(page, int) or isinstance(page, bool):
            raise bad(f"{s.at(page)} must be keyed by a page number")
        spec = Section(raw, s.at(page), _RASTER)
        spec.num("top"), spec.nums("figure", 4), spec.text("label"), spec.text("title")
        spec.texts("header")
        for i, row in enumerate(spec.items("rows")):
            if not (isinstance(row, list) and all(isinstance(c, str) for c in row)):
                raise bad(f"{spec.at('rows')}[{i}] must be a list of text, got {row!r}")
        out[page] = dict(raw)
    return out


def _left_out_text(s: Section) -> tuple[tuple[str, str], ...]:
    """The (pattern, why) pairs handed to verify, each pattern checked to compile."""
    pairs = s.pairs("left_out_text")
    for i, (pattern, _) in enumerate(pairs):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise bad(f"{s.at('left_out_text')}[{i}] is not a valid pattern: {exc}") from exc
    return pairs


def _document(doc: Section) -> dict[str, Any]:
    front = doc.child("front_headings", None, optional=True)
    crops = doc.child("crop_overrides", None, optional=True)
    return {
        "opener": _opener(doc.child("opener", _OPENER)),
        "title_block": _title_block(doc.child("title_block", _TITLE_BLOCK)),
        "front_headings": {str(k): front.text(k) for k in front.data},
        "drop_lines": tuple(
            (d.whole("page"), d.pattern("pattern", blank_ok=True))
            for d in doc.children("drop_lines", ("page", "pattern"))
        ),
        "group_after_empty_head": doc.flag("group_after_empty_head"),
        "raster_tables": _raster_tables(doc.child("raster_tables", None, optional=True)),
        "crop_overrides": {str(k): crops.nums(k, 4) for k in crops.data},
    }


def profile_from_mapping(data: dict[str, Any]) -> LayoutProfile:
    """Build a profile from its parsed YAML; raises `InvalidInputError` naming the bad field."""
    root = Section(data, "", _TOP)
    if type(data.get("version")) is not int or data["version"] != SCHEMA_VERSION:
        raise bad(f"version must be {SCHEMA_VERSION}")
    bands, fonts = root.child("bands", _BANDS), root.child("fonts", _FONTS)
    p, pages = root.child("patterns", _PATTERNS), root.child("pages", _PAGES)
    inner = bands.nums("page_number_inner", 2)
    rules = fonts.children("headings", _RULE)
    named: dict[str, Any] = {
        name: p.pattern(name, blank_ok=name == "note_prefix") for name in _PATTERN_NAMES
    }
    prof = LayoutProfile(
        head_y=bands.num("head_y"),
        table_rules_below=bands.num("table_rules_below"),
        floor_y=bands.num("floor_y"),
        page_number_below=bands.num("page_number_below"),
        page_number_inner=(inner[0], inner[1]),
        furniture_fonts=fonts.words("furniture"),
        body_font=fonts.word("body"),
        heading_font=fonts.word("heading"),
        label_head_min_cap=fonts.num("label_head_min_cap"),
        headings=tuple(_heading_rule(r) for r in rules),
        acute_as_prime=fonts.flag("acute_as_prime"),
        checkbox=p.word("checkbox"),
        label_credit_exact=p.texts("label_credit_exact"),
        stops_exclude=p.word("stops_exclude"),
        aside_heading=p.pattern("aside_heading", re.I),
        pages=(pages.whole("first"), pages.whole("last")),
        skip_pages=pages.wholes("skip"),
        flow_chart_pages=pages.wholes("flow_charts"),
        left_out_text=_left_out_text(root.child("source_map", ("left_out_text",), optional=True)),
        **named,
        **_document(root.child("document", _DOCUMENT)),
    )
    check_profile(prof)
    return prof


def load_profile(path: Path) -> LayoutProfile:
    """Read and check a layout profile file."""
    import yaml

    try:
        data = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidInputError(f"layout profile {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidInputError(f"layout profile {path}: not a mapping")
    return profile_from_mapping(data)
