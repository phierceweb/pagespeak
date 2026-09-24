"""Typer subcommand registration for `pagespeak ingest`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import typer

from ..backends._docx_dispatch import DocxBackendName
from ..orchestrators._chunk import resolve_cli_workers
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
        workers: int | None = typer.Option(
            None,
            "--workers",
            "-w",
            help="1 = single-process; N > 1 = chunked-parallel (PDF-only). "
            "Default 1, or PAGESPEAK_WORKERS when set.",
        ),
        pdf_backend: str = typer.Option(
            "marker",
            "--pdf-backend",
            callback=validate_pdf_backend,
            help="'marker' (default), 'docling', or 'tophat' (Top Hat quiz exports).",
        ),
        heading_hierarchy: bool = typer.Option(
            False,
            "--heading-hierarchy/--no-heading-hierarchy",
            help="Docling PDF only. Infer heading levels from PDF bookmarks / section numbering / font style instead of Docling's flat default. Requires docling>=2.109.",
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
        chunk_pages: int | None = typer.Option(
            None,
            "--chunk-pages",
            help="Pages per chunk when workers > 1. Default 50, or PAGESPEAK_CHUNK_PAGES when set.",
        ),
        device: str | None = typer.Option(
            None, "--device", help='Torch device override ("cpu" / "mps" / "cuda").'
        ),
        force_ocr: bool = typer.Option(False, "--force-ocr"),
        max_pages: int | None = typer.Option(
            None,
            "--max-pages",
            help="PDF only: convert just the first N pages, as a trial on a slice. "
            "Not with --pdf-backend tophat.",
        ),
        force: bool = typer.Option(
            False, "--force", help="Discard manifest + chunks; re-ingest from scratch."
        ),
    ) -> None:
        try:
            kwargs: dict[str, Any] = {
                "output_dir": output_dir,
                "workers": resolve_cli_workers(
                    workers,
                    input_path,
                    # The tophat backend reads the whole export in one pass and
                    # ignores page_range, so chunking it duplicates every question.
                    chunk_unsafe=pdf_backend == "tophat",
                ),
                "pdf_backend": pdf_backend,
                "heading_hierarchy": heading_hierarchy,
                "docx_backend": cast(DocxBackendName, docx_backend),
                "docx_outline_heading_depth": docx_outline_heading_depth,
                "chunk_pages": chunk_pages,
                "device": device,
                "force_ocr": force_ocr,
                "max_pages": max_pages,
                "force": force,
            }
            raw_md = ingest(input_path, **kwargs)
        except PartialIngestError as exc:
            # chunked ingest produced a partial output. raw.md
            # exists (with content from successful chunks only), manifest
            # records the failed ranges. Print a visible summary and exit
            # with code 2 (distinct from 1 = total failure).
            typer.echo(f"⚠  {exc}", err=True)
            typer.echo(f"   partial raw_md: {exc.raw_md_path}", err=True)
            raise typer.Exit(code=2) from exc
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(str(raw_md))
