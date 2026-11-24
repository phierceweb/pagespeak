"""The `layout` PDF backend: read a book from its text layer with a per-document profile.

For PDFs whose structure a general backend gets wrong but a reader tuned by data can
read: fonts mapped to heading levels, ruled tables read from their grid, figures matched
to their captions, page furniture dropped. The profile (`<source>.layout.yaml` beside
the PDF, or ``{"profile": "<path>"}`` in `--pdf-backend-kwargs`) carries the book's
signals; see docs/layout-backend.md.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pw_foundation.exceptions import InvalidInputError

from ..models._models import IngestResult
from ._layout_document import build, read_pages
from ._layout_output import clip_crops, render_crops, write_layout_source_map
from ._layout_pages import read_page
from ._layout_pictures import PageSource
from ._layout_profile import LayoutProfile, load_profile

PROFILE_SUFFIX = ".layout.yaml"


def profile_path(path: Path, backend_kwargs: dict[str, object] | None) -> Path:
    """The profile a source uses: the `profile` backend kwarg, else `<source stem>.layout.yaml` beside it."""
    given = (backend_kwargs or {}).get("profile")
    return Path(str(given)).expanduser() if given else path.with_suffix(PROFILE_SUFFIX)


def _check_faces(records: dict[int, dict[str, Any]], prof: LayoutProfile, prof_file: Path) -> None:
    """Refuse a profile whose body or heading face sets no text on the pages read."""
    faces = Counter(ln["font"] for rec in records.values() for ln in rec["lines"])
    for role, face in (("body", prof.body_font), ("heading", prof.heading_font)):
        if not any(found.startswith(face) for found in faces):
            common = ", ".join(found for found, _ in faces.most_common(8))
            raise InvalidInputError(
                f"layout profile {prof_file}: fonts.{role} {face!r} matches no text on the pages "
                f"read; the faces found there: {common}"
            )


def convert_pdf_layout(
    path: Path,
    *,
    output_dir: Path | None = None,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    heading_hierarchy: bool = False,
    backend_kwargs: dict[str, object] | None = None,
) -> IngestResult:
    """Convert a PDF with the layout reader and its profile.

    Matches the `PdfConverter` signature. `force_ocr`, `device` and `heading_hierarchy` are
    ignored; the pages read are the profile's, so `page_range` is refused. With
    `output_dir`, picture crops go to `output_dir/images/` and the source map beside them.

    Raises:
        InvalidInputError: no profile, a malformed one, one whose faces the book never
            uses, or a `page_range`.
    """
    if page_range:
        raise InvalidInputError(
            "the layout backend reads the pages its profile names; drop --page-range"
        )
    prof_file = profile_path(path, backend_kwargs)
    if not prof_file.is_file():
        raise InvalidInputError(
            f"the layout backend needs a profile: none at {prof_file} (see docs/layout-backend.md)"
        )
    prof = load_profile(prof_file)
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    first, last = prof.pages
    if last >= len(doc):
        raise InvalidInputError(
            f"layout profile {prof_file}: pages run to {last}, the PDF has {len(doc)} (0-based)"
        )
    records = {
        pg: read_page(doc, pg, acute_as_prime=prof.acute_as_prime) for pg in range(first, last + 1)
    }
    _check_faces(records, prof, prof_file)
    src = PageSource(doc, records)
    text, crops = build(src, prof)
    images: list[Path] = []
    if output_dir is not None:
        crops = clip_crops(doc, crops)
        empty = [name for _, (x0, y0, x1, y1), name, _ in crops if x1 <= x0 or y1 <= y0]
        if empty:
            raise InvalidInputError(
                f"layout profile {prof_file}: nothing of the page is inside the crop of "
                f"{', '.join(empty)}; check document.crop_overrides and raster_tables"
            )
        images = render_crops(doc, crops, output_dir / "images")
        read = read_pages(prof)
        bottom = min((float(doc[pg].get_cropbox()[1]) for pg in read), default=0.0)
        write_layout_source_map(output_dir, path, prof, read, crops, bottom)
    return IngestResult(
        markdown=text,
        images=images,
        diagrams=[],
        source_format="pdf",
        structure_authoritative=True,
        authored_headings=True,
    )
