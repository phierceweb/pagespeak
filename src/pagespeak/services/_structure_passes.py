"""Holistic doc-level heading passes for the structure phase.

$0 passes over the whole heading distribution, which no per-line cleanup pass
can reach: flat-source exports publish every article as a sibling `# `.
"""

from __future__ import annotations

from pf_core.log import get_logger

from ._enumerated_nest import nest_enumerated_item_runs
from ._flat_source_demote import demote_flat_h1_runs
from ._h1_ratio_rebalance import rebalance_orphan_h1s

logger = get_logger(__name__)


def apply_structure_passes(markdown: str, *, trusted: bool) -> str:
    """Nest enumerated-item runs, then re-level flat H1 runs unless `trusted`.

    Nesting runs FIRST, while original H1 boundaries are intact — after
    flat-demote a run could over-extend, and it keeps nested items out of the
    orphan-H1 count. The two level passes read a flat run as over-promotion,
    which is wrong on a hierarchy the source itself stated.
    """
    markdown = nest_enumerated_item_runs(markdown)
    if trusted:
        logger.info("structure_level_passes_skipped reason=authoritative_hierarchy")
        return markdown
    markdown = demote_flat_h1_runs(markdown)
    return rebalance_orphan_h1s(markdown)
