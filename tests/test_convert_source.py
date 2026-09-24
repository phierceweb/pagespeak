"""Tests for orchestrators._convert_source — format → backend dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.models._models import IngestResult
from pagespeak.orchestrators._convert_source import convert_source

_DEFAULTS: dict[str, object] = {
    "pdf_backend": "docling",
    "pdf_backend_kwargs": {"images_scale": 2.0},
    "heading_hierarchy": True,
    "docx_backend": "python-docx",
    "docx_outline_heading_depth": 2,
    "device": "cpu",
    "force_ocr": True,
    "page_range": "0-3",
    "html_base_url": "https://example.com/help/",
}


def _convert(src: Path, out: Path | None) -> IngestResult:
    return convert_source(src, out, suffix=src.suffix.lower(), **_DEFAULTS)  # type: ignore[arg-type]


def test_pdf_goes_to_the_pdf_backend_with_every_option(tmp_path: Path, monkeypatch) -> None:
    from pagespeak.backends import _pdf_dispatch

    seen: dict[str, object] = {}

    def fake(name, src, **kwargs):
        seen.update(kwargs, name=name)
        return IngestResult(markdown="pdf", source_format="pdf")

    monkeypatch.setattr(_pdf_dispatch, "convert", fake)
    assert _convert(tmp_path / "a.pdf", tmp_path).markdown == "pdf"
    assert seen == {
        "name": "docling",
        "output_dir": tmp_path,
        "force_ocr": True,
        "device": "cpu",
        "page_range": "0-3",
        "backend_kwargs": {"images_scale": 2.0},
        "heading_hierarchy": True,
    }


def test_docx_goes_to_the_docx_backend(tmp_path: Path, monkeypatch) -> None:
    from pagespeak.backends import _docx_dispatch

    seen: dict[str, object] = {}

    def fake(name, src, **kwargs):
        seen.update(kwargs, name=name)
        return IngestResult(markdown="docx", source_format="docx")

    monkeypatch.setattr(_docx_dispatch, "convert", fake)
    assert _convert(tmp_path / "a.docx", tmp_path).markdown == "docx"
    assert seen == {"name": "python-docx", "output_dir": tmp_path, "outline_heading_depth": 2}


def test_html_goes_to_markitdown_with_its_base_url(tmp_path: Path, monkeypatch) -> None:
    from pagespeak.backends import _docx

    seen: dict[str, object] = {}

    def fake(src, **kwargs):
        seen.update(kwargs)
        return IngestResult(markdown="html", source_format="html")

    monkeypatch.setattr(_docx, "convert_with_markitdown", fake)
    assert _convert(tmp_path / "a.html", tmp_path).markdown == "html"
    assert seen == {"output_dir": tmp_path, "html_base_url": "https://example.com/help/"}


def test_markdown_passes_through(tmp_path: Path) -> None:
    src = tmp_path / "a.md"
    src.write_text("# Title\n\nBody.\n", encoding="utf-8")
    assert _convert(src, tmp_path).markdown.startswith("# Title")


def test_unsupported_suffix_names_what_is_supported(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"Unsupported format: '\.doc'.*\.docx"):
        _convert(tmp_path / "a.doc", tmp_path)
