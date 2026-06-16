"""Cleanup-phase pass: demote runs of consecutive H1s with no intervening
sub-heading.

Catches flat-source documents that publish every article as a top-level
`# Title` — hundreds of sibling H1s with no real chapter above them, which
body-context normalize can't recover into a hierarchy. The structural signal
is a run of consecutive H1s with no H2-H6 between them; a real chapter head is
normally followed by sub-structure.

Every H1 in a qualifying run is demoted EXCEPT the first (which survives as the
run's anchor); body text is untouched, and any non-H1 heading resets the run.
The run-length threshold is `PAGESPEAK_FLAT_H1_THRESHOLD` (default 5).
"""

from __future__ import annotations

import re

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

logger = get_logger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")

_FLAT_H1_THRESHOLD_DEFAULT = 5
_FLAT_H1_THRESHOLD_ENV_VAR = "PAGESPEAK_FLAT_H1_THRESHOLD"


def _flat_h1_threshold() -> int:
    """Read `PAGESPEAK_FLAT_H1_THRESHOLD` at call time; fall back to default.

    Uses pf-core's `resolve_int` so a malformed env value emits a structured
    `env_var_malformed` warning and falls back to the default instead of
    crashing.
    """
    n: int = resolve_int(None, _FLAT_H1_THRESHOLD_ENV_VAR, default=_FLAT_H1_THRESHOLD_DEFAULT)
    return n


def demote_flat_h1_runs(text: str, *, threshold: int | None = None) -> str:
    """Demote runs of ≥ `threshold` consecutive H1s with no intervening
    H2-H6 heading. Returns the rewritten text.

    Args:
        text: the markdown to process.
        threshold: kwarg override; if None, env then default. Minimum
            length of an H1 run that triggers demotion. The first H1 in
            each qualifying run is kept at H1; the rest are demoted to H2.

    Returns:
        text with the trailing H1s in each qualifying run rewritten to H2.
        If no qualifying run is found, returns the input unchanged.
    """
    n_threshold = threshold if threshold is not None else _flat_h1_threshold()

    lines = text.splitlines(keepends=True)

    # First pass: identify the line indexes that start each qualifying run.
    # A run is a contiguous sequence of H1 heading lines whose only
    # intervening lines are non-heading (body / blank / lists / etc.). Any
    # H2-H6 heading line resets the run.
    runs: list[list[int]] = []  # list of [line_indexes-of-H1-in-run]
    current: list[int] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m is None:
            continue
        level = len(m.group(1))
        if level == 1:
            current.append(i)
        else:
            # Any non-H1 heading ends the current run.
            if len(current) >= n_threshold:
                runs.append(current)
            current = []
    if len(current) >= n_threshold:
        runs.append(current)

    if not runs:
        return text

    # Demote the 2nd through Nth H1 in each qualifying run.
    rewritten = 0
    for run in runs:
        for idx in run[1:]:
            old = lines[idx]
            # Add one more `#` to the leading hash prefix. Match preserves
            # everything past the first `#` exactly.
            lines[idx] = "#" + old
            rewritten += 1

    logger.info(
        "flat_h1_demote runs=%d rewrites=%d threshold=%d",
        len(runs),
        rewritten,
        n_threshold,
    )
    return "".join(lines)
