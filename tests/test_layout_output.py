"""Tests for backends._layout_output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.backends._layout_output import (
    _ranges,
    clip_crops,
    render_crops,
    write_layout_source_map,
)
from pagespeak.backends._layout_profile import profile_from_mapping
from tests.fixtures.layout_book import profile_mapping


def test_pages_collapse_into_runs() -> None:
    assert _ranges([3, 4, 5, 9, 1, 4]) == [(1, 1), (3, 5), (9, 9)]


def test_the_source_map_records_pages_pictures_and_what_is_left_out(tmp_path: Path) -> None:
    m = profile_mapping()
    m["document"]["raster_tables"] = {
        2: {
            "top": 600,
            "figure": [100, 300, 400, 500],
            "label": "x",
            "title": "CHART 1-1. Parts",
            "header": ["A"],
            "rows": [["1"]],
        }
    }
    m["source_map"] = {"left_out_text": [["^WATERMARK", "on every page"]]}
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    write_layout_source_map(
        tmp_path, pdf, profile_from_mapping(m), [2, 3], [(2, [1.0, 2.0, 3.0, 4.0], "a.jpeg", 0)]
    )
    smap = json.loads((tmp_path / ".pagespeak-source-map.json").read_text())
    assert smap["pages"] == [[3, 4]] and smap["pictures"] == [
        {"image": "a.jpeg", "page": 3, "box": [1.0, 2.0, 3.0, 4.0]}
    ]
    assert smap["left_out"][0]["page"] == 3 and smap["left_out"][0]["box"] == [100, 0.0, 400, 300]
    assert smap["body"] == {"bottom": 0.0, "top": 740.0}
    write_layout_source_map(tmp_path, pdf, profile_from_mapping(m), [2, 3], [], bottom=120.0)
    raised = json.loads((tmp_path / ".pagespeak-source-map.json").read_text())
    assert raised["body"]["bottom"] == 120.0 and raised["left_out"][0]["box"] == [
        100,
        120.0,
        400,
        300,
    ]
    assert smap["left_out"][0]["why"].startswith("CHART 1-1 is printed as a picture")
    assert smap["left_out_text"] == [{"pattern": "^WATERMARK", "why": "on every page"}]


def test_a_crop_past_the_page_edge_is_cut_and_recorded_at_the_edge(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium
    from PIL import Image

    from pagespeak.backends._layout import convert_pdf_layout
    from tests.fixtures.layout_book import make_book, write_profile

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    over = [(2, [-5.0, 242.0, 272.0, 800.0], "a.jpeg", 0)]
    assert clip_crops(doc, over) == [(2, [0.0, 242.0, 272.0, 792.0], "a.jpeg", 0)]
    (path,) = render_crops(doc, over, tmp_path / "images")
    assert Image.open(path).size == (544, 1100)

    m = profile_mapping()
    m["document"]["crop_overrides"] = {"p0002-plate-1-1.jpeg": [-5, 242, 272, 800]}
    write_profile(tmp_path / "b.layout.yaml", m)
    convert_pdf_layout(tmp_path / "b.pdf", output_dir=tmp_path / "out")
    smap = json.loads((tmp_path / "out" / ".pagespeak-source-map.json").read_text())
    assert smap["pictures"][0]["box"] == [0.0, 242.0, 272.0, 792.0]


def test_render_crops_cuts_each_crop_at_twice_the_page_scale(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium
    from PIL import Image

    from tests.fixtures.layout_book import make_book

    doc = pdfium.PdfDocument(str(make_book(tmp_path / "b.pdf")))
    paths = render_crops(
        doc,
        [(2, [72, 242, 272, 342], "a.jpeg", 0), (2, [72, 242, 272, 342], "b.jpeg", 90)],
        tmp_path / "images",
    )
    assert [p.name for p in paths] == ["a.jpeg", "b.jpeg"]
    assert Image.open(paths[0]).size == (400, 200) and Image.open(paths[1]).size == (200, 400)
