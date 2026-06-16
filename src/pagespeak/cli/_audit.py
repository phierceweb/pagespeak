"""Typer subcommand registration for `pagespeak audit`."""

from __future__ import annotations

from pathlib import Path

import typer

from ..services._audit import audit_paths, render_report


def register(app: typer.Typer) -> None:
    """Hang the `audit` subcommand off the given Typer app."""

    @app.command(
        name="audit",
        help=(
            "Scan converted markdown output for known conversion defects "
            "(collapsed tables, HTML debris, encoding damage, undecoded "
            "entities, shattered emphasis, empty sections, dangling image "
            "refs, duplicated junk headings). Read-only, $0, no LLM calls. "
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
    ) -> None:
        report = audit_paths(paths)
        typer.echo(render_report(report, summary_only=summary_only))
        if report.error_count:
            raise typer.Exit(code=1)
