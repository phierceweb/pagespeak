"""Docling PDF backend.

Wraps `docling.DocumentConverter` to match the Marker backend's
contract: same signature, same `IngestResult` return shape, same
`![](images/<name>)` ref convention in the markdown output.

Three things Docling needs translated to fit our pipeline:

1. **Image refs.** Docling emits `<!-- image -->` HTML-comment placeholders
   for every picture. Pagespeak's vision pass + cleanup expect
   `![](images/<basename>)` markdown image refs. We walk
   `result.document.pictures` in document order, save each via
   `pic.get_image(doc)`, and rewrite each placeholder to a real ref.

2. **Page range.** Docling supports `convert(..., page_range=(start, end))`
   with 1-based inclusive bounds. Our common spec is 0-based and can be
   non-contiguous. We translate `0-49` → `(1, 50)`. Non-contiguous specs
   collapse to the (min, max) hull and log a WARNING — Docling's surface
   doesn't expose per-page selection.

3. **OCR / device.** `do_ocr` and `accelerator_options.device` map
   one-to-one. `force_ocr=True` additionally sets
   `ocr_options.force_full_page_ocr=True`.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pf_core.log import get_logger

from ..models._models import IngestResult
from ._pdf import parse_page_range

if TYPE_CHECKING:
    from docling.datamodel.document import ConversionResult

logger = get_logger(__name__)

_PLACEHOLDER = "<!-- image -->"


def _docling_page_range(
    page_range: str | list[int] | None,
) -> tuple[int, int] | None:
    """Translate our 0-based, possibly-discontiguous spec to Docling's
    1-based contiguous (start, end) tuple.

    Discontiguous input collapses to (min, max). The caller-side warning
    is the user's signal that some pages may be over-included.
    """
    if page_range is None:
        return None
    pages = parse_page_range(page_range)
    if not pages:
        return None
    first = pages[0] + 1
    last = pages[-1] + 1
    contiguous = list(range(pages[0], pages[-1] + 1))
    if pages != contiguous:
        logger.warning(
            "docling_page_range_collapsed input=%r effective=(%d-%d) "
            "Docling supports only contiguous ranges; pages in the gap "
            "will be included.",
            page_range,
            first,
            last,
        )
    return (first, last)


def _picture_filename(picture: Any, idx: int) -> str:
    """Build a Marker-style filename so existing pipeline logic
    (basename → diagram map, decoration phash dedup) Just Works."""
    page_no: int | str = "X"
    try:
        if picture.prov:
            page_no = picture.prov[0].page_no
    except (AttributeError, IndexError):
        pass
    return f"_page_{page_no}_Picture_{idx}.png"


def _replace_placeholders(
    markdown: str,
    image_refs: list[str],
) -> str:
    """Replace each `<!-- image -->` placeholder, in document order,
    with the corresponding markdown image ref. If there are more
    placeholders than refs (image extraction failed), trailing
    placeholders are dropped to keep the output clean."""
    if not image_refs:
        # No images saved — drop placeholders so they don't pollute output.
        return markdown.replace(_PLACEHOLDER, "")

    out_parts: list[str] = []
    iter_refs = iter(image_refs)
    for chunk in markdown.split(_PLACEHOLDER):
        out_parts.append(chunk)
        try:
            ref = next(iter_refs)
            out_parts.append(ref)
        except StopIteration:
            out_parts.append("")  # placeholder count exceeded refs
    # Last chunk has no trailing placeholder; trim the empty appendix.
    if out_parts and out_parts[-1] == "":
        out_parts.pop()
    return "".join(out_parts)


def _save_pictures(
    result: ConversionResult,
    images_dir: Path,
) -> tuple[list[Path], list[str]]:
    """Save every picture in document order. Returns (saved paths, in-doc
    image refs). One entry per picture, even if save failed (the ref
    stays so `<!-- image -->` count matches)."""
    images_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    refs: list[str] = []
    for idx, pic in enumerate(result.document.pictures):
        try:
            img = pic.get_image(result.document)
        except Exception as e:
            logger.warning("docling_picture_get_image_failed idx=%d error=%s", idx, e)
            refs.append("")  # blank — placeholder will become empty string
            continue
        if img is None:
            refs.append("")
            continue
        name = _picture_filename(pic, idx)
        target = images_dir / name
        try:
            img.save(target)
        except Exception as e:
            logger.warning("docling_picture_save_failed path=%s error=%s", target, e)
            refs.append("")
            continue
        saved_paths.append(target)
        refs.append(f"![](images/{name})")
    return saved_paths, refs


def _build_pipeline_options(
    *,
    force_ocr: bool,
    device: str | None,
    backend_kwargs: dict[str, Any],
) -> Any:
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions()
    opts.generate_picture_images = True

    # OCR
    if force_ocr:
        opts.do_ocr = True
        # Some OCR option subclasses lack `force_full_page_ocr`; honoring
        # `do_ocr=True` is the best-effort fallback.
        with contextlib.suppress(AttributeError):
            opts.ocr_options.force_full_page_ocr = True

    # Device
    if device:
        try:
            opts.accelerator_options.device = device
        except (AttributeError, ValueError) as e:
            logger.warning("docling_device_set_failed device=%r error=%s", device, e)

    # Free-form passthrough.
    for key, value in backend_kwargs.items():
        if hasattr(opts, key):
            setattr(opts, key, value)
        else:
            logger.warning("docling_unknown_pipeline_option key=%r ignored", key)

    return opts


def convert_pdf_docling(
    path: Path,
    *,
    output_dir: Path | None = None,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    backend_kwargs: dict[str, object] | None = None,
) -> IngestResult:
    """Convert a PDF to markdown via Docling.

    Mirrors `_pdf.convert_pdf`'s signature so callers can swap backends
    by name. Returns the same `IngestResult` shape with image refs in
    `images/<basename>` form (translated from Docling's `<!-- image -->`
    placeholders).

    Args:
        path: Source PDF.
        output_dir: Where to save extracted images (created if missing).
            Required for image extraction; if None, image refs are
            dropped from the markdown.
        force_ocr: If True, set `do_ocr=True` and
            `ocr_options.force_full_page_ocr=True`.
        device: Maps to `accelerator_options.device`. Accepts `"auto"`,
            `"cpu"`, `"cuda"`, `"mps"`, `"xpu"`. `None` leaves Docling's
            default (`"auto"`).
        page_range: 0-based, inclusive. Translated to Docling's 1-based
            tuple. Discontiguous specs collapse to (min, max) with a
            WARNING.
        backend_kwargs: Pipeline-option overrides forwarded to
            `PdfPipelineOptions`. Useful keys: `do_formula_enrichment`,
            `do_code_enrichment`, `do_picture_classification`,
            `do_chart_extraction`, `do_table_structure`, `images_scale`.
            Unknown keys log a WARNING and are ignored.
    """
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:
        raise ImportError(
            "Docling backend requires the docling package. "
            "Install with: pip install pagespeak[pdf-docling]"
        ) from e

    opts = _build_pipeline_options(
        force_ocr=force_ocr,
        device=device,
        backend_kwargs=dict(backend_kwargs or {}),
    )

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)},
    )

    convert_kwargs: dict[str, Any] = {}
    docling_range = _docling_page_range(page_range)
    if docling_range is not None:
        convert_kwargs["page_range"] = docling_range

    result = converter.convert(path, **convert_kwargs)

    markdown_text = result.document.export_to_markdown()
    saved_images: list[Path] = []
    image_refs: list[str] = []
    if output_dir is not None:
        saved_images, image_refs = _save_pictures(result, output_dir / "images")
    markdown_text = _replace_placeholders(markdown_text, image_refs)

    return IngestResult(
        markdown=markdown_text,
        images=saved_images,
        source_format="pdf",
    )
