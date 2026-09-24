"""Tests for pagespeak._pdf — page-range parser, Marker version guard, and
Marker-config propagation.

Marker is mocked at the module boundary; no real model loading happens. Tests
that patch Marker's modules skip when marker-pdf isn't installed; the rest run
everywhere.
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
def _pin_marker_1x(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the convert tests independent of the installed Marker version."""
    monkeypatch.setattr(pdf_mod, "_installed_marker_version", lambda: "1.10.2")


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
    pytest.importorskip("marker")
    PdfCls, models_fn, text_fn = _patch_marker()
    with (
        patch("marker.converters.pdf.PdfConverter", PdfCls),
        patch("marker.models.create_model_dict", models_fn),
        patch("marker.output.text_from_rendered", text_fn),
    ):
        result = convert_pdf(pdf_path, **kwargs)  # type: ignore[arg-type]
    return PdfCls, result


@pytest.mark.parametrize("version", ["2.0.0", "2.0.0rc1", "2.0.0.dev0", "3.1"])
def test_marker_guard_refuses_2x(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_mod, "_installed_marker_version", lambda: version)
    with pytest.raises(ImportError, match=rf"marker-pdf {version} .*<2"):
        pdf_mod._require_marker_below_2()


@pytest.mark.parametrize("version", ["1.10.2", "1.10.2+local", "1.10.2.post1", "0.2.0", None])
def test_marker_guard_accepts_below_2(version: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_mod, "_installed_marker_version", lambda: version)
    pdf_mod._require_marker_below_2()


def test_convert_pdf_refuses_marker_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard runs before Marker is imported, so no Marker install is needed."""
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(pdf_mod, "_installed_marker_version", lambda: "2.0.0")
    with pytest.raises(ImportError, match=r"marker-pdf 2\.0\.0.*<2"):
        convert_pdf(pdf_path)


def test_convert_pdf_accepts_marker_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(pdf_mod, "_installed_marker_version", lambda: "1.10.2")
    _, result = _run_convert(pdf_path)
    assert result.markdown == "body"  # type: ignore[attr-defined]


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
    pytest.importorskip("marker")
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
    pytest.importorskip("marker")
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
    pytest.importorskip("marker")

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
    pytest.importorskip("marker")

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


def test_marker_keeps_its_lifted_pixel_limit_only_for_its_own_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker sets Pillow's decompression-bomb limit to None when it is imported,
    which would leave every later image open in the process unguarded."""
    from PIL import Image

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    during: list[int | None] = []
    PdfCls, models_fn, text_fn = _patch_marker()
    PdfCls.return_value.side_effect = lambda _p: during.append(Image.MAX_IMAGE_PIXELS)
    pytest.importorskip("marker")
    with (
        patch("marker.converters.pdf.PdfConverter", PdfCls),
        patch("marker.models.create_model_dict", models_fn),
        patch("marker.output.text_from_rendered", text_fn),
    ):
        convert_pdf(pdf_path)
        assert Image.MAX_IMAGE_PIXELS == 89_478_485
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200_000_000)
        convert_pdf(pdf_path)
    assert during == [None, None]
    assert Image.MAX_IMAGE_PIXELS == 200_000_000
