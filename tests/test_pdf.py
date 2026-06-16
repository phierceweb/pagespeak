"""Tests for pagespeak._pdf — page-range parser and Marker-config propagation.

Marker is mocked at the module boundary; no real model loading happens.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pagespeak.backends._pdf as pdf_mod
from pagespeak.backends._pdf import convert_pdf, parse_page_range

# --- parse_page_range unit tests ----------------------------------------


def test_parse_page_range_single() -> None:
    assert parse_page_range("5") == [5]


def test_parse_page_range_range() -> None:
    assert parse_page_range("0-3") == [0, 1, 2, 3]


def test_parse_page_range_mixed() -> None:
    assert parse_page_range("0-3,5,7-9") == [0, 1, 2, 3, 5, 7, 8, 9]


def test_parse_page_range_dedupes_and_sorts() -> None:
    assert parse_page_range("5,0-3,2-4") == [0, 1, 2, 3, 4, 5]


def test_parse_page_range_handles_whitespace() -> None:
    assert parse_page_range("0-3, 5, 7-9") == [0, 1, 2, 3, 5, 7, 8, 9]


def test_parse_page_range_list_passthrough() -> None:
    assert parse_page_range([5, 3, 1, 3]) == [1, 3, 5]


# --- convert_pdf with mocked Marker -------------------------------------


@pytest.fixture(autouse=True)
def _reset_pdf_state() -> Iterator[None]:
    """Reset module-level _first_device and TORCH_DEVICE around each test."""
    pdf_mod._first_device = None
    saved_env = os.environ.get("TORCH_DEVICE")
    try:
        yield
    finally:
        pdf_mod._first_device = None
        if saved_env is None:
            os.environ.pop("TORCH_DEVICE", None)
        else:
            os.environ["TORCH_DEVICE"] = saved_env


def _patch_marker() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build the three mocks needed to satisfy convert_pdf's marker imports."""
    converter_instance = MagicMock()
    converter_instance.return_value = MagicMock()  # rendered object
    pdf_converter_cls = MagicMock(return_value=converter_instance)
    create_model_dict = MagicMock(return_value={})
    text_from_rendered = MagicMock(return_value=("body", None, {}))
    return pdf_converter_cls, create_model_dict, text_from_rendered


def _run_convert(pdf_path: Path, **kwargs: object) -> tuple[MagicMock, object]:
    PdfCls, models_fn, text_fn = _patch_marker()
    with (
        patch("marker.converters.pdf.PdfConverter", PdfCls),
        patch("marker.models.create_model_dict", models_fn),
        patch("marker.output.text_from_rendered", text_fn),
    ):
        result = convert_pdf(pdf_path, **kwargs)  # type: ignore[arg-type]
    return PdfCls, result


