"""Typer subcommand registration for `pagespeak vision-audit`."""

from __future__ import annotations

from pathlib import Path

import typer

from ..services._vision_audit import audit_vision, render_report


def register(app: typer.Typer) -> None:
    """Hang the `vision-audit` subcommand off the given Typer app."""

    @app.command(
        name="vision-audit",
        help=(
            "Flag likely-confabulated vision captions for human review. "
            "Deterministic, $0, no LLM. Compares each figure's generated "
            "caption against the author's source alt text; a caption that keeps "
            "NONE of the alt's subject words (a squirrel captioned as a lemur) "
            "is flagged. Only figures whose source alt names a clear subject are "
            "assessable; figures without alt are skipped. Exits 0 by default "
            "(candidates need a human eye); --strict exits 1 if any are flagged."
        ),
    )
    def vision_audit_cmd(
        paths: list[Path] = typer.Argument(
            ...,
            exists=True,
            help="Converted output dirs (each with a .vision-cache/) to scan.",
        ),
        summary_only: bool = typer.Option(
            False,
            "--summary-only",
            help="Print only the totals, no per-figure detail.",
        ),
        strict: bool = typer.Option(
            False,
            "--strict",
            help="Exit 1 if any captions are flagged (for a delivery / CI gate).",
        ),
    ) -> None:
        report = audit_vision(paths)
        typer.echo(render_report(report, summary_only=summary_only))
        if strict and report.finding_count:
            raise typer.Exit(code=1)
