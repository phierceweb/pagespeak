"""Typer subcommand registration for `pagespeak audit`."""

from __future__ import annotations

from pathlib import Path

import typer

from ..services._audit import audit_paths, is_document_dir, render_report
from ..services._staging import find_source_pdf


def _stem(md: Path) -> str:
    return md.name.removesuffix(".raw.md").removesuffix(".md")


def register(app: typer.Typer) -> None:
    """Hang the `audit` subcommand off the given Typer app."""

    @app.command(
        name="audit",
        help=(
            "Scan converted markdown output for known conversion defects "
            "(collapsed tables, HTML debris, encoding damage, undecoded "
            "entities, shattered emphasis, empty sections, dangling and "
            "unparseable image refs, duplicated junk headings, collapsed code "
            "blocks, formula glyph codes). --text-coverage also compares each "
            "document with its source PDF's text layer to catch body text that "
            "never arrived. Read-only, $0, no LLM calls. "
            "Audits final artifacts only (skips stage checkpoints and "
            "caches). Exits 1 if any errors are found; warnings alone "
            "exit 0. The report narrows where to read — it does not "
            "replace reading the output."
        ),
    )
    def audit_cmd(
        paths: list[Path] = typer.Argument(
            ...,
            exists=True,
            help="Converted output dirs (or single .md files) to scan.",
        ),
        summary_only: bool = typer.Option(
            False,
            "--summary-only",
            help="Print only the per-check totals, no per-file detail.",
        ),
        text_coverage: bool = typer.Option(
            False,
            "--text-coverage",
            help=(
                "Also check each converted document dir against its source PDF's text "
                "layer (the share of the PDF's distinct words that reached raw.md), "
                "naming the pages mostly missing. Needs pypdfium2."
            ),
        ),
        source: Path | None = typer.Option(
            None,
            "--source",
            exists=True,
            dir_okay=False,
            help="With --text-coverage: the source PDF, for a single document dir.",
        ),
        in_dir: Path = typer.Option(
            Path("conversions/in"),
            "--in-dir",
            help="With --text-coverage and no --source: where to auto-locate source PDFs.",
        ),
    ) -> None:
        if source is not None and not text_coverage:
            raise typer.BadParameter("--source is only used with --text-coverage")
        if source is not None and (len(paths) != 1 or not is_document_dir(paths[0])):
            raise typer.BadParameter(
                "--source names one PDF, so pass exactly one converted document folder "
                "(the one holding <stem>.raw.md or the master .md)"
            )
        source_for = None
        if text_coverage:

            def source_for(md: Path) -> Path | None:
                return source if source is not None else find_source_pdf(_stem(md), in_dir)

        try:
            report = audit_paths(paths, source_for=source_for)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        except ImportError as exc:
            typer.echo(
                f"--text-coverage reads the PDF text layer and needs pypdfium2 "
                f"(pip install 'pagespeak[tophat]'): {exc}",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        typer.echo(render_report(report, summary_only=summary_only))
        if report.error_count:
            raise typer.Exit(code=1)
