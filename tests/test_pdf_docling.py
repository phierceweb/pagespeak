"""Tests for the Docling PDF backend wrapper.

Real Docling conversions take minutes and download model weights, so the
unit suite mocks at the `DocumentConverter` boundary. A local script
exercises the real path manually."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pagespeak.backends._pdf_docling import (
    _docling_page_range,
    _picture_filename,
    _replace_placeholders,
    convert_pdf_docling,
)

# --- _docling_page_range ---


def test_docling_page_range_none_returns_none() -> None:
    assert _docling_page_range(None) is None


def test_docling_page_range_translates_zero_based_to_one_based() -> None:
    assert _docling_page_range("0-49") == (1, 50)


def test_docling_page_range_accepts_list() -> None:
    assert _docling_page_range([0, 1, 2, 3]) == (1, 4)


def test_docling_page_range_collapses_discontiguous_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Docling supports only one contiguous (start, end) — non-contiguous
    input collapses to the (min, max) hull, with a WARNING so the user
    knows they got more pages than they asked for."""
    with caplog.at_level("WARNING"):
        result = _docling_page_range("0-3,7-9")
    assert result == (1, 10)
    assert any("docling_page_range_collapsed" in r.message for r in caplog.records)


def test_docling_page_range_single_page() -> None:
    assert _docling_page_range([5]) == (6, 6)


# --- _picture_filename ---


def test_picture_filename_uses_page_no_when_available() -> None:
    pic = SimpleNamespace(prov=[SimpleNamespace(page_no=4)])
    assert _picture_filename(pic, idx=2) == "_page_4_Picture_2.png"


def test_picture_filename_falls_back_when_no_prov() -> None:
    pic = SimpleNamespace(prov=[])
    assert _picture_filename(pic, idx=1) == "_page_X_Picture_1.png"


# --- _replace_placeholders ---


def test_replace_placeholders_basic() -> None:
    md = "intro\n\n<!-- image -->\n\nbody\n\n<!-- image -->\n\nend"
    refs = ["![](images/a.png)", "![](images/b.png)"]
    out = _replace_placeholders(md, refs)
    assert "<!-- image -->" not in out
    assert "![](images/a.png)" in out
    assert "![](images/b.png)" in out
    # Order is preserved.
    assert out.index("a.png") < out.index("b.png")


def test_replace_placeholders_drops_when_no_refs() -> None:
    md = "before\n\n<!-- image -->\n\nafter"
    out = _replace_placeholders(md, [])
    assert "<!-- image -->" not in out
    assert "before" in out and "after" in out


def test_replace_placeholders_blank_ref_skips_image() -> None:
    """A blank ref (image extraction failed) replaces the placeholder
    with an empty string, leaving the surrounding text intact."""
    md = "x\n\n<!-- image -->\n\ny"
    out = _replace_placeholders(md, [""])
    assert "<!-- image -->" not in out
    assert "x" in out and "y" in out


def test_replace_placeholders_more_placeholders_than_refs() -> None:
    """If Docling produces more <!-- image --> than we have refs for
    (image save failed), trailing placeholders are dropped to keep the
    output clean."""
    md = "<!-- image -->\n<!-- image -->\n<!-- image -->"
    out = _replace_placeholders(md, ["![](a.png)"])
    # First placeholder gets the ref; the rest are dropped.
    assert out.count("![](a.png)") == 1
    assert "<!-- image -->" not in out


# --- convert_pdf_docling (full mock) ---


def _fake_docling_doc(picture_count: int = 0) -> MagicMock:
    """Build a minimal mock of `result.document` so the wrapper's main
    path runs without invoking Docling."""
    doc = MagicMock()
    doc.export_to_markdown.return_value = (
        "# Heading\n\n" + "\n\n".join("<!-- image -->" for _ in range(picture_count)) + "\n\nbody"
    )
    doc.pictures = []
    for i in range(picture_count):
        pic = MagicMock()
        pic.prov = [SimpleNamespace(page_no=i)]
        # Make get_image return a tiny PIL-like object whose .save writes a file.
        img = MagicMock()
        img.save = lambda target: Path(target).write_bytes(b"\x89PNG\r\n")
        pic.get_image.return_value = img
        doc.pictures.append(pic)
    return doc


def test_convert_pdf_docling_routes_through_document_converter(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    fake_doc = _fake_docling_doc(picture_count=2)
    fake_result = MagicMock(document=fake_doc)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = fake_result

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption"),
    ):
        result = convert_pdf_docling(src, output_dir=out)

    fake_converter.convert.assert_called_once()
    assert result.source_format == "pdf"
    assert "<!-- image -->" not in result.markdown
    # Two pictures => two saved images at expected names.
    assert len(result.images) == 2
    assert (out / "images" / "_page_0_Picture_0.png").exists()
    assert (out / "images" / "_page_1_Picture_1.png").exists()


def test_convert_pdf_docling_force_ocr_sets_pipeline_options(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    fake_doc = _fake_docling_doc(picture_count=0)
    fake_result = MagicMock(document=fake_doc)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = fake_result

    captured_opts: dict[str, object] = {}

    def capture_format_option(*, pipeline_options):
        captured_opts["opts"] = pipeline_options
        return MagicMock()

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption", side_effect=capture_format_option),
    ):
        convert_pdf_docling(src, force_ocr=True)

    opts = captured_opts["opts"]
    assert opts.do_ocr is True
    # force_full_page_ocr is set when the OCR options support it.
    assert getattr(opts.ocr_options, "force_full_page_ocr", False) is True


def test_convert_pdf_docling_device_routes_to_accelerator(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    fake_doc = _fake_docling_doc(picture_count=0)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = MagicMock(document=fake_doc)

    captured: dict[str, object] = {}

    def capture_format_option(*, pipeline_options):
        captured["opts"] = pipeline_options
        return MagicMock()

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption", side_effect=capture_format_option),
    ):
        convert_pdf_docling(src, device="cpu")

    assert captured["opts"].accelerator_options.device == "cpu"


def test_convert_pdf_docling_passes_page_range_to_convert(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    fake_doc = _fake_docling_doc(picture_count=0)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = MagicMock(document=fake_doc)

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption"),
    ):
        convert_pdf_docling(src, page_range="0-9")

    # Docling is 1-based, ours is 0-based — translation expected.
    assert fake_converter.convert.call_args.kwargs["page_range"] == (1, 10)


def test_convert_pdf_docling_backend_kwargs_set_pipeline_attributes(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    fake_doc = _fake_docling_doc(picture_count=0)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = MagicMock(document=fake_doc)

    captured: dict[str, object] = {}

    def capture_format_option(*, pipeline_options):
        captured["opts"] = pipeline_options
        return MagicMock()

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption", side_effect=capture_format_option),
    ):
        convert_pdf_docling(
            src,
            backend_kwargs={"do_formula_enrichment": True, "images_scale": 2.5},
        )

    opts = captured["opts"]
    assert opts.do_formula_enrichment is True
    assert opts.images_scale == 2.5


def test_convert_pdf_docling_unknown_backend_kwarg_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    fake_doc = _fake_docling_doc(picture_count=0)
    fake_converter = MagicMock()
    fake_converter.convert.return_value = MagicMock(document=fake_doc)

    with (
        patch("docling.document_converter.DocumentConverter", return_value=fake_converter),
        patch("docling.document_converter.PdfFormatOption"),
        caplog.at_level("WARNING"),
    ):
        convert_pdf_docling(src, backend_kwargs={"definitely_not_a_real_option": 42})

    assert any("docling_unknown_pipeline_option" in r.message for r in caplog.records)
