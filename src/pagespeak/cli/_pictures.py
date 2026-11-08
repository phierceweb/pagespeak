"""Typer subcommand registration for `pagespeak pictures`."""

from __future__ import annotations

from pathlib import Path

import typer
from pw_foundation.exceptions import InvalidInputError

from ..services._pictures import picture_report, render_report
from ..services._pictures_sheet import write_sheet
from ..services._verify_doc import find_documents
from ._verify import from_shell


def register(app: typer.Typer) -> None:
    """Hang the `pictures` subcommand off the given Typer app."""

    @app.command(
        name="pictures",
        help=(
            "Settle a converted document's pictures before paying for captions. Lists the "
            "pictures in the text, how many already have a cached caption, and each one "
            "whose label says nothing about it (fix the label, then caption once); runs "
            "verify's picture checks against the source PDF (ink no picture holds, a crop "
            "that cuts, printed titles with no picture); writes a contact sheet of every "
            "picture to .pagespeak-pictures.html beside the master. Read-only apart from "
            "the sheet, $0, no LLM calls; never fails a document."
        ),
    )
    def pictures_cmd(
        paths: list[Path] = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Converted output dirs: a document, or an export holding several.",
        ),
        in_dir: Path | None = typer.Option(
            None,
            "--in-dir",
            help=(
                "Where to look for each document's source PDF. Default: the `in` folder "
                "beside the document's `out` folder, else conversions/in."
            ),
        ),
    ) -> None:
        try:
            found = [d for p in paths for d in find_documents(from_shell(p))]
        except InvalidInputError as exc:
            raise typer.BadParameter(str(exc)) from exc
        docs = list({d.root.resolve(): d for d in found}.values())
        if not docs:
            raise typer.BadParameter("no converted document (a folder with a master .md) found")
        for doc in docs:
            report = picture_report(doc, in_dir=in_dir)
            typer.echo(render_report(report, write_sheet(report)))
