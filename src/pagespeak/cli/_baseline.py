"""pagespeak baseline subcommand group — pf-core shim.

A thin binding over `pf_core.cli.subcommands.make_baseline_subcommand_group`:
binds pagespeak's `BaselineConfig` (which sets the `.pagespeak-run.json`
filename) and delegates command registration to the factory.
"""

from __future__ import annotations

import typer
from pf_core.cli.subcommands import make_baseline_subcommand_group

from ..services._baseline import PAGESPEAK_BASELINE_CONFIG


def register(app: typer.Typer) -> None:
    """Register the `baseline` subcommand group on `app`."""
    make_baseline_subcommand_group(app, config=PAGESPEAK_BASELINE_CONFIG)
