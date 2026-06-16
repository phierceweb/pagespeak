"""DOCX backend selection — mirrors `backends/_pdf_dispatch.py`.

`markitdown` (default) = the legacy MarkItDown path (also the only
path for non-.docx office formats). `python-docx` = the structure-
faithful backend. python-docx is an optional extra; the ImportError
names the exact pip extra, mirroring the docling pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ..models._models import IngestResult

DocxBackendName = Literal["markitdown", "python-docx"]
DEFAULT_DOCX_BACKEND: DocxBackendName = "markitdown"

DocxConverter = Callable[..., IngestResult]


def get_docx_converter(name: DocxBackendName) -> DocxConverter:
    """Return the convert function for the named DOCX backend.
    Raises `ImportError` (with the exact pip extra) when python-docx
    isn't installed; `ValueError` for unknown names."""
    if name == "markitdown":
        from ._docx import convert_with_markitdown

        return convert_with_markitdown
    if name == "python-docx":
        try:
            import docx  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "The python-docx DOCX backend requires python-docx. "
                "Install with: pip install pagespeak[docx-structured]"
            ) from e
        from ._docx_structured import convert_structured

        return convert_structured
    raise ValueError(f"Unknown docx_backend: {name!r}. Valid: 'markitdown' | 'python-docx'.")


def convert(
    name: DocxBackendName,
    path: Path,
    *,
    output_dir: Path | None = None,
    outline_heading_depth: int = 0,
) -> IngestResult:
    """Single entry point for both DOCX backends.

    ``outline_heading_depth`` is only meaningful for the
    ``python-docx`` backend (the switch — how many top Word-outline
    levels to override into headings; default 0 retains the whole
    outline as a list). Not forwarded to MarkItDown (no outline model).
    """
    fn = get_docx_converter(name)
    if name == "python-docx":
        return fn(
            path,
            output_dir=output_dir,
            outline_heading_depth=outline_heading_depth,
        )
    return fn(path, output_dir=output_dir)
