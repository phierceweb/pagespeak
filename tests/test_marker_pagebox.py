"""Tests for backends._marker_pagebox — Marker's text layer, keeping only the text
inside each page's visible box."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import marker.providers.pdf as marker_pdf
import pypdfium2 as pdfium
import pytest
from fpdf import FPDF
from marker.providers.pdf import PdfProvider

import pagespeak.backends._marker_pagebox as pagebox
from pagespeak.backends._marker_pagebox import centre_inside, clip_pages, clipped_to_page_box

# A 400 x 300 pt spread whose CropBox keeps the left half: one page cut from a
# two-page spread, the facing page's text still in the file.
_SPREAD = (400, 300)
_LEFT_HALF = (0, 0, 200, 300)


def _pdf(
    path: Path,
    texts: list[tuple[float, float, int, str]],
    *,
    cropbox: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
) -> str:
    raw = path.with_suffix(".raw.pdf")
    doc = FPDF(unit="pt", format=_SPREAD)
    doc.add_page()
    for x, y, size, text in texts:
        doc.set_font("Helvetica", size=size)
        doc.text(x, y, text)
    doc.output(str(raw))
    pdf = pdfium.PdfDocument(raw)
    if cropbox is not None:
        pdf[0].set_cropbox(*cropbox)
    pdf[0].set_rotation(rotation)
    pdf.save(path)
    pdf.close()
    return str(path)


def _spread(path: Path, *, rotation: int = 0) -> str:
    texts = [
        (30, 50, 18, "Own Title"),
        (230, 50, 18, "Facing Title"),
        (30, 120, 11, "Body text on this page."),
        (230, 120, 11, "Body text on the facing page."),
    ]
    return _pdf(path, texts, cropbox=_LEFT_HALF, rotation=rotation)


def _read(path: str, config: dict[str, Any] | None = None) -> PdfProvider:
    config = config or {}
    with clipped_to_page_box(config):
        return PdfProvider(path, config)


def _text(provider: PdfProvider, page: int = 0) -> str:
    return "\n".join(
        "".join(span.text for span in line.spans) for line in provider.get_page_lines(page)
    )


def _boxes(provider: PdfProvider, page: int = 0) -> list[list[float]]:
    lines = provider.get_page_lines(page)
    return [line.line.polygon.bbox for line in lines] + [
        span.polygon.bbox for line in lines for span in line.spans
    ]


# --- the rule ---------------------------------------------------------


def test_centre_inside() -> None:
    page = [0, 0, 200, 300]
    assert centre_inside([10, 10, 20, 20], page)
    assert centre_inside([195, 10, 204, 20], page)  # straddles the edge, centre in
    assert not centre_inside([196, 10, 206, 20], page)  # centre just past the edge
    assert not centre_inside([230, 10, 240, 20], page)
    assert not centre_inside([10, -20, 20, -10], page)


def _char(char: str, x: float, idx: int) -> dict[str, Any]:
    return {"char": char, "bbox": [x, 10, x + 8, 20], "char_idx": idx}


def _page(*spans: list[dict[str, Any]]) -> dict[str, Any]:
    span_dicts = [
        {
            "text": "".join(c["char"] for c in chars),
            "bbox": [chars[0]["bbox"][0], 10, chars[-1]["bbox"][2], 20],
            "chars": chars,
            "char_start_idx": chars[0]["char_idx"],
            "char_end_idx": chars[-1]["char_idx"],
        }
        for chars in spans
    ]
    line = {
        "spans": span_dicts,
        "bbox": [span_dicts[0]["bbox"][0], 10, span_dicts[-1]["bbox"][2], 20],
    }
    return {"width": 200, "height": 300, "blocks": [{"lines": [line], "bbox": line["bbox"]}]}


def test_clip_pages_rebuilds_a_span_from_the_characters_inside() -> None:
    page = _page([_char(c, 180 + 10 * i, i) for i, c in enumerate("ABCDE")])
    assert clip_pages([page], keep_chars=False) == (3, 1)
    (span,) = page["blocks"][0]["lines"][0]["spans"]
    assert span["text"] == "AB"
    assert span["bbox"] == [180, 10, 198, 20]
    assert (span["char_start_idx"], span["char_end_idx"]) == (0, 1)
    assert "chars" not in span
    assert page["blocks"][0]["lines"][0]["bbox"] == [180, 10, 198, 20]


def test_clip_pages_drops_a_line_left_empty() -> None:
    page = _page([_char("Z", 250, 0)])
    assert clip_pages([page], keep_chars=True) == (1, 1)
    assert page["blocks"] == []


def test_clip_pages_leaves_a_page_inside_its_box_alone() -> None:
    page = _page([_char("A", 10, 0)], [_char("B", 30, 1)])
    before = repr(page)
    assert clip_pages([page], keep_chars=True) == (0, 0)
    assert repr(page) == before


# --- Marker's reader, on a page cut from a spread -----------------------


def test_marker_reads_the_facing_pages_text(tmp_path: Path) -> None:
    """The defect: pdftext keeps text outside the CropBox, beside this page's."""
    assert "Facing Title" in _text(PdfProvider(_spread(tmp_path / "spread.pdf"), {}))


