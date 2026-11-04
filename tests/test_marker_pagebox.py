"""Tests for backends._marker_pagebox — Marker's text layer, keeping only the text
inside each page's visible box."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import marker.providers.pdf as marker_pdf
import pdftext.extraction as pdftext_extraction
import pypdfium2 as pdfium
import pytest
from fpdf import FPDF
from marker.providers.pdf import PdfProvider

import pagespeak.backends._marker_pagebox as pagebox
from pagespeak.backends._marker_pagebox import centre_inside, clip_pages, clipped_to_page_box

# A 400 x 300 pt spread whose CropBox keeps one half: one page cut from a
# two-page spread, the facing page's text still in the file.
_SPREAD = (400, 300)
_LEFT_HALF = (0, 0, 200, 300)
_RIGHT_HALF = (200, 0, 400, 300)
# Each half's own text, then the text that belongs to the other half.
_HALVES = [(_LEFT_HALF, "Own Title", "Facing"), (_RIGHT_HALF, "Facing Title", "Own")]


def _pdf(
    path: Path,
    texts: list[tuple[float, float, int, str]],
    *,
    cropbox: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
    size: tuple[float, float] = _SPREAD,
) -> str:
    raw = path.with_suffix(".raw.pdf")
    doc = FPDF(unit="pt", format=size)
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


def _spread(
    path: Path, *, rotation: int = 0, cropbox: tuple[float, float, float, float] = _LEFT_HALF
) -> str:
    texts = [
        (30, 50, 18, "Own Title"),
        (230, 50, 18, "Facing Title"),
        (30, 120, 11, "Body text on this page."),
        (230, 120, 11, "Body text on the facing page."),
    ]
    return _pdf(path, texts, cropbox=cropbox, rotation=rotation)


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
    assert not centre_inside([-12, 10, -4, 20], page)  # left of the box
    assert not centre_inside([196, 10, 204, 20], page)  # centre on the far edge: the next page's
    assert centre_inside([-4, 10, 4, 20], page)  # centre on the near edge


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
    return {
        "bbox": [0.0, 0.0, 200.0, 300.0],
        "width": 200,
        "height": 300,
        "rotation": 0,
        "blocks": [{"lines": [line], "bbox": line["bbox"]}],
    }


def _kept(page: dict[str, Any]) -> str:
    return "".join(s["text"] for b in page["blocks"] for line in b["lines"] for s in line["spans"])


def test_a_word_goes_by_its_middle_not_its_first_letter() -> None:
    page = _page([_char(c, 172 + 8 * i, i) for i, c in enumerate("HEADLINE")])
    clip_pages([page], keep_chars=False)
    assert _kept(page) == ""  # it starts inside the box; its middle (204) lies past the edge


def test_a_word_split_across_two_spans_goes_whole_to_one_page() -> None:
    chars = [_char(c, 172 + 8 * i, i) for i, c in enumerate("HEADLINE")]
    page = _page(chars[:4], chars[4:])  # a change of font inside the word
    clip_pages([page], keep_chars=False)
    assert _kept(page) == ""


def test_each_ideograph_goes_to_the_page_its_own_middle_is_on() -> None:
    run = "灯台の光が海を照らす"
    page = _page([_char(c, 160 + 10 * i, i) for i, c in enumerate(run)])
    clip_pages([page], keep_chars=False)
    assert _kept(page) == run[:4]


def test_clip_pages_rebuilds_a_span_from_the_characters_inside() -> None:
    page = _page([_char(c, 180 + 10 * i, i) for i, c in enumerate("AB DE")])
    assert clip_pages([page], keep_chars=False) == (3, 1)
    (span,) = page["blocks"][0]["lines"][0]["spans"]
    assert span["text"] == "AB"
    assert span["bbox"] == [180, 10, 198, 20]
    assert (span["char_start_idx"], span["char_end_idx"]) == (0, 1)
    assert "chars" not in span
    assert page["blocks"][0]["lines"][0]["bbox"] == [180, 10, 198, 20]
    assert page["blocks"][0]["bbox"] == [180, 10, 198, 20]


def test_clip_pages_keeps_the_tail_of_a_span_that_starts_left_of_the_box() -> None:
    page = _page([_char(c, -30 + 10 * i, i) for i, c in enumerate("AB DE")])
    assert clip_pages([page], keep_chars=False) == (3, 1)
    (span,) = page["blocks"][0]["lines"][0]["spans"]
    assert span["text"] == "DE"
    assert (span["char_start_idx"], span["char_end_idx"]) == (3, 4)
    assert span["bbox"] == [0, 10, 18, 20]


def test_a_rebuilt_span_reads_as_pdftext_reads_one() -> None:
    """A ligature spelled out, a soft hyphen made a line-end hyphen."""
    chars = [_char(c, 10 + 10 * i, i) for i, c in enumerate("ﬁne\x02 ")] + [_char("Z", 250, 5)]
    page = _page(chars)
    assert clip_pages([page], keep_chars=False) == (1, 1)
    (span,) = page["blocks"][0]["lines"][0]["spans"]
    assert span["text"] == "fine-\n "


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


@pytest.mark.parametrize(("cropbox", "own", "other"), _HALVES)
def test_drops_the_facing_pages_text(
    tmp_path: Path, cropbox: tuple[float, float, float, float], own: str, other: str
) -> None:
    provider = _read(_spread(tmp_path / "spread.pdf", cropbox=cropbox))
    text = _text(provider)
    assert own in text
    assert other not in text
    assert all(box[0] >= -1 and box[2] <= 201 for box in _boxes(provider)), _boxes(provider)


def test_a_line_across_the_gutter_parts_between_words(tmp_path: Path) -> None:
    """Each word goes whole to the page its middle is on, never half to each."""
    words = ["ABCDEFGH", "IJKLMNOP", "QRSTUVWX", "YZABCDEF"]
    sizer = FPDF(unit="pt")
    sizer.set_font("Helvetica", size=14)
    # The gutter runs through the second word, a little right of its middle.
    x = 200 - sizer.get_string_width(f"{words[0]} ") - 0.6 * sizer.get_string_width(words[1])
    line = [(x, 80, 14, " ".join(words))]
    left = _text(_read(_pdf(tmp_path / "left.pdf", line, cropbox=_LEFT_HALF))).split()
    right = _text(_read(_pdf(tmp_path / "right.pdf", line, cropbox=_RIGHT_HALF))).split()
    assert (left, right) == (words[:2], words[2:])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(("offset", "side"), [(-0.3, "left"), (0.3, "right")])
def test_a_word_by_the_gutter_of_an_a4_spread_goes_to_its_own_page(
    tmp_path: Path, rotation: int, offset: float, side: str
) -> None:
    """pdftext rounds a 595.28pt page up to 596: the box is the page's true size."""
    w, h = 595.28, 841.89
    sizer = FPDF(unit="pt")
    sizer.set_font("Helvetica", size=18)
    line = [(w + offset - sizer.get_string_width("GUTTER") / 2, 100, 18, "GUTTER")]
    kept = {}
    for name, box in (("left", (0, 0, w, h)), ("right", (w, 0, 2 * w, h))):
        pdf = _pdf(tmp_path / f"{name}.pdf", line, cropbox=box, rotation=rotation, size=(2 * w, h))
        lines = _read(pdf).page_lines.get(0, [])  # a page left with no text has no lines
        kept[name] = any("GUTTER" in span.text for line in lines for span in line.spans)
    assert kept == {"left": side == "left", "right": side == "right"}


