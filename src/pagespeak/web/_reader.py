"""Re-read a converted PDF when the console asks for another reader.

The pipeline refuses a raw.md that another reader produced, and the form has no
re-ingest control, so a reader change becomes `--rerun-from ingest`.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.orchestrators._resume import recorded_ingest_flags
from pagespeak.web._jobs import ConversionOptions


class ReaderChangeRefused(Exception):
    """A reader change this run cannot carry out."""


def previous_reader(out_dir: Path, source: Path | None, pdf_backend: str | None) -> str | None:
    """The reader behind `out_dir`'s raw.md when `pdf_backend` would read `source`
    differently, else None. The console's docling always adds `--heading-hierarchy`."""
    if not pdf_backend or source is None or source.suffix.lower() != ".pdf":
        return None
    if not (out_dir / f"{source.stem}.raw.md").exists():
        return None
    recorded = recorded_ingest_flags(out_dir)
    reader = recorded.get("pdf_backend")
    if reader is not None and reader != pdf_backend:
        return str(reader)
    if pdf_backend == "docling" and recorded.get("heading_hierarchy") is False:
        return "docling without --heading-hierarchy"
    return None


def reread_on_reader_change(
    opts: ConversionOptions, *, out_dir: Path, source: Path | None, start: str | None
) -> tuple[ConversionOptions, bool]:
    """`opts` set to re-ingest when the chosen reader differs from the previous
    one, and whether it does (the image set is then unknown until ingest)."""
    if start not in (None, "ingest") or opts.rerun_from == "ingest":
        return opts, False
    reader = previous_reader(out_dir, source, opts.pdf_backend)
    if reader is None:
        return opts, False
    if opts.workers > 1:
        raise ReaderChangeRefused(
            f"This document was read with {reader}. Re-reading it with {opts.pdf_backend} "
            "needs workers set to 1: a multi-worker run reuses the pages already read."
        )
    return opts.model_copy(update={"rerun_from": "ingest"}), True
