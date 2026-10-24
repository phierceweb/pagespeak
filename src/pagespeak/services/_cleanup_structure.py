"""Structural cleanup passes: heading-slug + anchor-map building, page-ref
remapping, recurring-scaffold-heading demotion, and consecutive-heading dedup.
The TOC and front-matter demotes are `_cleanup_front_matter.py`.

These operate on whole-text heading structure (not per-line);
`cleanup_markdown` + `_cleanup_diagnose` drive them and `_cleanup`
re-exports them. Regex table lives in `_cleanup_regexes.py`.
This module does not call the per-line transforms — only the shared regexes —
so there is no cross-module cycle.
"""

from __future__ import annotations

import re

from ._cleanup_regexes import (
    HEADING_HASH_RE,
    HEADING_NUM_RE,
    PAGE_REF_RE,
    PAGE_SPAN_RE,
    SCAFFOLD_STUB_MAX_CONTENT_CHARS,
)
from ._fences import fence_flags


def heading_slug(line: str) -> str:
    """GitHub-flavored anchor slug for a heading line.

    Accepts `## Quick Start` or unpromoted `1.4. Triggers`. Strips leading
    hashes, page-spans, lowercases, replaces whitespace with hyphens, and
    drops everything that isn't `[a-z0-9-]`.

    `## Quick Start` -> `quick-start`
    `### 1.4.1. Foo Bar` -> `141-foo-bar`
    """
    stripped = PAGE_SPAN_RE.sub("", line.strip()).strip()
    text = re.sub(r"^#+\s*", "", stripped)
    text = text.lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _is_eventual_heading(line: str) -> bool:
    """True if this line will be a heading after cleanup (already `#`-prefixed
    or matches the numbered-heading pattern that promotion will fire on)."""
    stripped = PAGE_SPAN_RE.sub("", line.strip()).strip()
    if stripped.startswith("#"):
        return True
    return HEADING_NUM_RE.match(stripped) is not None


def build_anchor_map(text: str) -> dict[str, str]:
    """Scan raw text for `<span id="page-X-Y"></span>` targets and pair each
    with the slug of the next heading that follows.

    Anchors with no following heading are absent from the map; refs to them
    fall back to strip behavior at remap time.
    """
    anchor_map: dict[str, str] = {}
    pending: list[str] = []
    for line in text.splitlines():
        for m in PAGE_SPAN_RE.finditer(line):
            pending.append(m.group(1))
        if pending and _is_eventual_heading(line):
            slug = heading_slug(line)
            if slug:
                for anchor in pending:
                    anchor_map[anchor] = slug
                pending.clear()
    return anchor_map


def remap_page_refs(text: str, anchor_map: dict[str, str]) -> str:
    """Rewrite `[label](#page-X-Y)` to `[label](#<slug>)` using `anchor_map`.

    Refs whose anchor isn't in the map fall back to `label` (strip behavior),
    so no broken anchors are left behind.
    """

    def _replace(m: re.Match[str]) -> str:
        label, anchor = m.group(1), m.group(2)
        slug = anchor_map.get(anchor)
        if slug:
            return f"[{label}](#{slug})"
        return label

    return PAGE_REF_RE.sub(_replace, text)


def _dedupe_heading_lines(lines: list[str]) -> list[str]:
    """List-in, list-out internal helper. See `dedupe_consecutive_headings`."""
    out: list[str] = []
    last_heading: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped == last_heading:
                # Drop trailing blank lines we just appended so the dedupe
                # doesn't leave an extra blank where the second heading was.
                while out and out[-1].strip() == "":
                    out.pop()
                continue
            last_heading = stripped
            out.append(line)
        else:
            if stripped:
                last_heading = None
            out.append(line)
    return out


