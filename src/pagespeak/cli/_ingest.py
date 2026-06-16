"""Typer subcommand registration for `pagespeak ingest`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import typer

from ..backends._docx_dispatch import DocxBackendName
from ..orchestrators._ingest import PartialIngestError, ingest


def register(
    app: typer.Typer,
    *,
    validate_pdf_backend: Callable[[str], str],
) -> None:
    """Hang the `ingest` subcommand off the given Typer app."""

    @app.command(
        name="ingest",
        help=(
            "Produce <stem>.raw.md + images/ for one document. Workers=1 is "
            "single-process; workers>1 chunks the PDF in parallel."
        ),
    )
    def ingest_cmd(
        input_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False),
        output_dir: Path = typer.Option(
            ..., "--output-dir", "-o", help="Where raw.md + images/ are written."
        ),
        workers: int = typer.Option(
            1,
            "--workers",
            "-w",
            help="1 = single-process; N > 1 = chunked-parallel (PDF-only).",
        ),
        pdf_backend: str = typer.Option(
            "marker",
            "--pdf-backend",
            callback=validate_pdf_backend,
            help="'marker' (default), 'docling', or 'tophat' (Top Hat quiz exports).",
        ),
        docx_backend: str = typer.Option(
            "markitdown",
            "--docx-backend",
            help=(
                "DOCX backend: 'markitdown' (default) | 'python-docx' "
                "(structure-faithful, requires pagespeak[docx-structured]). "
                "Ignored for non-.docx formats."
            ),
        ),
        docx_outline_heading_depth: int = typer.Option(
            0,
            "--docx-outline-heading-depth",
            help=(
                "python-docx backend only. The outline→heading switch. "
                "0 (default) = retain the WHOLE Word outline as a nested "
                "list (only the document title is '#'). N>0 overrides "
                "the top N outline levels into headings (1 = ilvl0 → '#')."
            ),
        ),
        chunk_pages: int = typer.Option(
            50,
            "--chunk-pages",
            help="Pages per chunk when workers > 1. Default 50.",
        ),
        device: str | None = typer.Option(
            None, "--device", help='Torch device override ("cpu" / "mps" / "cuda").'
        ),
        force_ocr: bool = typer.Option(False, "--force-ocr"),
        max_pages: int | None = typer.Option(
            None, "--max-pages", help="Limit to first N pages (for testing on slices)."
        ),
        force: bool = typer.Option(
            False, "--force", help="Discard manifest + chunks; re-ingest from scratch."
        ),
    ) -> None:
        kwargs: dict[str, Any] = {
            "output_dir": output_dir,
            "workers": workers,
            "pdf_backend": pdf_backend,
            "docx_backend": cast(DocxBackendName, docx_backend),
            "docx_outline_heading_depth": docx_outline_heading_depth,
            "chunk_pages": chunk_pages,
            "device": device,
            "force_ocr": force_ocr,
            "max_pages": max_pages,
            "force": force,
        }
        try:
            raw_md = ingest(input_path, **kwargs)
        except PartialIngestError as exc:
            # chunked ingest produced a partial output. raw.md
            # exists (with content from successful chunks only), manifest
            # records the failed ranges. Print a visible summary and exit
            # with code 2 (distinct from 1 = total failure).
            typer.echo(f"⚠  {exc}", err=True)
            typer.echo(f"   partial raw_md: {exc.raw_md_path}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(str(raw_md))
