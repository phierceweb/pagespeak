"""Structural cleanup passes: heading-slug + anchor-map building, page-ref
remapping, TOC-phantom-heading demotion, recurring-scaffold-heading demotion,
and consecutive-heading dedup.

These operate on whole-text heading structure (not per-line);
`cleanup_markdown` + `_cleanup_diagnose` drive them and `_cleanup`
re-exports them. Regex table lives in `_cleanup_regexes.py`.
This module does not call the per-line transforms — only the shared regexes —
so there is no cross-module cycle.
"""

from __future__ import annotations

import re

from ._cleanup_regexes import (
    _TOC_NUM_PREFIX_RE,
    HEADING_HASH_RE,
    HEADING_NUM_RE,
    PAGE_REF_RE,
    PAGE_SPAN_RE,
    SCAFFOLD_STUB_MAX_CONTENT_CHARS,
    TOC_PAGE_NUM_SUFFIX_RE,
)


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


def _toc_match_key(content: str) -> str:
    """Normalise a heading's text for TOC-twin comparison: drop the
    trailing page number, a leading section-number prefix, collapse
    whitespace, casefold. Empty result ⇒ no usable key."""
    core = TOC_PAGE_NUM_SUFFIX_RE.sub("", content).strip()
    core = _TOC_NUM_PREFIX_RE.sub("", core)
    return re.sub(r"\s+", " ", core).strip().casefold()


def demote_toc_phantom_headings(text: str) -> tuple[str, int]:
    """Demote TOC entries that Marker promoted to heading shape.

    Targets the dominant cause of duplicate `sections/<n>/<title>.md` files
    on textbook-style documents: the front-of-book TOC lists every chapter
    and sub-section with the printed page number appended
    (``## 1.1 Introduction to the Topic 2``), and Marker promotes those
    lines to actual headings because the source PDF styled them like
    headings. The splitter then writes one section file for the TOC
    entry's heading plus another for the real body heading, with the
    collision-dedup keeping both (`-2` filename suffix).

    Detection is a two-pass scan of all heading lines in ``text``:

    1. **Signal 1 — trailing page-number suffix.** A heading text ending
       in ``\\s+\\d{1,4}\\s*$``. The 4-digit cap excludes legit titles
       that happen to end in long numbers (years, version strings, ZIP
       codes).
    2. **Signal 2 — the title re-appears as a real heading later.** For
       each candidate, compute its match key (`_toc_match_key`: page-num
       suffix + leading section-number prefix stripped, whitespace
       collapsed, casefolded) and demote only if that key also belongs
       to a *clean* (page-num-free) heading elsewhere. Required to dodge
       signal-1 false positives — ``## Section 2020`` only demotes if a
       clean ``Section`` heading exists. The key is
       numbering-/case-insensitive so a TOC line ``Organization of the
       Body 32`` matches its real twin ``## 1.1 Organization of the
       Body`` — an exact-text compare misses every such pair where the
       body heading carries a number the TOC line omits, leaving many
       phantom headings (a common TOC-survival cause).

    On match, demote the heading: drop the ``#`` markers, preserve
    indentation and the rest of the line verbatim. Result is plain text
    that the splitter ignores and ``regenerate_toc`` ignores; the
    document's TOC info is preserved as prose.

    Returns ``(rewritten_text, demoted_count)`` for callers that want
    to log the count.

    This catches the common TOC shape ``<numeric prefix> <title> <page>``
    (no ``, p. NN`` marker), which the splitter's
    ``is_toc_phantom_heading`` detector alone does not.
    """
    lines = text.splitlines()

    # Pass 1: collect the match-keys of "clean" headings (no page-num
    # suffix) — the real-section twins a TOC phantom must match. The key
    # is numbering-prefix- and case-insensitive (`_toc_match_key`) so a
    # body heading `## 1.1 Organization of the Body` is recognised as
    # the twin of a TOC line `Organization of the Body 32` (an
    # exact-text compare misses every such pair — a common
    # TOC-survival cause).
    body_heading_keys: set[str] = set()
    for line in lines:
        stripped = line.strip()
        m = HEADING_HASH_RE.match(stripped)
        if not m:
            continue
        _, content = m.groups()
        # Skip candidates from the body set — we only want "clean" heading
        # texts as the match target.
        if TOC_PAGE_NUM_SUFFIX_RE.search(content):
            continue
        key = _toc_match_key(content)
        if key:
            body_heading_keys.add(key)

    # Pass 2: rewrite candidates whose normalized key matches a clean
    # body heading's key.
    demoted = 0
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = HEADING_HASH_RE.match(stripped)
        if not m:
            out.append(line)
            continue
        _, content = m.groups()
        if not TOC_PAGE_NUM_SUFFIX_RE.search(content):
            out.append(line)
            continue
        key = _toc_match_key(content)
        if not key or key not in body_heading_keys:
            out.append(line)
            continue
        # Demote: preserve the original line's leading indent and the
        # heading text content; drop the `#` markers entirely.
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f"{indent}{content}")
        demoted += 1

    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, demoted


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
    # Pass 1: collect heading-line records.
    headings: list[tuple[int, str]] = []  # (line_index, heading_text)
    for i, line in enumerate(lines):
        m = HEADING_HASH_RE.match(line.strip())
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


