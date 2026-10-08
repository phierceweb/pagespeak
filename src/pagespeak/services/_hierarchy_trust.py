"""Is a document's heading hierarchy authoritative, or guessed?

The structure phase's level-rewriting passes exist to repair a backend that
infers heading depth from typography. When the depth instead came from the
PDF's own bookmark outline, those passes are net harmful: they read a document
that genuinely has many top-level sections as a flat-source artifact and demote
real sections. Tree shape cannot tell the two apart — "wrongly flat" and
"genuinely flat" look identical — so the signal has to be provenance.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int
from pf_core.utils.io import atomic_write_json

logger = get_logger(__name__)

# A depth-1 outline is a bare chapter list: docling still infers everything
# below it from style, so the tree is not outline-derived.
_MIN_OUTLINE_DEPTH_DEFAULT = 2
_MIN_OUTLINE_DEPTH_ENV_VAR = "PAGESPEAK_TRUSTED_OUTLINE_MIN_DEPTH"

# Written at ingest; read by the structure phase on any later resume run.
MARKER_NAME = ".pagespeak-hierarchy.json"

# Boolean marker keys that each mean "the hierarchy came from the source".
# Trust is read from these values, never from the file's existence:
# `structure_authoritative` is rewritten on every ingest and must be clearable.
_TRUST_KEYS = ("outline_promoted", "structure_authoritative")


def _min_outline_depth(override: int | None = None) -> int:
    n: int = resolve_int(override, _MIN_OUTLINE_DEPTH_ENV_VAR, default=_MIN_OUTLINE_DEPTH_DEFAULT)
    return n


def pdf_outline_depth(src: Path) -> int:
    """Depth of the PDF's bookmark outline; 0 when absent or unreadable."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return 0
    try:
        doc = pdfium.PdfDocument(str(src))
    except Exception:
        return 0
    try:
        return max((bm.level + 1 for bm in doc.get_toc()), default=0)
    except Exception:
        return 0
    finally:
        with contextlib.suppress(Exception):
            doc.close()


def _is_outline_derived(
    src: Path | None,
    *,
    pdf_backend: str,
    heading_hierarchy: bool,
    min_outline_depth: int | None = None,
) -> bool:
    """Requires all of: docling, the heading-hierarchy option, a PDF source, and
    a bookmark outline at least `min_outline_depth` deep. Anything else —
    including docling falling back to numbering or style — is a guessed
    hierarchy the repair passes should still see."""
    if not heading_hierarchy or pdf_backend != "docling":
        return False
    if src is None or Path(src).suffix.lower() != ".pdf":
        return False
    return pdf_outline_depth(Path(src)) >= _min_outline_depth(min_outline_depth)


def record_hierarchy_source(
    out: Path | None,
    src: Path | None,
    *,
    pdf_backend: str,
    heading_hierarchy: bool,
) -> None:
    """Stamp the ingest's hierarchy provenance beside the checkpoints.

    A resume run (`--from <phase>` over an output dir) resolves its source to a
    checkpoint and re-stamps `.pagespeak-run.json` with bare defaults, so the
    run record cannot answer this question later. This marker is written once,
    at ingest, while the real source is still in hand.
    """
    if out is None:
        return
    if not _is_outline_derived(src, pdf_backend=pdf_backend, heading_hierarchy=heading_hierarchy):
        return
    depth = pdf_outline_depth(Path(src)) if src is not None else 0
    _merge_marker(out, source="outline", depth=depth)


