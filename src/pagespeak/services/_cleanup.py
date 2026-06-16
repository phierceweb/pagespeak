"""Cleanup pipeline for normalizing raw backend markdown.

`cleanup_markdown(text, level)` orchestrates the passes.

Module layout: the per-line transforms live in `_cleanup_transforms.py`, the
whole-text structural passes in `_cleanup_structure.py`, and the shared regex
table in `_cleanup_regexes.py`. This module keeps the orchestrator + table
normalization + the `CleanupLevel` / `CrossRefs` types, and re-exports every
pass function so the public + test + `_cleanup_diagnose` surface is unchanged.
"""

from __future__ import annotations

import re
from typing import Literal

from pf_core.log import get_logger

from ._cleanup_regexes import (
    IMAGE_ONLY_RE,
    LEADING_WS_RE,
    LIST_ITEM_BODY_RE,
    PAGE_SPAN_RE,
    TABLE_DIVIDER_RE,
)
from ._cleanup_structure import (
    _dedupe_heading_lines,
)
from ._cleanup_structure import (
    build_anchor_map as build_anchor_map,
)
from ._cleanup_structure import (
    dedupe_consecutive_headings as dedupe_consecutive_headings,
)
from ._cleanup_structure import (
    demote_front_matter_headings as demote_front_matter_headings,
)
from ._cleanup_structure import (
    demote_recurring_scaffold_headings as demote_recurring_scaffold_headings,
)
from ._cleanup_structure import (
    demote_toc_outline_headings as demote_toc_outline_headings,
)
from ._cleanup_structure import (
    demote_toc_phantom_headings as demote_toc_phantom_headings,
)
from ._cleanup_structure import (
    heading_slug as heading_slug,
)
from ._cleanup_structure import (
    remap_page_refs as remap_page_refs,
)
from ._cleanup_transforms import (
    collapse_multi_space as collapse_multi_space,
)
from ._cleanup_transforms import (
    collapse_shattered_emphasis as collapse_shattered_emphasis,
)
from ._cleanup_transforms import (
    decode_html_entities as decode_html_entities,
)
from ._cleanup_transforms import (
    lock_numbered_section_depth as lock_numbered_section_depth,
)
from ._cleanup_transforms import (
    normalize_list_bullet as normalize_list_bullet,
)
from ._cleanup_transforms import (
    promote_numbered_heading as promote_numbered_heading,
)
from ._cleanup_transforms import (
    repair_broken_cross_ref as repair_broken_cross_ref,
)
from ._cleanup_transforms import (
    strip_emphasis_from_heading as strip_emphasis_from_heading,
)
from ._cleanup_transforms import (
    strip_garbage_chars as strip_garbage_chars,
)
from ._cleanup_transforms import (
    strip_html_inline_tags as strip_html_inline_tags,
)
from ._cleanup_transforms import (
    strip_marker_pollution as strip_marker_pollution,
)
from ._cleanup_transforms import (
    strip_page_refs as strip_page_refs,
)
from ._cleanup_transforms import (
    strip_page_spans as strip_page_spans,
)
from ._cleanup_transforms import (
    unescape_underscores as unescape_underscores,
)
from ._outline import promote_outline

logger = get_logger(__name__)

CleanupLevel = Literal["off", "basic", "aggressive"]
CrossRefs = Literal["keep", "strip", "remap"]