# Front-matter demote tuning. A book = several H1 chapters; the front
# matter (title page, copyright/credits, TOC) is always a minority of the
# document's headings.
_FRONT_MATTER_MIN_H1 = 3
_FRONT_MATTER_MAX_FRACTION = 0.30


def demote_front_matter_headings(text: str) -> tuple[str, int]:
    """Demote the headings that precede the first chapter of a book.

    A PDF textbook's title page, copyright / credits page, and table of
    contents all sit BEFORE the first chapter, and Marker promotes their
    lines (the book title, the author name, ``British Library
    Cataloguing-in-Publication Data``, each TOC entry) to ``##`` / ``###``
    headings — which the splitter then emits as junk sections.

    Purely structural, no phrase list: **the first ``#`` (H1) is the first
    chapter**, so every heading before it is front matter. Those are demoted
    to plain text (``#`` markers dropped, indent + text kept — nothing
    deleted, the title-page prose survives as body text).

    Guards keep it off non-books and off docs that merely open with a few
    sections:

    * the doc must have ``>= _FRONT_MATTER_MIN_H1`` H1 headings (a
      multi-chapter book — a manual with one or two H1s is exempt); AND
    * there must be headings before the first H1 (else nothing to do); AND
    * those pre-first-H1 headings must be a **minority** of all headings
      (``< _FRONT_MATTER_MAX_FRACTION``). If most of the document's headings
      precede the first H1, the body isn't H1-led and the front-matter
      assumption is wrong — no-op rather than gut the document.

    Returns ``(rewritten_text, demoted_count)``; a no-op (count 0) when any
    guard fails.
    """
    lines = text.splitlines()
    heading_idxs: list[int] = []
    h1_idxs: list[int] = []
    for i, line in enumerate(lines):
        m = HEADING_HASH_RE.match(line.strip())
        if not m:
            continue
        heading_idxs.append(i)
        if len(m.group(1)) == 1:
            h1_idxs.append(i)

    if len(h1_idxs) < _FRONT_MATTER_MIN_H1:
        return text, 0
    first_h1 = h1_idxs[0]
    pre = [i for i in heading_idxs if i < first_h1]
    if not pre:
        return text, 0
    if len(pre) >= len(heading_idxs) * _FRONT_MATTER_MAX_FRACTION:
        return text, 0

    out = list(lines)
    demoted = 0
    for i in pre:
        m = re.match(r"^(\s*)#{1,6}\s+(.*)$", lines[i])
        if m:
            out[i] = f"{m.group(1)}{m.group(2)}"
            demoted += 1
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, demoted


# TOC-outline demote tuning. A detailed table of contents lists each chapter
# heading above a run of `- N.N <title> <page>` section lines; a real chapter
# heading sits above prose. Two such lines is enough signal to call it a TOC.
_TOC_OUTLINE_LINE_RE = re.compile(r"^\s*-\s+\d+\.\d+[a-z]?\s+\S.*?\d{1,4}\s*$")
_TOC_OUTLINE_MIN_LINES = 2


def demote_toc_outline_headings(text: str) -> tuple[str, int]:
    """Demote a book's detailed-table-of-contents chapter headings.

    A PDF textbook's detailed Contents lists every chapter as a heading
    (``# Chapter 1``) sitting directly above that chapter's section
    breakdown — bulleted ``- 1.1 Introduction to the Topic 2`` lines carrying a
    section number and the printed page number. Marker promotes the chapter
    label to an H1, and the splitter then emits each TOC entry as a junk
    section. (``demote_toc_phantom_headings`` misses these: the label is a
    bare ``Chapter N`` with no page-number suffix and no clean twin.)

    Detection is purely structural and **body-driven**: a heading is a TOC
    entry when its body — the lines up to the next heading — holds
    ``>= _TOC_OUTLINE_MIN_LINES`` ``- N.N <title> <page>`` section lines. A
    real chapter heading sits above prose (zero such lines) and is never
    touched; that body signal is the safe discriminator, so the real
    ``# Chapter 1`` deeper in the book survives while its TOC twin is demoted.

    Gated to books (``>= _FRONT_MATTER_MIN_H1`` H1s) so a short manual's lone
    numbered list isn't mistaken for a TOC. Demotes to plain text (``#``
    markers dropped, indent + text kept). Returns
    ``(rewritten_text, demoted_count)``; a no-op (count 0) when clean.
    """
    lines = text.splitlines()
    heading_idxs: list[int] = []
    h1_count = 0
    for i, line in enumerate(lines):
        m = HEADING_HASH_RE.match(line.strip())
        if m:
            heading_idxs.append(i)
            if len(m.group(1)) == 1:
                h1_count += 1

    if h1_count < _FRONT_MATTER_MIN_H1:
        return text, 0

    demote: set[int] = set()
    for k, i in enumerate(heading_idxs):
        nxt = heading_idxs[k + 1] if k + 1 < len(heading_idxs) else len(lines)
        toc_lines = sum(1 for j in range(i + 1, nxt) if _TOC_OUTLINE_LINE_RE.match(lines[j]))
        if toc_lines >= _TOC_OUTLINE_MIN_LINES:
            demote.add(i)

    if not demote:
        return text, 0

    out = list(lines)
    for i in demote:
        m = re.match(r"^(\s*)#{1,6}\s+(.*)$", lines[i])
        if m:
            out[i] = f"{m.group(1)}{m.group(2)}"
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, len(demote)


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
