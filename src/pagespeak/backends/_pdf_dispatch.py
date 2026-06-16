"""PDF-backend selection: pick `marker`, `docling`, or `tophat` per call.

Pagespeak's PDF backends:

- **Marker** (`_pdf.convert_pdf`) — fast, the default. Heading
  hierarchy and tables flatten on academic PDFs; surya can crash on MPS.
- **Docling** (`_pdf_docling.convert_pdf_docling`) — accuracy-first
  alternative. Preserves heading hierarchy, TableFormer-grade
  tables, formula → LaTeX, MPS-clean. Slower per page.
- **Top Hat** (`_tophat.convert_pdf_tophat`) — special-purpose, for Top Hat
  quiz-export PDFs only. Reads the text layer (no layout/ML), promoting each
  `Question N` marker to a `## Question N` heading so the pipeline splits one
  file per question; marks the correct answer (grey-letter signal) and extracts
  embedded figures for the vision pass. Lightweight (`pypdfium2`).

The `convert(name)` factory returns the right callable. Both convert
functions accept the same kwargs and return the same `IngestResult`
shape, so callers (`_dispatch.to_markdown`, `_chunk._run_one_chunk`)
need only forward arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pf_core.utils.env import resolve_str

from ..models._models import IngestResult

PdfBackendName = Literal["marker", "docling", "tophat"]
DEFAULT_PDF_BACKEND: PdfBackendName = "marker"

# Type for any backend's convert callable.
PdfConverter = Callable[..., IngestResult]

# Operational tunable (env-configurable): lets the user pin
# a default torch device (`cpu` / `mps` / `cuda`) in `.env` rather than
# typing `--device cpu` on every call. Use case: Apple Silicon machines
# that hit the surya/MPS crash
# can set `PAGESPEAK_DEFAULT_DEVICE=cpu` once and forget. Explicit
# `--device` / `device=` still wins.
_DEFAULT_DEVICE_ENV_VAR = "PAGESPEAK_DEFAULT_DEVICE"


def _resolve_device(explicit: str | None) -> str | None:
    """Resolve the torch device: explicit arg > `PAGESPEAK_DEFAULT_DEVICE` env > None.

    `None` means "leave the torch device unset and let the backend pick".
    """
    value: str | None = resolve_str(explicit, _DEFAULT_DEVICE_ENV_VAR, default=None)
    return value


def get_pdf_converter(name: PdfBackendName) -> PdfConverter:
    """Return the convert function for the named PDF backend.

    Raises `ImportError` (with the exact pip extra) if the backend's
    package isn't installed. Raises `ValueError` for unknown names.
    """
    if name == "marker":
        from ._pdf import convert_pdf

        return convert_pdf
    if name == "docling":
        try:
            from ._pdf_docling import convert_pdf_docling
        except ImportError as e:
            raise ImportError(
                "Docling PDF backend requires the docling package. "
                "Install with: pip install pagespeak[pdf-docling]"
            ) from e
        return convert_pdf_docling
    if name == "tophat":
        try:
            from ._tophat import convert_pdf_tophat
        except ImportError as e:
            raise ImportError(
                "The Top Hat PDF backend requires pypdfium2. "
                "Install with: pip install pagespeak[tophat]"
            ) from e
        return convert_pdf_tophat
    raise ValueError(f"Unknown pdf_backend: {name!r}. Valid: 'marker' | 'docling' | 'tophat'.")


def convert(
    name: PdfBackendName,
    path: Path,
    *,
    output_dir: Path | None = None,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    backend_kwargs: dict[str, Any] | None = None,
) -> IngestResult:
    """Single entry point for both PDF backends. Routes to the right
    converter and forwards the common args. `backend_kwargs` is the
    backend-specific escape hatch (e.g. `docling_kwargs` /
    `marker_kwargs` from `to_markdown`)."""
    converter = get_pdf_converter(name)
    return converter(
        path,
        output_dir=output_dir,
        force_ocr=force_ocr,
        device=_resolve_device(device),
        page_range=page_range,
        backend_kwargs=backend_kwargs or {},
    )
