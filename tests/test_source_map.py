"""Tests for services._source_map — what a build read from its source PDF."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.services._source_map import (
    SOURCE_MAP_FILENAME,
    read_source_map,
    write_source_map,
)


def _write(tmp_path: Path) -> Path:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    write_source_map(
        tmp_path,
        pdf=pdf,
        pages=[(3, 5), (9, 9)],
        body=(40.0, 760.0),
        pictures=[("p0004-fig-1.jpeg", 4, (10.0, 20.0, 300.0, 400.0))],
        left_out=[(3, (0.0, 0.0, 612.0, 300.0), "author photos")],
        left_out_text=[(r"^Visit the companion", "publisher ads")],
    )
    return pdf


def test_a_written_map_reads_back(tmp_path: Path) -> None:
    pdf = _write(tmp_path)
    smap = read_source_map(tmp_path)
    assert smap is not None
    assert smap.pdf == pdf
    assert smap.sha256 is not None and len(smap.sha256) == 64
    assert smap.page_numbers() == [3, 4, 5, 9]
    assert [p.image for p in smap.pictures_on(4)] == ["p0004-fig-1.jpeg"]
    assert smap.pictures_on(5) == []
    assert [lo.why for lo in smap.left_out_on(3)] == ["author photos"]
    assert smap.text_left_out("Visit the companion site online")
    assert not smap.text_left_out("The tower has four floors.")
    assert smap.in_body(100.0, 110.0)
    assert not smap.in_body(770.0, 780.0)


def test_no_map_is_none(tmp_path: Path) -> None:
    assert read_source_map(tmp_path) is None


def test_a_map_without_a_body_band_covers_the_whole_page(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    write_source_map(tmp_path, pdf=pdf, pages=[(1, 2)], body=None, pictures=[])
    smap = read_source_map(tmp_path)
    assert smap is not None and smap.in_body(780.0, 790.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(version=99),
        lambda m: m.update(pages=[[5, 3]]),
        lambda m: m["pictures"].append({"image": "x.png", "page": 4}),
        lambda m: m["left_out_text"].append({"pattern": "(", "why": "broken"}),
        lambda m: m.pop("source"),
        lambda m: m["pictures"].append({"image": "x.png", "page": 4, "box": [10, 10, 5, 20]}),
        lambda m: m.update(glyphs=[{"font": "MathPi", "from": "Q~", "to": "±"}]),
    ],
)
def test_a_malformed_map_is_refused(tmp_path: Path, mutate: object) -> None:
    _write(tmp_path)
    path = tmp_path / SOURCE_MAP_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)  # type: ignore[operator]  # the parametrized lambdas
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(InvalidInputError):
        read_source_map(tmp_path)


def test_glyph_tables_read_back_per_font(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    write_source_map(
        tmp_path, pdf=pdf, pages=[(1, 1)], body=None, pictures=[], glyphs=[("MathPi", "Q~", "±≈")]
    )
    smap = read_source_map(tmp_path)
    assert smap is not None and smap.glyph_tables() == {"MathPi": {"Q": "±", "~": "≈"}}


def test_background_art_reads_back_per_page(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    write_source_map(
        tmp_path,
        pdf=pdf,
        pages=[(1, 2)],
        body=None,
        pictures=[],
        background=[(2, (0.0, 0.0, 600.0, 800.0), "opener photo")],
    )
    smap = read_source_map(tmp_path)
    assert smap is not None
    assert [bg.why for bg in smap.background_on(2)] == ["opener photo"]
    assert smap.background_on(1) == []
