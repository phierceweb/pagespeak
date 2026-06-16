"""Markdown / plain-text passthrough backend.

A markdown deliverable is *already* the pipeline's target format, so routing
it through MarkItDown (which re-emits lists, headings, and emphasis its own
way) would be a lossy round-trip. This backend instead reads the file and
returns its text verbatim as the `raw.md`, letting the source enter the
pipeline at the cleanup stage unchanged.

No image extraction: a markdown source references images by path or URL
already, and remote-URL localization happens later in the cleanup phase
(`localize_remote_images_in_markdown`). An upstream ingester that hands off
markdown typically references images by absolute URL, so there is nothing for
this backend to pull out of a container.
"""

from __future__ import annotations

from pathlib import Path

from pf_core.log import get_logger

from ..models._models import IngestResult

logger = get_logger(__name__)


def convert_markdown(path: Path) -> IngestResult:
    """Read a markdown/text file and return its content unchanged.

    Args:
        path: The markdown (or markdown-ish plain-text) source file.

    Returns:
        An `IngestResult` whose `markdown` is the file's text verbatim, with
        no extracted images (`images=[]`).
    """
    text = path.read_text(encoding="utf-8")
    logger.debug("markdown_passthrough src=%s chars=%d", path.name, len(text))
    return IngestResult(
        markdown=text,
        images=[],
        source_format=path.suffix.lstrip("."),
    )