def has_authoritative_hierarchy(
    src: Path | None,
    *,
    pdf_backend: str,
    heading_hierarchy: bool,
    out: Path | None = None,
    min_outline_depth: int | None = None,
    in_memory: bool = False,
) -> bool:
    """True when the heading levels were derived from the source's own outline.

    Prefers the ingest-time marker, which survives a resume run; falls back to
    inspecting `src` for a full-pipeline run that has no marker yet.

    `in_memory` carries the reader's claim for a `to_markdown(output_dir=None)`
    run, which writes no marker.
    """
    if in_memory:
        logger.info("hierarchy_authoritative via=in_memory")
        return True
    if _marker_is_trusted(out):
        logger.info("hierarchy_authoritative via=marker")
        return True
    trusted = _is_outline_derived(
        src,
        pdf_backend=pdf_backend,
        heading_hierarchy=heading_hierarchy,
        min_outline_depth=min_outline_depth,
    )
    if trusted:
        logger.info("hierarchy_authoritative via=source")
    return trusted


def _marker_data(out: Path | None) -> dict[str, object]:
    """The marker's parsed contents; `{}` when absent or unreadable."""
    if out is None:
        return {}
    path = out / MARKER_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_marker(out: Path, **fields: object) -> None:
    """Merge `fields` into the marker, preserving whatever is already there.

    Three writers share this file; each must keep the others' keys.
    """
    data = _marker_data(out)
    data.update(fields)
    try:
        atomic_write_json(out / MARKER_NAME, data)
    except OSError as e:
        logger.warning("hierarchy_marker_write_failed: %s", e)


def _marker_flag(out: Path | None, key: str) -> bool:
    return bool(_marker_data(out).get(key))


def ingested_from_outline(out: Path | None) -> bool:
    """True when `out`'s raw.md came from docling's `--heading-hierarchy` reading
    a bookmark outline; the marker is written at that ingest and nowhere else."""
    return _marker_data(out).get("source") == "outline"


def _marker_is_trusted(out: Path | None) -> bool:
    data = _marker_data(out)
    return data.get("source") == "outline" or any(bool(data.get(k)) for k in _TRUST_KEYS)


def record_outline_promoted(out: Path | None, *, promoted: bool) -> None:
    """Note that cleanup reconstructed this document's outline.

    Written to disk because `--from repair` is a separate invocation that
    cannot see cleanup's locals.
    """
    if out is None or not promoted:
        return
    _merge_marker(out, outline_promoted=True)


def outline_promoted(out: Path | None) -> bool:
    """True when cleanup reconstructed this document's outline."""
    return _marker_flag(out, "outline_promoted")


def record_structured(
    out: Path | None, *, authoritative: bool, authored_headings: bool = False
) -> None:
    """Record whether the backend read this document's structure from its format,
    and whether every heading is one the author wrote.

    Call only where the backend actually ran: this writes `False` too, so a
    re-ingest that switched backends clears the previous run's claim.
    """
    if out is None:
        return
    _merge_marker(out, structure_authoritative=authoritative, authored_headings=authored_headings)


def authored_headings(out: Path | None, *, in_memory: bool = False) -> bool:
    """True when every heading is the author's, from the marker or the in-memory claim."""
    return _marker_flag(out, "authored_headings") or in_memory


def structure_authoritative(out: Path | None) -> bool:
    """True when the backend read structure from the source format."""
    return _marker_flag(out, "structure_authoritative")


def trusted_structure(out: Path | None, *, in_memory: bool = False) -> bool:
    """`structure_authoritative`, from the marker or from the in-memory claim.

    The marker carries it across a separate `--from <phase>` invocation; the
    flag is the only carrier when there is no out dir to hold a marker.
    """
    return structure_authoritative(out) or in_memory


def hierarchy_is_trusted(
    src: Path | None,
    out: Path | None,
    *,
    pdf_backend: str,
    heading_hierarchy: bool,
    in_memory: bool = False,
) -> bool:
    """True when the heading levels came from the source, not from inference —
    the level-rewriting passes must then stand down."""
    return (
        outline_promoted(out)
        or trusted_structure(out, in_memory=in_memory)
        or has_authoritative_hierarchy(
            src, pdf_backend=pdf_backend, heading_hierarchy=heading_hierarchy, out=out
        )
    )
