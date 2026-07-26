"""Docling heading-hierarchy inference: option construction + level fixups.

Docling's PDF pipeline labels every section header at the same level unless
`HeadingHierarchyOptions.enabled` is set, which infers levels from PDF
bookmarks, then section numbering, then font style (in that precedence).

Two Docling behaviours have to be corrected on our side:

1. `export_to_markdown()` renders `SectionHeaderItem.level=N` as **N+1** hash
   marks, so `max_level=6` can emit seven — past CommonMark's six-hash limit,
   which means no parser (ours included) reads them as headings at all.
2. A single `#` is reserved for `TitleItem`. A PDF that yields no title comes
   back with its whole tree starting at `##`, leaving every H1-keyed pass
   downstream with nothing to act on.

The fixups compose: promotion (2) runs first, and in the usual no-title case
it pulls a level-6 heading's seven hashes back to six — all six tiers
survive. The overflow clamp only fires when a title exists and blocks the
shift.
"""

from __future__ import annotations

import re
from typing import Any

from pf_core.log import get_logger

from ..services._fences import fence_flags

logger = get_logger(__name__)

HEADING_MAX_LEVEL = 6

_HEADING_RE = re.compile(r"^(#+)(\s+\S.*)$")


def enable_heading_hierarchy(opts: Any) -> None:
    """Turn on Docling's heading-level inference at full depth.

    No-ops with a WARNING on a Docling too old to carry the option
    (the field landed in 2.109.0 with the bookmark signal)."""
    if not hasattr(opts, "heading_hierarchy_options"):
        logger.warning(
            "docling_heading_hierarchy_unavailable "
            "installed docling has no heading_hierarchy_options; "
            "upgrade to docling>=2.109 — continuing with flat heading levels"
        )
        return
    from docling.datamodel.pipeline_options import HeadingHierarchyOptions

    opts.heading_hierarchy_options = HeadingHierarchyOptions(
        enabled=True,
        max_level=HEADING_MAX_LEVEL,
    )
    # The font-style fallback reads `page.parsed_page`, which the pipeline
    # discards unless this is set — without it `use_style` silently finds
    # nothing and only bookmarks + numbering contribute.
    opts.generate_parsed_pages = True


def coerce_option_value(current: Any, value: Any) -> Any:
    """Rebuild a nested pipeline-option model from a plain dict.

    Docling's options are pydantic models without `validate_assignment`, so a
    dict assigned to one is stored verbatim and only fails later, deep inside
    the conversion, as `AttributeError: 'dict' object has no attribute ...`.
    """
    if not isinstance(value, dict) or not hasattr(type(current), "model_fields"):
        return value
    try:
        return type(current)(**value)
    except (TypeError, ValueError) as e:
        logger.warning(
            "docling_option_coercion_failed type=%s error=%s — passing through",
            type(current).__name__,
            e,
        )
        return value


def promote_headings_without_h1(markdown: str) -> str:
    """Shift every heading up one level when the document has no H1.

    Returns the input unchanged when an H1 is already present (Docling
    emitted a title) or when there are no headings at all. Fenced code is
    skipped so a `#` comment is neither counted nor rewritten.
    """
    lines = markdown.split("\n")
    fenced = fence_flags(lines)
    headings: list[int] = []
    for idx, line in enumerate(lines):
        if fenced[idx]:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        if len(match.group(1)) == 1:
            return markdown
        headings.append(idx)

    for idx in headings:
        match = _HEADING_RE.match(lines[idx])
        if match:  # always true; re-matched to get the groups
            lines[idx] = match.group(1)[1:] + match.group(2)
    return "\n".join(lines)


def clamp_heading_overflow(markdown: str) -> str:
    """Rewrite headings deeper than six hashes down to six.

    Only reachable when the document has a title (promotion couldn't shift)
    and Docling assigned level 6, which renders as seven hashes. Fenced code
    is skipped."""
    lines = markdown.split("\n")
    fenced = fence_flags(lines)
    for idx, line in enumerate(lines):
        if fenced[idx]:
            continue
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) > 6:
            lines[idx] = "######" + match.group(2)
    return "\n".join(lines)


__all__ = [
    "HEADING_MAX_LEVEL",
    "clamp_heading_overflow",
    "coerce_option_value",
    "enable_heading_hierarchy",
    "promote_headings_without_h1",
]
