"""Typer subcommand registration for `pagespeak verify`."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from pw_foundation.exceptions import InvalidInputError
from pw_foundation.utils.env import resolve_str

from ..services._verify import verify_paths
from ..services._verify_verdict import render_summary


def _from_shell(path: Path) -> Path:
    """A relative path made absolute from the shell's working folder ($PWD) when
    that names the real one, so a folder reached through a symlink keeps the
    `out` folder its source PDF and delivery are found beside."""
    pwd = resolve_str(None, "PWD", default="") or ""
    if path.is_absolute() or not os.path.isabs(pwd):
        return path
    try:
        same = os.path.samefile(pwd, os.curdir)
    except OSError:
        return path
    return Path(os.path.normpath(os.path.join(pwd, path))) if same else path


def register(app: typer.Typer) -> None:
    """Hang the `verify` subcommand off the given Typer app."""

    @app.command(
        name="verify",
        help=(
            "Check each converted document as a whole and write PASS or FAIL beside its "
            "master (.pagespeak-verdict.md): broken or unused picture links, pictures "
            "without a caption or sharing one, section files that lose or repeat part of "
            "the master, a delivered copy that differs from the build, plus notes on "
            "captions that doubt their label and on heading and table shape. With the "
            "source PDF: printed figure and table titles that never arrive, repeat, sit "
            "out of page order or have no picture, and bookmarks missing as headings. With "
            "a build's source map: every body line of five words or more, lines still "
            "joined, and ink no picture "
            "holds or a crop cuts, labels included. A finding read and accepted in "
            ".pagespeak-accepted.json no longer fails. `deliver` refuses a "
            "failing document. Read-only apart from the verdict files, $0, no LLM calls. "
            "Exits 1 if any document fails."
        ),
    )
    def verify_cmd(
        paths: list[Path] = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Converted output dirs: a document, or an export holding several.",
        ),
        delivery: bool = typer.Option(
            True,
            "--delivery/--no-delivery",
            help="Also compare each document with its copy under conversions/delivery/.",
        ),
        in_dir: Path | None = typer.Option(
            None,
            "--in-dir",
            help=(
                "Where to look for each document's source PDF, matched by its recorded name "
                "and SHA-256. Default: the `in` folder beside the document's `out` folder, "
                "else conversions/in."
            ),
        ),
    ) -> None:
        try:
            verdicts = verify_paths(
                [_from_shell(p) for p in paths], in_dir=in_dir, include_delivery=delivery
            )
        except InvalidInputError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(render_summary(verdicts))
        if any(not v.passed for v in verdicts):
            raise typer.Exit(code=1)