def test_drops_the_facing_pages_text(tmp_path: Path) -> None:
    provider = _read(_spread(tmp_path / "spread.pdf"))
    text = _text(provider)
    assert "Own Title" in text
    assert "Body text on this page." in text
    assert "acing" not in text
    assert all(box[2] <= 201 for box in _boxes(provider)), _boxes(provider)


def test_keeps_the_part_of_a_span_inside_the_page(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "straddle.pdf", [(150, 80, 14, "ABCDEFGHIJKLMNOP")], cropbox=_LEFT_HALF)
    provider = _read(path)
    text = _text(provider).strip()
    assert text and "ABCDEFGHIJKLMNOP".startswith(text) and text != "ABCDEFGHIJKLMNOP"
    assert all(box[2] <= 201 for box in _boxes(provider))


def test_a_rotated_page_is_clipped_to_its_box(tmp_path: Path) -> None:
    text = _text(_read(_spread(tmp_path / "rotated.pdf", rotation=90)))
    assert "Own Title" in text
    assert "acing" not in text


def test_a_page_with_only_facing_text_is_left_to_ocr(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "blank.pdf", [(230, 50, 18, "Facing Title")], cropbox=_LEFT_HALF)
    assert 0 not in _read(path).page_lines


def test_an_uncropped_page_reads_as_marker_reads_it(tmp_path: Path) -> None:
    path = _pdf(
        tmp_path / "plain.pdf",
        [(30, 50, 18, "Title"), (30, 120, 11, "Body text."), (230, 120, 11, "Right column.")],
    )
    ours, marker = _read(path), PdfProvider(path, {})
    assert _text(ours) == _text(marker)
    assert _boxes(ours) == _boxes(marker)


@pytest.mark.parametrize("off", [False, "false"])
def test_turned_off_reads_as_marker_does(tmp_path: Path, off: object) -> None:
    path = _spread(tmp_path / "spread.pdf")
    provider = _read(path, {pagebox.CONFIG_KEY: off})
    assert _text(provider) == _text(PdfProvider(path, {}))


def test_chars_are_kept_only_when_asked(tmp_path: Path) -> None:
    path = _spread(tmp_path / "spread.pdf")
    plain = _read(path)
    assert all(chars == [] for line in plain.get_page_lines(0) for chars in line.chars)

    kept = _read(path, {"keep_chars": True})
    chars = [c for line in kept.get_page_lines(0) for span in line.chars for c in span]
    assert chars
    assert all(centre_inside(c.polygon.bbox, [0, 0, 200, 300]) for c in chars)


def test_logs_what_it_dropped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger=pagebox.__name__):
        _read(_spread(tmp_path / "spread.pdf"))
    assert "marker_text_outside_page_box_dropped" in caplog.text


def test_marker_reads_its_own_way_again_after_the_call() -> None:
    read = marker_pdf.dictionary_output
    with clipped_to_page_box({}):
        assert marker_pdf.dictionary_output is not read
    assert marker_pdf.dictionary_output is read
    with pytest.raises(RuntimeError), clipped_to_page_box({}):
        raise RuntimeError
    assert marker_pdf.dictionary_output is read