@pytest.mark.parametrize(("cropbox", "own", "other"), _HALVES)
def test_a_rotated_page_is_clipped_to_its_box(
    tmp_path: Path, cropbox: tuple[float, float, float, float], own: str, other: str
) -> None:
    text = _text(_read(_spread(tmp_path / "rotated.pdf", rotation=90, cropbox=cropbox)))
    assert own in text
    assert other not in text


def test_a_clipped_page_reads_as_the_page_printed_alone(tmp_path: Path) -> None:
    """Spacing aside: the clip leaves a kept line's own space or line end in place."""
    own = [
        (30, 50, 18, "Own Title"),
        (30, 120, 11, "The lamp room holds a hyphen-"),
        (30, 134, 11, "ated word and the beam."),
    ]
    facing = [(230, 50, 18, "Facing Title"), (230, 120, 11, "Facing body line one.")]
    clipped = _text(_read(_pdf(tmp_path / "spread.pdf", own + facing, cropbox=_LEFT_HALF)))
    alone = _text(PdfProvider(_pdf(tmp_path / "alone.pdf", own, cropbox=_LEFT_HALF), {}))
    assert clipped.split() == alone.split()


def test_a_tables_text_is_read_clipped_too(tmp_path: Path) -> None:
    """Marker's table processor reads the page again, through pdftext's `table_output`;
    a facing line on a row's baseline widens the row past the table, which then loses it."""
    import pdftext.extraction as extraction

    texts: list[tuple[float, float, int, str]] = []
    for i, y in enumerate((60, 80, 100)):
        texts += [(30, y, 10, f"Cell{i}A"), (110, y, 10, f"Cell{i}B")]
        if i != 1:
            texts.append((230, y, 10, f"facing line {i}"))
    path = _pdf(tmp_path / "table.pdf", texts, cropbox=_LEFT_HALF)
    table = {"tables": [[10, 40, 190, 110]], "img_size": [200, 300]}
    with clipped_to_page_box({}):
        ((cells,),) = extraction.table_output(path, [table])
    assert [c["text"] for c in cells] == [
        "Cell0A",
        "Cell0B",
        "Cell1A",
        "Cell1B",
        "Cell2A",
        "Cell2B",
    ]


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
    with clipped_to_page_box({}):
        pages = pdftext_extraction.dictionary_output(path)  # read with chars, to clip by them
    spans = [s for p in pages for b in p["blocks"] for line in b["lines"] for s in line["spans"]]
    assert spans and not any("chars" in span for span in spans)

    kept = _read(path, {"keep_chars": True})
    chars = [c for line in kept.get_page_lines(0) for span in line.chars for c in span]
    assert chars
    assert all(centre_inside(c.polygon.bbox, [0, 0, 200, 300]) for c in chars)


def test_logs_what_it_dropped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger=pagebox.__name__):
        _read(_spread(tmp_path / "spread.pdf"))
    assert "marker_text_outside_page_box_dropped" in caplog.text


def test_marker_reads_its_own_way_again_after_the_call() -> None:
    import pdftext.extraction as extraction

    read, table_read = marker_pdf.dictionary_output, extraction.dictionary_output
    with clipped_to_page_box({}):
        assert marker_pdf.dictionary_output is not read
        assert extraction.dictionary_output is not table_read
    assert marker_pdf.dictionary_output is read
    assert extraction.dictionary_output is table_read
    with pytest.raises(RuntimeError), clipped_to_page_box({}):
        raise RuntimeError
    assert marker_pdf.dictionary_output is read
    assert extraction.dictionary_output is table_read
