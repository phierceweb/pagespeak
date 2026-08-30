"""What `pagespeak convert` prints after a run."""

from __future__ import annotations

from pathlib import Path

import typer

from ..backends._qti import is_qti_export
from ..models._models import IngestResult
from ..orchestrators._dispatch import resolve_dir_mode_stem


def _document_stem(input_path: Path) -> str:
    # A directory input's stem comes from the raw.md inside it, not the
    # directory name; a QTI export dir has no raw.md, so it uses its own name.
    if input_path.is_dir() and not is_qti_export(input_path):
        return resolve_dir_mode_stem(input_path)
    return input_path.stem


def report_result(
    *,
    input_path: Path,
    output_dir: Path,
    result: IngestResult,
    stop_after: str | None,
) -> None:
    """Echo what the run wrote."""
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_stem = _document_stem(input_path)

    # An early --stop-after leaves result.markdown as an intermediate
    # checkpoint; the final <stem>.md is only written on completed runs
    # (the guard lives in to_markdown, which owns the write).
    if stop_after not in (None, "vision", "split"):
        typer.echo(
            f"stopped after '{stop_after}'; wrote the {stop_after} checkpoint "
            f"(final {doc_stem}.md left intact)"
        )
        return

    # QTI: per-quiz files were written flat at the output root (the
    # one independent document directory per exam) — report those instead
    # of writing a single <stem>.md.
    if is_qti_export(input_path):
        exam_dirs = sorted(d for d in output_dir.iterdir() if d.is_dir())
        typer.echo(f"wrote {len(exam_dirs)} quiz document(s) under {output_dir}/")
        typer.echo(f"  format       : {result.source_format}")
        typer.echo(f"  images       : {len(result.images)}")
        typer.echo(f"  diagrams     : {sum(1 for d in result.diagrams if d.mermaid)}")
        return

    # to_markdown() wrote the master; report it.
    md_path = output_dir / f"{doc_stem}.md"
    typer.echo(f"wrote {md_path}")
    typer.echo(f"  format       : {result.source_format}")
    typer.echo(f"  images       : {len(result.images)}")
    typer.echo(f"  diagrams     : {sum(1 for d in result.diagrams if d.mermaid)}")
    typer.echo(f"  non-diagrams : {sum(1 for d in result.diagrams if not d.mermaid)}")
    # The actual `split_sections` choice may have come from a preset
    # — `(output_dir / 'sections').is_dir()` is the source of truth.
    sections_dir = output_dir / "sections"
    if sections_dir.is_dir():
        typer.echo(f"  sections     : {sections_dir}")
