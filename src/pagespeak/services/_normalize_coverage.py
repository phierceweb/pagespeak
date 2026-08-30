"""Coverage check for LLM heading-level responses.

A heading with no entry keeps its extracted level, so a short reply
under-applies silently.
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


def warn_on_low_coverage(covered: int, target: int, *, mode: str) -> None:
    """Not for `llm_dehead`, whose absent verdicts mean KEEP."""
    if target <= 0:
        return
    pct = 100.0 * covered / target
    if pct >= min_coverage_pct():
        return
    logger.warning(
        "heading_normalize_low_coverage mode=%s covered=%d target=%d pct=%.1f "
        "— un-covered headings keep their extracted level",
        mode,
        covered,
        target,
        pct,
    )
