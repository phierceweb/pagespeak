"""pagespeak invalidate subcommand — pf-core shim.

A thin binding over `pf_core.cli.subcommands.make_invalidate_subcommand`:
binds pagespeak's stage registry + run-record filename and delegates
command registration to the factory.
"""

from __future__ import annotations

import typer
from pf_core.cli.subcommands import make_invalidate_subcommand

from ..services._rerun import PAGESPEAK_REGISTRY


def register(app: typer.Typer) -> None:
    """Register the `invalidate` subcommand on `app`."""
    make_invalidate_subcommand(
        app,
        registry=PAGESPEAK_REGISTRY,
        run_record_filename=".pagespeak-run.json",
    )
