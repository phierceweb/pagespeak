"""Structure-phase pass: rebalance flat-source docs by demoting orphan H1s.

Sister pass to `_flat_source_demote`. Where that pass catches LONG pure runs
of consecutive H1s, this one catches the broader flat-publish pattern: every
article is published as `# Article title` with its own H2-H4 sub-structure
underneath. The articles are siblings, not chapters, but all sit at H1.

The discriminating signal vs. a healthy pyramid is **whether each H1 owns any
child heading (H2-H6) before the next H1**:

- Healthy / real section: `# Chapter N` introduces sub-headings — a
  `## Section`, or even just a `###` — before the next `#`. Orphan ratio ≈ low.
- Flat-source: many H1s are childless leaf articles (`# Title` + body, no
  sub-heading of any level before the next `#`). Orphan ratio ≈ high.

Keying on ANY child (not just an H2) is deliberate: a doc with an under-built
hierarchy — sections that skip H2 and go straight to H3 — still has real
structure and must NOT be flattened. Only a truly childless H1 is a leaf.

When the orphan ratio crosses the threshold (default 70% of all H1s), every
orphan H1 is demoted to H2. The first H1 (typically the document title) is
always kept at H1.
"""

from __future__ import annotations

import re

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

logger = get_logger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")

# Conservative default: only fire on STRONGLY flat docs. Some authored docs
# are flat by design (every H1 carries an intentional child), so the threshold
# is set high — catch machine-flattened publishes without touching them.
# Tune via `PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD` env var.
_ORPHAN_H1_RATIO_THRESHOLD_DEFAULT = 70  # percent
_ORPHAN_H1_RATIO_THRESHOLD_ENV_VAR = "PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD"


def _orphan_h1_ratio_threshold() -> int:
    """Read `PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD` at call time; fall back
    to default. Pf-core's `resolve_int` emits an `env_var_malformed`
    warning + uses default on a non-integer value.
    """
    n: int = resolve_int(
        None,
        _ORPHAN_H1_RATIO_THRESHOLD_ENV_VAR,
        default=_ORPHAN_H1_RATIO_THRESHOLD_DEFAULT,
    )
    return n


def rebalance_orphan_h1s(text: str, *, threshold_pct: int | None = None) -> str:
    """Demote orphan H1s when the orphan ratio crosses `threshold_pct`.

    Orphan H1 = an H1 with no child heading of any level (H2-H6)
    between it and the next H1 (or EOF) — a truly childless leaf. An H1
    that owns even an H3 child has real structure and is kept.
    The first H1 is always kept (the title slot).

    Args:
        text: post-repair markdown.
        threshold_pct: kwarg override. Percentage (0-100) of all H1s that
            must be orphans for the rebalance to fire. If None, reads
            env then default.

    Returns:
        text with orphan H1s rewritten to H2 if the threshold is met,
        else input unchanged.
    """
    pct = threshold_pct if threshold_pct is not None else _orphan_h1_ratio_threshold()

    lines = text.splitlines(keepends=True)

    # Linear scan: collect H1 line indexes, and for each H1 record
    # whether ANY child heading (H2-H6) appears before the next H1 (or
    # EOF). A section that owns even an H3 child has real hierarchy — it
    # is not a flat-publish leaf article, so it is not an orphan.
    h1_indexes: list[int] = []
    has_child: list[bool] = []
    seen_child_for_current = False
    current_h1_idx: int | None = None

    def _close_current() -> None:
        nonlocal current_h1_idx, seen_child_for_current
        if current_h1_idx is not None:
            h1_indexes.append(current_h1_idx)
            has_child.append(seen_child_for_current)
        current_h1_idx = None
        seen_child_for_current = False

    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m is None:
            continue
        level = len(m.group(1))
        if level == 1:
            _close_current()
            current_h1_idx = i
        elif level >= 2 and current_h1_idx is not None:
            seen_child_for_current = True
    _close_current()

    # Need at least 2 H1s to compute a meaningful ratio.
    if len(h1_indexes) < 2:
        return text

    # First H1 is always kept (title slot) — exclude from orphan check.
    orphans = sum(1 for child in has_child[1:] if not child)
    candidate_count = len(h1_indexes) - 1  # excluding the title
    orphan_pct = (orphans * 100) // candidate_count

    if orphan_pct < pct:
        return text

    # Rebalance: demote every orphan H1 (skipping the first H1).
    rewrites = 0
    for idx_in_list, h1_line_idx in enumerate(h1_indexes):
        if idx_in_list == 0:
            continue  # title slot — keep
        if has_child[idx_in_list]:
            continue  # owns a child heading — a real section, not a leaf
        # Demote: prepend one `#`.
        lines[h1_line_idx] = "#" + lines[h1_line_idx]
        rewrites += 1

    logger.info(
        "orphan_h1_rebalance demoted=%d total_h1=%d orphan_pct=%d threshold=%d",
        rewrites,
        len(h1_indexes),
        orphan_pct,
        pct,
    )
    return "".join(lines)
