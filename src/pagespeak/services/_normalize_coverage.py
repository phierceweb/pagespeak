"""Coverage check for LLM heading-level responses.

A heading with no entry would keep its extracted level, so applying a short
reply re-levels part of the tree and leaves the rest as extracted.
"""

from __future__ import annotations

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

logger = get_logger(__name__)

MIN_COVERAGE_PCT_DEFAULT = 90
MIN_COVERAGE_PCT_ENV_VAR = "PAGESPEAK_NORMALIZE_MIN_COVERAGE_PCT"


def min_coverage_pct() -> int:
    n: int = resolve_int(None, MIN_COVERAGE_PCT_ENV_VAR, default=MIN_COVERAGE_PCT_DEFAULT)
    return n


def is_low_coverage(covered: int, target: int, *, mode: str, cached: bool = False) -> bool:
    """True (and a warning) when a response answers too few headings to apply.

    The response stays cached either way, so later runs replay it rather than
    re-send the payload; `cached` says this run is such a replay.
    Not for `llm_dehead`, whose absent verdicts mean KEEP.
    """
    if target <= 0:
        return False
    pct = 100.0 * covered / target
    if pct >= min_coverage_pct():
        return False
    logger.warning(
        "heading_normalize_low_coverage mode=%s covered=%d target=%d pct=%.1f source=%s "
        "— response not applied; every heading keeps its extracted level. The response "
        "is cached: --rerun-from normalize asks the model again",
        mode,
        covered,
        target,
        pct,
        "cache" if cached else "llm",
    )
    return True
