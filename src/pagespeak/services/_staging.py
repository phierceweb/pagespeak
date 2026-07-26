"""Resolve a staging entry to the file the pipeline should convert.

An entry in ``conversions/in`` is either a plain file or a *bundle* — a
directory holding one deliverable plus its sidecars (``manifest.json``,
``images/``, a kept crawl), which is how an upstream ingester stages a document
so its images stay beside it.

A bundle always resolves to the inner deliverable, never to the directory:
handing a directory to the pipeline triggers dir-mode, which requires the
output dir to equal the input dir and would write checkpoints into the source
tree.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pagespeak.backends._qti import is_qti_export
from pagespeak.orchestrators._ingest import (
    MARKDOWN_SUFFIXES,
    MARKITDOWN_SUFFIXES,
    PDF_SUFFIXES,
)

CONVERTIBLE_SUFFIXES: frozenset[str] = PDF_SUFFIXES | MARKITDOWN_SUFFIXES | MARKDOWN_SUFFIXES

# Convertible in their own right, but inside a bundle these are sidecars — an
# acquisition record or an image index — never the document.
_SIDECAR_SUFFIXES: frozenset[str] = frozenset({".json", ".xml", ".csv"})
_DOCUMENT_SUFFIXES: frozenset[str] = CONVERTIBLE_SUFFIXES - _SIDECAR_SUFFIXES

# A directory holding one of these is an output dir, not a source.
_CHECKPOINT_MARKER = "*.raw.md"


def _is_convertible(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in CONVERTIBLE_SUFFIXES


def resolve_staged(entry: Path) -> Path | None:
    """The file to convert for one staging entry, or None when undecidable.

    A plain convertible file resolves to itself. A bundle resolves to the
    deliverable named after the directory, falling back to the sole convertible
    file when the naming differs. Two candidates and no slug-named one is
    ambiguous, and guessing there would silently convert the wrong document.
    """
    try:
        if entry.is_file():
            return entry if _is_convertible(entry) else None
        if not entry.is_dir():
            return None
        # An out dir would otherwise resolve to its own checkpoint.
        if any(entry.glob(_CHECKPOINT_MARKER)):
            return None
        # A QTI export is converted as the directory itself, not as one file
        # inside it; resolving inward would convert a single question stem.
        if is_qti_export(entry):
            return None
        candidates = sorted(p for p in entry.iterdir() if _is_convertible(p))
    except OSError:
        return None
    # Naming the file after its directory is an explicit statement of which
    # file is the document, so it wins over any suffix judgement.
    for p in candidates:
        if p.stem == entry.name:
            return p
    docs = [p for p in candidates if p.suffix.lower() in _DOCUMENT_SUFFIXES]
    return docs[0] if len(docs) == 1 else None


def staged_sources(in_dir: Path) -> Iterator[Path]:
    """Every convertible source staged in ``in_dir``, bundles resolved inward."""
    try:
        entries = sorted(in_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith("."):
            continue
        resolved = resolve_staged(entry)
        if resolved is not None:
            yield resolved
