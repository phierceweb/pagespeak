"""Typer subcommand registration for `pagespeak deliver`."""

from __future__ import annotations

from pathlib import Path

import typer
from pw_foundation.exceptions import PreconditionError

from ..services._deliver import deliver


def _default_dest(source: Path) -> Path:
    """Infer the delivery dir by mirroring `…/out/<rest>` → `…/delivery/<rest>`.

    Requires an `out` segment in the path (the `conversions/out/` layout);
    otherwise the caller must pass `-o/--output-dir`."""
    parts = source.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "out":
            return Path(*parts[:i], "delivery", *parts[i + 1 :])
    raise typer.BadParameter(
        "could not infer a delivery dir (no 'out' folder in the path); "
        "pass -o/--output-dir explicitly"
    )


def register(app: typer.Typer) -> None:
    """Hang the `deliver` subcommand off the given Typer app."""

    @app.command(
        name="deliver",
        help=(
            "Strip a converted output dir for handoff: copy only the master "
            ".md, sections/, and images/ into a parallel delivery dir, dropping "
            "stage checkpoints, run records, and caches. Re-runnable — the "
            "destination is rebuilt to match the source. Defaults to mirroring "
            "conversions/out/<name> → conversions/delivery/<name>. Refuses while "
            "any document fails `pagespeak verify` (it runs verify first, or "
            "reuses the last verdict of an unchanged document)."
        ),
    )
    def deliver_cmd(
        source: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="A converted output dir (a whole export or a single document).",
        ),
        output_dir: Path | None = typer.Option(
            None,
            "--output-dir",
            "-o",
            help="Delivery destination. Default: the 'out' segment swapped to 'delivery'.",
        ),
        in_dir: Path | None = typer.Option(
            None,
            "--in-dir",
            help=(
                "Where verify looks for each document's source PDF. Default: the `in` "
                "folder beside the document's `out` folder, else conversions/in."
            ),
        ),
    ) -> None:
        dest = output_dir or _default_dest(source)
        try:
            result = deliver(source, dest, in_dir=in_dir)
        except PreconditionError as refused:
            typer.echo(str(refused), err=True)
            raise typer.Exit(code=1) from refused
        if result.documents == 0:
            typer.echo(f"no delivery-ready documents found under {source}", err=True)
            raise typer.Exit(code=1)
        typer.echo(
            f"delivered {result.documents} document(s), {result.files} file(s) → {result.dest}"
        )