def is_image_only_line(line: str) -> bool:
    """A bare `![](path)` with empty alt text — treated as page decoration.

    Image refs with non-empty alt text (`![Caption](path)`) are content, not
    decoration, and are NOT dropped by aggressive cleanup. The diagram pass
    populates alt text from the vision-extracted caption, so anything still
    bare here had no useful caption.
    """
    return IMAGE_ONLY_RE.match(line.strip()) is not None


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _split_table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _join_table_cells(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _trim_trailing_empty(cells: list[str]) -> list[str]:
    while cells and cells[-1] == "":
        cells.pop()
    return cells


def normalize_table_block(block_lines: list[str]) -> list[str]:
    """Normalize a contiguous run of pipe-table lines.

    - Promote a single-cell first row + divider to a `**caption**` paragraph.
    - Pad / truncate rows to the table's max column count.
    - Insert `|---|` divider after the first row when missing.
    """
    if not block_lines:
        return block_lines

    work_lines = list(block_lines)
    rows = [_trim_trailing_empty(_split_table_cells(line)) for line in work_lines]

    caption: str | None = None
    if len(rows) >= 3:
        first_non_empty = [c for c in rows[0] if c]
        second_is_divider = TABLE_DIVIDER_RE.match(work_lines[1].strip()) is not None
        third_non_empty = [c for c in rows[2] if c]
        if len(first_non_empty) == 1 and second_is_divider and len(third_non_empty) > 1:
            caption = first_non_empty[0]
            rows = rows[2:]
            work_lines = work_lines[2:]

    non_divider_rows = [
        rows[i] for i, raw in enumerate(work_lines) if not TABLE_DIVIDER_RE.match(raw.strip())
    ]
    if not non_divider_rows:
        return work_lines

    target_cols = max(max(len(r) for r in non_divider_rows), 2)

    out: list[str] = []
    if caption:
        out.append(f"**{caption}**")
        out.append("")

    has_divider = any(TABLE_DIVIDER_RE.match(raw.strip()) for raw in work_lines)
    header_emitted = False
    for i, raw in enumerate(work_lines):
        if TABLE_DIVIDER_RE.match(raw.strip()):
            out.append(_join_table_cells(["---"] * target_cols))
            continue
        cells = _trim_trailing_empty(rows[i])
        if len(cells) < target_cols:
            cells = cells + [""] * (target_cols - len(cells))
        elif len(cells) > target_cols:
            cells = cells[:target_cols]
        out.append(_join_table_cells(cells))
        if not has_divider and not header_emitted:
            out.append(_join_table_cells(["---"] * target_cols))
            header_emitted = True

    return out


def _preserve_list_indent(original: str, normalized: str) -> str:
    """Re-apply ``original``'s leading indent to ``normalized`` when it
    is a list item.

    A nested list item's leading indentation encodes its nesting depth
    (structural). The per-line leading-whitespace strip would otherwise
    flatten every list to column 0 (the list-flatten regression). For a
    list item we keep the original indent; every
    non-list line passes through with ``normalized`` (leading/trailing
    whitespace stripped; internal spacing preserved verbatim —
    internal runs never break markdown).
    """
    m = LEADING_WS_RE.match(original)
    indent = m.group(0) if m else ""
    body = normalized.lstrip()
    if indent and LIST_ITEM_BODY_RE.match(body):
        return indent + body
    return normalized


def cleanup_markdown(
    text: str,
    level: CleanupLevel = "basic",
    *,
    cross_refs: CrossRefs = "keep",
) -> str:
    """Run the cleanup pipeline at the requested level.

    `off`        - return text unchanged (useful for debugging raw backend output).
                    `cross_refs` is ignored at this level.
    `basic`      - generic transformations safe across documents.
    `aggressive` - additionally drop image-only lines, drop TOC table rows,
                    strip page-anchor spans.

    `cross_refs="keep"` (default): leave `[label](#page-X-Y)` references intact.
    `cross_refs="strip"`: rewrite to plain `label`, dropping the broken anchor.
    Pair with `aggressive` to avoid orphan refs after page-span targets are
    stripped.
    """
    if level == "off":
        return text

    # Decode HTML entities the backend left in the markdown (`T3 &lt; 34F` →
    # `T3 < 34F`) so every downstream pass + the RAG sees the real char. Always
    # correct on extracted content; runs first so heading/outline detection and
    # the line loop see decoded text.
    text = decode_html_entities(text)

    # Collapse converter-debris emphasis pileups (`****word****` from Marker's
    # doubled bold or markdownify'd nested quiz-stem emphasis) to `**word**`.
    # Always-correct on extracted content; runs as a whole-text pass before the
    # per-line loop so the heading branch and the audit see repaired markers.
    text = collapse_shattered_emphasis(text)

    aggressive = level == "aggressive"

    # Outline-to-heading PRE-pass — runs BEFORE the per-line loop, which
    # `.strip()`s away the leading whitespace that encodes outline depth.
    # When it fires the doc is DOCX-shaped (no Marker), so `demote_prose_
    # heading` (built for Marker's false positives) would only hurt here,
    # demoting legitimate long-sentence-shaped section titles. Track the
    # outline-doc state so the heading branch can skip prose-demote.
    text, outline_promoted = promote_outline(text)
    is_outline_doc = outline_promoted > 0
    if outline_promoted:
        logger.info("cleanup_promoted_outline_to_headings count=%d", outline_promoted)

    anchor_map: dict[str, str] = {}
    if cross_refs == "remap":
        anchor_map = build_anchor_map(text)

    out: list[str] = []
    table_buf: list[str] = []
    blank_run = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if aggressive:
            if "Table of Contents" in line:
                # Normalize the heading but preserve any TOC table that follows.
                # stripped TOC table rows entirely, but on some real-world
                # docs that table is the only TOC the doc has — preserve it.
                out.append("## Table of Contents")
                blank_run = 0
                continue
            if is_image_only_line(line):
                continue

        line = strip_garbage_chars(line, aggressive=aggressive)
        if aggressive:
            line = strip_page_spans(line)
        line = strip_html_inline_tags(line)
        # Preserve the author's internal spacing — a run of spaces
        # mid-line (e.g. a space-laid pseudo-diagram `foo    bar`) never
        # breaks markdown, so it is kept verbatim. Only leading/trailing
        # whitespace is normalized: a leading run would mis-form an
        # indented code block (markdown-breaking) and a trailing run is
        # a stray hard break. `.strip()` handles both; structural list
        # indent is then re-applied by `_preserve_list_indent`.
        line = _preserve_list_indent(line, line.strip())
        line = repair_broken_cross_ref(line)
        if cross_refs == "strip":
            line = strip_page_refs(line)
        elif cross_refs == "remap":
            line = remap_page_refs(line, anchor_map)
        line = unescape_underscores(line)
        line = promote_numbered_heading(line)
        # Strip page-anchor spans from heading lines: Marker emits
        # `## <span id="page-X-Y"></span>Title` for many PDFs; left in place
        # the spans leak into split filenames + breadcrumbs. With
        # `cross_refs="keep"` (default) each stripped anchor is re-emitted on
        # the line after the heading so `[label](#page-X-Y)` refs still
        # resolve; aggressive mode strips them without restoring.
        preserved_anchors: list[str] = []
        if line.lstrip().startswith("#"):
            if not aggressive and cross_refs == "keep":
                preserved_anchors = [f'<span id="{m}"></span>' for m in PAGE_SPAN_RE.findall(line)]
            line = strip_page_spans(line).rstrip()
            # also strip the broader Marker-pollution patterns
            # that the simple `strip_page_spans` doesn't catch — broken-
            # markup span tags inside link brackets, `[label](#page-X-Y)`
            # cross-ref wrapping around the title text, and dangling
            # `](#page-X-Y)` orphan tails. Heading-line-only so body
            # cross-refs (which are legitimate navigation) stay intact.
            # The well-formed span anchors are already preserved into
            # `preserved_anchors` above for re-emit on the line below.
            hash_match = re.match(r"^(\s*#{1,6}\s+)(.*)$", line)
            if hash_match:
                prefix, body = hash_match.group(1), hash_match.group(2)
                line = prefix + strip_marker_pollution(body)
            # All heading-quality transforms (chapter-promote,
            # numbered-depth lock, emphasis-strip, prose-demote, the
            # scaffold/TOC/shell demotes) now live in the
            # `_cleanup_diagnose` detect→correct engine, applied
            # post-loop in the load-bearing promotes-before-demotes
            # order. This per-line heading branch only does the
            # anchor-preserving span / Marker-pollution strip above —
            # NOT heading-quality decisions ("brute down one path").
        line = normalize_list_bullet(line)
        # Internal spacing preserved; only a trailing run (stray hard
        # break) is normalized here (leading already handled above / by
        # list-bullet normalization).
        line = _preserve_list_indent(line, line.rstrip())

        if is_table_line(line):
            table_buf.append(line)
            # Table rows are non-blank content, so they break a blank run — same
            # as line 354 does for other non-blank lines. Without this reset, a
            # blank line *before* a table and the blank *after* it count as
            # consecutive (the rows between are skipped via `continue`), so the
            # trailing separator is dropped by the `blank_run <= 1` dedup and the
            # next table glues onto this one (the 2-col-then-wide-table wipe).
            blank_run = 0
            continue
        if table_buf:
            out.extend(normalize_table_block(table_buf))
            table_buf = []

        if not line:
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue

        blank_run = 0
        out.append(line)
        if preserved_anchors:
            out.extend(preserved_anchors)

    if table_buf:
        out.extend(normalize_table_block(table_buf))

    out = _dedupe_heading_lines(out)

    # Whole-text heading-demotion passes. Detect→correct: dispatched
    # through the ordered registry in `_cleanup_diagnose` instead of a
    # hard-coded sequence — each pass self-diagnoses and no-ops when
    # its pattern is absent. Lazy import breaks the import cycle
    # (`_cleanup_diagnose` reuses this module's pass functions).
    from ._cleanup_diagnose import apply_heading_demotions

    out_text = "\n".join(out)
    out_text, demote_counts = apply_heading_demotions(out_text, is_outline_doc=is_outline_doc)
    for event, n in demote_counts.items():
        if n:
            logger.info("%s count=%d", event, n)

    return out_text.strip() + "\n"
