"""Tests for `_pdf_dispatch` — the small factory that picks `marker` /
`docling`. Heavy backends are mocked so this stays fast."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pagespeak import IngestResult
from pagespeak.backends._pdf_dispatch import (
    DEFAULT_PDF_BACKEND,
    _resolve_device,
    convert,
    get_pdf_converter,
)


def test_default_backend_is_marker() -> None:
    """Existing consumers must see no behavior change."""
    assert DEFAULT_PDF_BACKEND == "marker"


def test_get_pdf_converter_marker_returns_callable() -> None:
    fn = get_pdf_converter("marker")
    assert callable(fn)


def test_get_pdf_converter_docling_returns_callable() -> None:
    """Docling is installed in dev; this should resolve. If a future setup
    runs without `pdf-docling`, the import-error path is the next test."""
    fn = get_pdf_converter("docling")
    assert callable(fn)


def test_get_pdf_converter_docling_raises_when_uninstalled() -> None:
    """ImportError must include the exact pip extra so the user can
    self-serve the fix. Patching the submodule to None makes
    `from ._pdf_docling import …` raise ImportError."""
    with (
        patch.dict("sys.modules", {"pagespeak.backends._pdf_docling": None}),
        pytest.raises(ImportError, match=r"pagespeak\[pdf-docling\]"),
    ):
        get_pdf_converter("docling")


def test_get_pdf_converter_unknown_name_value_errors() -> None:
    with pytest.raises(ValueError, match="Unknown pdf_backend"):
        get_pdf_converter("bogus")  # type: ignore[arg-type]


def test_convert_routes_to_marker(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="marker said hi", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake) as mock_marker:
        result = convert("marker", src, output_dir=tmp_path / "out")
    mock_marker.assert_called_once()
    assert result.markdown == "marker said hi"


def test_convert_routes_to_docling(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="docling said hi", source_format="pdf")
    with patch(
        "pagespeak.backends._pdf_docling.convert_pdf_docling", return_value=fake
    ) as mock_docling:
        result = convert("docling", src, output_dir=tmp_path / "out")
    mock_docling.assert_called_once()
    assert result.markdown == "docling said hi"


def test_convert_forwards_backend_kwargs(tmp_path: Path) -> None:
    """`backend_kwargs` must reach the active backend so consumers can
    pass through Marker-/Docling-specific options without waiting for
    pagespeak to surface every flag."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="x", source_format="pdf")
    with patch(
        "pagespeak.backends._pdf_docling.convert_pdf_docling", return_value=fake
    ) as mock_docling:
        convert(
            "docling",
            src,
            backend_kwargs={"do_formula_enrichment": True, "images_scale": 2.0},
        )
    kwargs = mock_docling.call_args.kwargs
    assert kwargs["backend_kwargs"] == {"do_formula_enrichment": True, "images_scale": 2.0}


def test_convert_default_backend_kwargs_is_empty_dict(tmp_path: Path) -> None:
    """Calling `convert(...)` without `backend_kwargs` must hand the
    backend an empty dict, not None — backends pattern-match on dict
    items and shouldn't have to defensive-check None."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="x", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake) as mock_marker:
        convert("marker", src)
    assert mock_marker.call_args.kwargs["backend_kwargs"] == {}


# --- _resolve_device (PAGESPEAK_DEFAULT_DEVICE) ---


def test_resolve_device_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_DEFAULT_DEVICE", "cpu")
    assert _resolve_device("mps") == "mps"


def test_resolve_device_env_used_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_DEFAULT_DEVICE", "cpu")
    assert _resolve_device(None) == "cpu"


def test_resolve_device_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGESPEAK_DEFAULT_DEVICE", raising=False)
    assert _resolve_device(None) is None


def test_convert_forwards_env_device_to_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: env var → dispatch resolves → backend receives the device.
    This is the actual user-visible behavior the env var promises."""
    monkeypatch.setenv("PAGESPEAK_DEFAULT_DEVICE", "cpu")
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="x", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake) as mock_marker:
        convert("marker", src)
    assert mock_marker.call_args.kwargs["device"] == "cpu"


def test_convert_explicit_device_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAGESPEAK_DEFAULT_DEVICE", "cpu")
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    fake = IngestResult(markdown="x", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake) as mock_marker:
        convert("marker", src, device="mps")
    assert mock_marker.call_args.kwargs["device"] == "mps"