def demote_recurring_scaffold_headings(text: str) -> tuple[str, int]:
    """Demote heading-text occurrences that are an empty recurring
    scaffold echo rather than a real section.

    Detects heading text that appears 3+ times in the document, then
    classifies each occurrence's body as a **stub** (less than roughly
    one sentence of content — an empty scaffold echo) or
    **substantive** (a real section). The decision routes purely on the
    *count* of substantive occurrences — a document-relative signal,
    with no absolute paragraph-size threshold and no outlier ratio:

    1. **0 substantive** — every occurrence is an empty echo (e.g. a
       sidebar title like ``## In This Chapter`` repeated per chapter
       with no real underlying section). Demote ALL occurrences.

    2. **Exactly 1 substantive** — one occurrence is the real section,
       the others are stub copies (Outline / Chapter Summary /
       page-footer text mirroring the real heading). Keep the
       substantive one, demote the rest.

    3. **2+ substantive** — per-instance recurring real sections, each
       carrying its own distinct content under a different parent
       (e.g. a ``### Specifications`` heading repeated per item with
       different data each time). Keep ALL — this is not scaffold.

    "Body content size" = the count of NON-whitespace characters
    between this heading and the next (any depth). Whitespace-,
    indent-, and blank-line-insensitive, so a stub padded with blank
    lines is still a stub. ``SCAFFOLD_STUB_MAX_CONTENT_CHARS`` is the
    universal empty-section floor (see its definition above).

    Returns ``(rewritten_text, demoted_count)``.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)
    # Pass 1: collect heading-line records.
    headings: list[tuple[int, str]] = []  # (line_index, heading_text)
    for i, line in enumerate(lines):
        m = None if _fenced[i] else HEADING_HASH_RE.match(line.strip())
        if m:
            _, content = m.groups()
            headings.append((i, content.strip()))

    if len(headings) < 3:
        return text, 0

    # Per-occurrence body content size = non-whitespace char count
    # between this heading and the next. Whitespace/blank-line
    # insensitive so an echo padded with blank lines is still a stub.
    body_content: dict[int, int] = {}
    for k, (idx, _) in enumerate(headings):
        next_idx = headings[k + 1][0] if k + 1 < len(headings) else len(lines)
        body = "".join(lines[idx + 1 : next_idx])
        body_content[idx] = len("".join(body.split()))

    # Group occurrences by heading text.
    by_text: dict[str, list[int]] = {}
    for idx, txt in headings:
        by_text.setdefault(txt, []).append(idx)

    demoted_indices: set[int] = set()
    for _txt, indices in by_text.items():
        if len(indices) < 3:
            continue
        # Substantive = a real section; stub = an empty scaffold echo.
        substantive = [i for i in indices if body_content[i] > SCAFFOLD_STUB_MAX_CONTENT_CHARS]
        if len(substantive) == 0:
            # All empty echoes — pure scaffold; demote every occurrence.
            demoted_indices.update(indices)
        elif len(substantive) == 1:
            # One real section + stub copies. Keep it, demote the rest.
            keep_idx = substantive[0]
            for i in indices:
                if i != keep_idx:
                    demoted_indices.add(i)
        # 2+ substantive: per-instance recurring real sections — keep
        # all; demote nothing.

    if not demoted_indices:
        return text, 0

    out: list[str] = []
    for i, line in enumerate(lines):
        if i not in demoted_indices:
            out.append(line)
            continue
        m = re.match(r"^(\s*)#+\s+(.*)$", line)
        if m:
            out.append(f"{m.group(1)}{m.group(2)}")
        else:
            out.append(line)

    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, len(demoted_indices)


def dedupe_consecutive_headings(text: str) -> str:
    """Collapse runs of identical heading lines, including across blank lines.

    `## Foo\\n## Foo` -> `## Foo`.
    `## Foo\\n\\n## Foo` -> `## Foo` (blank line between still counts).
    `## Foo\\nbody\\n## Foo` -> kept as two (interrupted by content).

    Marker sometimes emits a heading like `## Table of Contents` twice in a row;
    this collapses that pattern. Runs after all per-line transforms so headings
    are compared post-normalization.
    """
    result = "\n".join(_dedupe_heading_lines(text.splitlines()))
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result
