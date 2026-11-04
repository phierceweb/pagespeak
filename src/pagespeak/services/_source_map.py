"""`<doc>/.pagespeak-source-map.json`: what a build read from its source PDF.

Written by whatever cut the pictures (a layout reader) and read by verify's
line and picture checks, which cannot run without it. Pages are 1-based;
boxes are PDF points with the origin bottom-left, as pdfium reports them.

    {"version": 1,
     "source": {"file": "/abs/book.pdf", "sha256": "…"},
     "pages": [[9, 214]],
     "body": {"bottom": 36, "top": 756},
     "pictures": [{"image": "p0123-fig.jpeg", "page": 124, "box": [x0, y0, x1, y1]}],
     "left_out": [{"page": 5, "box": [x0, y0, x1, y1], "why": "a full-page advert"}],
     "background": [{"page": 9, "box": [x0, y0, x1, y1], "why": "chapter opener photo"}],
     "left_out_text": [{"pattern": "^Visit the companion site", "why": "advert lines"}],
     "glyphs": [{"font": "MathPi", "from": "Q~", "to": "±≈"}]}

`body` is the band between running head and foot; `left_out` and
`left_out_text` name what the build drops on purpose, so verify does not
report it as lost. `background` is art behind text the build does not keep
as a picture (an opener photo, a tinted panel): its ink is not dropped art,
and the text over it is still body text. `glyphs` names fonts whose text
layer stores a symbol under a stand-in letter, so the PDF's text reads as the
page shows it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pw_core.pipeline.run_record import file_sha256
from pw_foundation.exceptions import InvalidInputError
from pw_foundation.utils.io import atomic_write_json

SOURCE_MAP_FILENAME = ".pagespeak-source-map.json"
_VERSION = 1

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class MapPicture:
    image: str
    page: int
    box: Box


@dataclass(frozen=True)
class LeftOut:
    page: int
    box: Box
    why: str


@dataclass(frozen=True)
class SourceMap:
    pdf: Path
    sha256: str | None
    pages: tuple[tuple[int, int], ...]
    body: tuple[float, float] | None
    pictures: tuple[MapPicture, ...]
    left_out: tuple[LeftOut, ...]
    left_out_text: tuple[tuple[re.Pattern[str], str], ...]
    glyphs: tuple[tuple[str, str, str], ...] = ()  # font, stand-ins, what they show
    background: tuple[LeftOut, ...] = ()

    def glyph_tables(self) -> dict[str, dict[str, str]]:
        return {
            font: dict(zip(stand_in, shown, strict=True)) for font, stand_in, shown in self.glyphs
        }

    def page_numbers(self) -> list[int]:
        return [n for first, last in self.pages for n in range(first, last + 1)]

    def pictures_on(self, page: int) -> list[MapPicture]:
        return [p for p in self.pictures if p.page == page]

    def left_out_on(self, page: int) -> list[LeftOut]:
        return [lo for lo in self.left_out if lo.page == page]

    def background_on(self, page: int) -> list[LeftOut]:
        return [bg for bg in self.background if bg.page == page]

    def text_left_out(self, text: str) -> bool:
        return any(pattern.search(text) for pattern, _ in self.left_out_text)

    def in_body(self, y0: float, y1: float) -> bool:
        """A line spanning y0..y1 sits in the body band, not a running head or foot."""
        if self.body is None:
            return True
        middle = (y0 + y1) / 2
        return self.body[0] < middle < self.body[1]


def write_source_map(
    root: Path,
    *,
    pdf: Path,
    pages: Iterable[tuple[int, int]],
    body: tuple[float, float] | None,
    pictures: Iterable[tuple[str, int, Box]],
    left_out: Iterable[tuple[int, Box, str]] = (),
    left_out_text: Iterable[tuple[str, str]] = (),
    glyphs: Iterable[tuple[str, str, str]] = (),
    background: Iterable[tuple[int, Box, str]] = (),
) -> Path:
    """Write the map beside a document's master; returns its path."""
    data: dict[str, Any] = {
        "version": _VERSION,
        "source": {"file": str(pdf.resolve()), "sha256": file_sha256(pdf)},
        "pages": [[a, b] for a, b in pages],
        "body": None if body is None else {"bottom": body[0], "top": body[1]},
        "pictures": [{"image": i, "page": p, "box": list(b)} for i, p, b in pictures],
        "left_out": [{"page": p, "box": list(b), "why": w} for p, b, w in left_out],
        "left_out_text": [{"pattern": pat, "why": w} for pat, w in left_out_text],
        "glyphs": [{"font": f, "from": a, "to": b} for f, a, b in glyphs],
        "background": [{"page": p, "box": list(b), "why": w} for p, b, w in background],
    }
    path = root / SOURCE_MAP_FILENAME
    atomic_write_json(path, data)
    return path


def _box(value: Any) -> Box:
    if not (isinstance(value, list) and len(value) == 4):
        raise ValueError(f"a box is [x0, y0, x1, y1], got {value!r}")
    x0, y0, x1, y1 = (float(v) for v in value)
    if x0 > x1 or y0 > y1:
        raise ValueError(f"box corners out of order: {value!r}")
    return (x0, y0, x1, y1)


def _parse(data: Any) -> SourceMap:
    if not isinstance(data, dict) or data.get("version") != _VERSION:
        raise ValueError(f"expected an object with version {_VERSION}")
    source = data["source"]
    pages = tuple((int(a), int(b)) for a, b in data["pages"])
    if any(a < 1 or a > b for a, b in pages):
        raise ValueError(f"page ranges are 1-based [first, last]: {data['pages']!r}")
    body = data.get("body")
    return SourceMap(
        pdf=Path(source["file"]),
        sha256=source.get("sha256"),
        pages=pages,
        body=None if body is None else (float(body["bottom"]), float(body["top"])),
        pictures=tuple(
            MapPicture(str(p["image"]), int(p["page"]), _box(p["box"])) for p in data["pictures"]
        ),
        left_out=tuple(
            LeftOut(int(lo["page"]), _box(lo["box"]), str(lo["why"]))
            for lo in data.get("left_out", [])
        ),
        left_out_text=tuple(
            (re.compile(t["pattern"]), str(t["why"])) for t in data.get("left_out_text", [])
        ),
        glyphs=tuple(_glyph(g) for g in data.get("glyphs", [])),
        background=tuple(
            LeftOut(int(bg["page"]), _box(bg["box"]), str(bg["why"]))
            for bg in data.get("background", [])
        ),
    )


def _glyph(entry: Any) -> tuple[str, str, str]:
    font, stand_in, shown = str(entry["font"]), str(entry["from"]), str(entry["to"])
    if len(stand_in) != len(shown):
        raise ValueError(f"glyphs for {font}: 'from' and 'to' differ in length")
    return font, stand_in, shown


def read_source_map(root: Path) -> SourceMap | None:
    """The map beside `root`'s master, or None when the build wrote none.

    Raises InvalidInputError when it exists but cannot be read: a broken map
    must never pass for "no map" and quietly switch the checks that need it off.
    """
    path = root / SOURCE_MAP_FILENAME
    if not path.is_file():
        return None
    try:
        return _parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        raise InvalidInputError(f"{path}: {exc}") from exc