def test_convert_pdf_no_extras_passes_none_config(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    PdfCls, _ = _run_convert(pdf_path)
    assert PdfCls.call_args.kwargs["config"] is None


def test_convert_pdf_force_ocr_appears_in_config(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    PdfCls, _ = _run_convert(pdf_path, force_ocr=True)
    assert PdfCls.call_args.kwargs["config"] == {"force_ocr": True}


def test_convert_pdf_page_range_string_propagates_as_list(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    PdfCls, _ = _run_convert(pdf_path, page_range="0-3")
    assert PdfCls.call_args.kwargs["config"] == {"page_range": [0, 1, 2, 3]}


def test_convert_pdf_page_range_list_propagates(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    PdfCls, _ = _run_convert(pdf_path, page_range=[2, 4, 6])
    assert PdfCls.call_args.kwargs["config"] == {"page_range": [2, 4, 6]}


def test_convert_pdf_device_sets_env_var(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    os.environ.pop("TORCH_DEVICE", None)
    _run_convert(pdf_path, device="cpu")
    assert os.environ.get("TORCH_DEVICE") == "cpu"


def test_convert_pdf_device_none_does_not_touch_env(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    os.environ["TORCH_DEVICE"] = "set-by-caller"
    _run_convert(pdf_path)
    assert os.environ.get("TORCH_DEVICE") == "set-by-caller"


def test_convert_pdf_device_second_call_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    with caplog.at_level(logging.WARNING, logger="pagespeak._pdf"):
        _run_convert(pdf_path, device="cpu")
        _run_convert(pdf_path, device="cuda")
    assert any("ignored" in r.message and "cuda" in r.message for r in caplog.records)


def test_convert_pdf_prefixes_bare_image_refs_with_images_dir(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_image = MagicMock()
    fake_image.save = MagicMock()
    PdfCls = MagicMock()
    converter_instance = MagicMock()
    converter_instance.return_value = MagicMock()
    PdfCls.return_value = converter_instance
    text_from_rendered = MagicMock(
        return_value=(
            "body ![](foo.png) more text ![Alt](bar.jpg)",
            None,
            {"foo.png": fake_image, "bar.jpg": fake_image},
        ),
    )
    out_dir = tmp_path / "out"
    with (
        patch("marker.converters.pdf.PdfConverter", PdfCls),
        patch("marker.models.create_model_dict", MagicMock(return_value={})),
        patch("marker.output.text_from_rendered", text_from_rendered),
    ):
        result = convert_pdf(pdf_path, output_dir=out_dir)
    assert "![](images/foo.png)" in result.markdown
    assert "![Alt](images/bar.jpg)" in result.markdown


def test_convert_pdf_does_not_double_prefix_existing_images_path(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_image = MagicMock()
    fake_image.save = MagicMock()
    PdfCls = MagicMock()
    converter_instance = MagicMock()
    converter_instance.return_value = MagicMock()
    PdfCls.return_value = converter_instance
    text_from_rendered = MagicMock(
        return_value=(
            "![](images/foo.png) and ![](sub/bar.jpg)",
            None,
            {"foo.png": fake_image, "bar.jpg": fake_image},
        ),
    )
    out_dir = tmp_path / "out"
    with (
        patch("marker.converters.pdf.PdfConverter", PdfCls),
        patch("marker.models.create_model_dict", MagicMock(return_value={})),
        patch("marker.output.text_from_rendered", text_from_rendered),
    ):
        result = convert_pdf(pdf_path, output_dir=out_dir)
    assert "![](images/foo.png)" in result.markdown
    assert "![](sub/bar.jpg)" in result.markdown
    assert "images/images/foo.png" not in result.markdown


def test_convert_pdf_translates_sandbox_permission_error(tmp_path: Path) -> None:
    """sysconf-style PermissionError from Marker → clear re-raise with doc pointer."""

    class _FakeConverter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __call__(self, _path: str) -> None:
            raise PermissionError("[Errno 1] Operation not permitted: sysconf")

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    with (  # noqa: SIM117
        patch("marker.converters.pdf.PdfConverter", _FakeConverter),
        patch("marker.models.create_model_dict", lambda: {}),
        patch("marker.output.text_from_rendered", lambda _r: ("md", None, {})),
    ):
        with pytest.raises(PermissionError, match="ProcessPoolExecutor") as excinfo:
            convert_pdf(pdf_path)
    assert "docs/operations.md" in str(excinfo.value)


def test_convert_pdf_unrelated_permission_error_passes_through(tmp_path: Path) -> None:
    class _FakeConverter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __call__(self, _path: str) -> None:
            raise PermissionError("[Errno 13] Permission denied: '/root/secret.pdf'")

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    with (  # noqa: SIM117
        patch("marker.converters.pdf.PdfConverter", _FakeConverter),
        patch("marker.models.create_model_dict", lambda: {}),
        patch("marker.output.text_from_rendered", lambda _r: ("md", None, {})),
    ):
        with pytest.raises(PermissionError, match="Permission denied") as excinfo:
            convert_pdf(pdf_path)
    assert "operations.md" not in str(excinfo.value)
    assert "ProcessPoolExecutor" not in str(excinfo.value)
