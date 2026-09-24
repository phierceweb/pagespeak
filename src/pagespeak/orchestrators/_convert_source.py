"""Run the right backend for a source file's format.

The one format dispatch shared by `pagespeak ingest` and the pipeline's ingest
phase, plus the suffix tables that decide it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from ..backends._docx_dispatch import DocxBackendName
from ..backends._pdf_dispatch import PdfBackendName
from ..models._models import IngestResult

PDF_SUFFIXES: frozenset[str] = frozenset({".pdf"})
MARKITDOWN_SUFFIXES: frozenset[str] = frozenset(
    {
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".htm",
        ".csv",
        ".json",
        ".xml",
        ".epub",
    }
)
# Legacy binary Office (.doc / .ppt / .xls) is deliberately excluded: MarkItDown
# does not reliably handle the pre-OOXML binary formats, so they fall through to
# a clear "Unsupported format" error rather than a silent lossy conversion.
# Convert to .docx / .pptx / .xlsx first. See docs/format-support.md.
# Markdown deliverables are already the pipeline's target format — read them
# straight into raw.md rather than round-tripping through MarkItDown (lossy on
# lists / headings / emphasis). Lets an upstream ingester hand off clean
# markdown for the cleanup → split passes.
MARKDOWN_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown"})


def unsupported_format_error(suffix: str) -> ValueError:
    """The dispatch fallthrough, shared by both ingest entry points."""
    return ValueError(
        f"Unsupported format: {suffix!r}. Supported: "
        f"{sorted(PDF_SUFFIXES | MARKITDOWN_SUFFIXES | MARKDOWN_SUFFIXES)}"
    )


def convert_source(
    src: Path,
    out: Path | None,
    *,
    suffix: str,
    pdf_backend: str,
    pdf_backend_kwargs: dict[str, Any] | None,
    heading_hierarchy: bool,
    docx_backend: str,
    docx_outline_heading_depth: int,
    device: str | None,
    force_ocr: bool,
    page_range: str | list[int] | None,
    html_base_url: str | None,
) -> IngestResult:
    """Run the backend for `src`'s format."""
    if suffix in PDF_SUFFIXES:
        from ..backends._pdf_dispatch import convert as _pdf_convert

        return _pdf_convert(
            cast(PdfBackendName, pdf_backend),
            src,
            output_dir=out,
            force_ocr=force_ocr,
            device=device,
            page_range=page_range,
            backend_kwargs=pdf_backend_kwargs,
            heading_hierarchy=heading_hierarchy,
        )
    if suffix == ".docx":
        from ..backends._docx_dispatch import convert as _docx_convert

        return _docx_convert(
            cast(DocxBackendName, docx_backend),
            src,
            output_dir=out,
            outline_heading_depth=docx_outline_heading_depth,
        )
    if suffix in MARKITDOWN_SUFFIXES:
        from ..backends._docx import convert_with_markitdown

        return convert_with_markitdown(src, output_dir=out, html_base_url=html_base_url)
    if suffix in MARKDOWN_SUFFIXES:
        from ..backends._markdown import convert_markdown

        return convert_markdown(src)
    raise unsupported_format_error(suffix)
