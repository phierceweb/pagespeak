from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Any

from pf_core.log import get_logger

from ..models._models import IngestResult
from ..services._image_refs import ImageRef, replace_image_refs

logger = get_logger(__name__)


# Tracks the device the marker model cache was first loaded on so we can warn
# when a later call passes a different device (Marker caches globally per
# process; the second device value is silently ignored).
_first_device: str | None = None

# Pillow's default decompression-bomb limit.
_PILLOW_MAX_IMAGE_PIXELS = 89_478_485


def _installed_marker_version() -> str | None:
    try:
        return metadata.version("marker-pdf")
    except metadata.PackageNotFoundError:
        return None


def _require_marker_below_2() -> None:
    """Refuse Marker 2.x: 2.0 converted only a document's first pages under pagespeak, exit 0."""
    version = _installed_marker_version()
    if version is None:
        return
    try:
        major = int(version.split(".")[0])
    except ValueError:
        return
    if major >= 2:
        raise ImportError(
            f"marker-pdf {version} is not supported: Marker 2.0 silently truncated "
            "documents under pagespeak. Install marker-pdf<2: pip install 'marker-pdf<2'"
        )


@contextmanager
def _pixel_limit_lifted_for_marker() -> Iterator[None]:
    """Marker lifts Pillow's bomb limit process-wide when it is imported; keep that to its own call."""
    from PIL import Image

    before = Image.MAX_IMAGE_PIXELS or _PILLOW_MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        yield
    finally:
        Image.MAX_IMAGE_PIXELS = before


def _run_marker(path: Path, config: dict[str, object]) -> tuple[str, dict[str, Any]]:
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except ImportError as e:
        raise ImportError(
            "PDF support requires marker-pdf. Install with: pip install pagespeak[pdf]"
        ) from e

    converter = PdfConverter(
        artifact_dict=create_model_dict(),
        config=config or None,
    )
    try:
        rendered = converter(str(path))
    except PermissionError as e:
        if "sysconf" in str(e) or "Operation not permitted" in str(e):
            raise PermissionError(
                "Marker's internal ProcessPoolExecutor failed to start. "
                "This usually means the shell is sandboxed and "
                '`os.sysconf("SC_SEM_NSEMS_MAX")` is denied. '
                "Re-run with broader permissions (in Cursor: "
                '`required_permissions=["all"]`). '
                "See docs/operations.md for details."
            ) from e
        raise
    markdown_text, _, images = text_from_rendered(rendered)
    return markdown_text, images


def _prefix_bare_image_refs(markdown: str, saved_basenames: set[str]) -> str:
    """Point a bare `![alt](foo.png)` at the extracted `images/foo.png`."""

    def _repl(ref: ImageRef) -> str | None:
        if "/" in ref.target or "\\" in ref.target:
            return None
        if ref.target not in saved_basenames:
            return None
        return ref.retargeted(f"images/{ref.target}")

    return replace_image_refs(markdown, _repl)[0]


def parse_page_range(spec: str | list[int]) -> list[int]:
    """Parse a page-range spec into a sorted, deduplicated list of 0-based ints.

    Accepts:
        - A list[int] (returned sorted/deduped).
        - A string like `"5"`, `"0-3"`, `"0-3,5,7-9"`.

    Page indices are 0-based — `"0"` means the first page. Marker uses 0-based
    internally, so the input format passes through directly.
    """
    if isinstance(spec, list):
        return sorted(set(spec))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def convert_pdf(
    path: Path,
    *,
    output_dir: Path | None = None,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    heading_hierarchy: bool = False,
    backend_kwargs: dict[str, object] | None = None,
) -> IngestResult:
    """Convert a PDF to markdown via Marker.

    Marker is heavy (torch + surya). Imported lazily so DOCX-only consumers
    don't pay the cost.

    Args:
        path: Source PDF.
        output_dir: Where to save extracted images (created if missing).
        force_ocr: Force surya OCR even on text-bearing PDFs.
        device: Override the torch device. Set via `TORCH_DEVICE` env var
            before Marker's lazy import. `"cpu"` works around the surya/MPS
            crash on Apple Silicon. `None` (default) leaves the env unchanged.
            **Caveat:** Marker caches its model artifacts globally per process
            on the first call; subsequent calls with a different `device` are
            silently ignored (a WARNING is logged).
        page_range: Convert only these pages (0-based). String spec like
            `"0-19"` / `"0-3,5,7-9"` or `list[int]`. `None` converts all pages.
        heading_hierarchy: Accepted for protocol compatibility and ignored —
            Marker has no bookmark/outline/numbering signal, so heading depth
            always comes from its font clustering. Docling-only.
        backend_kwargs: Forwarded into Marker's `PdfConverter(config=…)`.
            Use to reach Marker-specific options the common surface
            doesn't expose. Empty by default.
    """
    global _first_device
    if device is not None:
        if _first_device is None:
            _first_device = device
            os.environ["TORCH_DEVICE"] = device
        elif device != _first_device:
            logger.warning(
                "device=%r ignored; Marker model cache locked to %r from the "
                "first conversion in this process",
                device,
                _first_device,
            )

    _require_marker_below_2()
    config: dict[str, object] = {}
    if force_ocr:
        config["force_ocr"] = True
    if page_range is not None:
        config["page_range"] = parse_page_range(page_range)
    if backend_kwargs:
        config.update(backend_kwargs)

    with _pixel_limit_lifted_for_marker():
        markdown_text, images = _run_marker(path, config)

    saved_images: list[Path] = []
    if output_dir is not None:
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for name, img in images.items():
            out_path = images_dir / name
            img.save(out_path)
            saved_images.append(out_path)
            logger.debug("saved_pdf_image path=%s", out_path)

    # Marker emits image refs by basename (e.g. `![](_page_5_Picture_16.jpeg)`)
    # but we save them under `images/`. Rewrite refs to `images/<basename>` so
    # the consolidated markdown resolves correctly relative to the output dir.
    if saved_images:
        saved_basenames = {p.name for p in saved_images}

        markdown_text = _prefix_bare_image_refs(markdown_text, saved_basenames)

    return IngestResult(
        markdown=markdown_text,
        images=saved_images,
        source_format="pdf",
    )
