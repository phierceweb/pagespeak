"""Markdown → `_Section` tree parsing for the splitter.

The heading parsers (`_parse_numbered_heading` / `_parse_any_heading` /
`_parse_chapter_heading`), the `_Section` / `_Collision` data types, parent
attribution (`_find_parent`), section parsing (`_parse_sections`), and the
numbered-vs-fallback min-level detection. `_split` re-exports `_Section`,
`_parse_numbered_heading`, and `_detect_fallback_min_level`.
Self-contained — the write/filter modules and the orchestrator import
from here, never the reverse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NUMBERED_HEADING_RE = re.compile(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$")

MEASUREMENT_HEADING_RE = re.compile(r"^#{1,6}\s+\d+(?:\.\d+)?\s+[a-z]")

ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+?)$")

CHAPTER_TITLE_RE = re.compile(r"^Chapter\s+(\d+)(?:[\s.:]+(.+))?$", re.IGNORECASE)

_PAGE_ANCHOR_LINE_RE = re.compile(r'^<span id="page-\d+-\d+"></span>\s*$')

FALLBACK_SPARSE_GROUP_MAX = 2

FALLBACK_SPARSE_GROUP_RATIO = 3


def _parse_chapter_heading(body: str) -> tuple[str, str] | None:
    """Match `Chapter N <title>` style headings. Returns `(number, title)`
    where `title` is the part after `Chapter N` (the `display_name`
    property prefixes the number on its own — keeping `Chapter N` in the
    title would render as `1. Chapter 1 Introduction…` (redundant)).

    Falls back to `Chapter N` literal when there's nothing after the
    number, to keep the title non-empty.
    """
    m = CHAPTER_TITLE_RE.match(body.strip())
    if not m:
        return None
    number = m.group(1)
    rest = (m.group(2) or "").strip()
    title = rest if rest else f"Chapter {number}"
    return number, title


def _parse_numbered_heading(line: str) -> tuple[str, str, str] | None:
    """Return `(hashes, number, title)` if this line is a numbered section heading.

    Heuristic: at heading level 2, require a `.` in the number. `## 1 Step`
    looks like a procedure step inside a section, not a real `## 1.4. TITLE`.

    Also recognizes `Chapter N <title>` patterns — Marker often emits
    chapter headings without a leading digit (e.g.
    `#### Chapter 1 <Title>`), and we want them available as numbered
    ancestors.
    """
    m = NUMBERED_HEADING_RE.match(line)
    if m:
        hashes, number, title = m.groups()
        if len(hashes) == 2 and "." not in number:
            return None
        # reject `<number> <lowercase unit>` measurement
        # shapes (`35 mm`, `6.3 mm`, `50 ohm`) — the number is a
        # quantity, not a section prefix.
        if MEASUREMENT_HEADING_RE.match(line):
            return None
        return hashes, number, title
    # Fall back to Chapter-N pattern detection.
    m_any = ANY_HEADING_RE.match(line)
    if m_any:
        hashes, body = m_any.groups()
        chap = _parse_chapter_heading(body)
        if chap:
            number, title = chap
            return hashes, number, title
    return None


def _parse_any_heading(line: str, min_level: int) -> tuple[str, str | None, str] | None:
    """Return `(hashes, number_or_None, title)` for any heading at depth ≥ min_level.

    Numbered headings (`# 2. CHAPTER`, `### 1.4. Foo`) are ALWAYS parsed
    regardless of `min_level`. The level filter only suppresses unnumbered
    headings — `# Title` at level 1 stays filtered when `min_level=2`,
    but `# 2. INSTALLATION` does not. Without this rule a chapter
    heading at the user's `min_level - 1` is invisible to the splitter,
    leaving its descendants as orphans with no breadcrumb ancestor.

    `Chapter N <title>` is also treated as numbered (synthetic number
    `N`), so an extracted `#### Chapter 1 <Title>` can serve as the
    parent of subsequent `#### 1.1 Foo` sections after
    LLM normalization promotes the chapter level.
    """
    m = ANY_HEADING_RE.match(line)
    if not m:
        return None
    hashes, body = m.groups()
    num_m = NUMBER_PREFIX_RE.match(body)
    if num_m:
        return hashes, num_m.group(1), num_m.group(2).strip()
    chap = _parse_chapter_heading(body)
    if chap:
        number, title = chap
        return hashes, number, title
    if len(hashes) < min_level:
        return None
    return hashes, None, body.strip()


@dataclass
class _Section:
    level: int
    number: str | None
    title: str
    heading_line: str
    content_lines: list[str] = field(default_factory=list)
    children: list[_Section] = field(default_factory=list)
    parent: _Section | None = None
    # numeric disambiguator appended to the on-disk filename when
    # two distinct sections share a sanitized name. First occurrence
    # leaves this empty; later occurrences get "-2", "-3", etc. Inserted
    # before the `.md` extension by `_section_output_path`. Does NOT
    # affect `display_name` — breadcrumbs still render the bare title.
    filename_suffix: str = ""
    # when `min_level` is set, headings at depth < min_level are
    # parsed as `_Section` objects so descendants can find them via
    # `_find_parent`, but they're excluded from file-writing and INDEX
    # (and rendered as plain-text in breadcrumbs). Preserves chapter
    # context for L2 sections under `min_level=2`.
    is_ancestor_only: bool = False

    @property
    def display_name(self) -> str:
        if self.number:
            return f"{self.number}. {self.title}"
        return self.title


@dataclass(frozen=True)
class _Collision:
    """One dropped section from a resolved on-disk path collision."""

    target_path: Path
    kept_title: str
    kept_body_chars: int
    dropped_title: str
    dropped_body_chars: int


def _build_heading_line(hashes: str, number: str | None, title: str) -> str:
    if number:
        return f"{hashes} {number}. {title}"
    return f"{hashes} {title}"


def _find_parent(section: _Section, sections: list[_Section]) -> _Section | None:
    """Find the parent of `section` from earlier sections.

    Multi-part numbered sections (e.g. `### 2.6.`) require a number-prefix
    ancestor (e.g. `# 2.` or `## 2.`). Without one, return None — falling
    back to level-based attribution would misattribute. Concrete failure:
    `## 2.5.` followed by `### 2.6.` (with no `# 2.` parent) would attach
    `2.6.` to `2.5.` via level-only matching, even though they're siblings.

    Single-part numbered headings (`### 1. Step One`) are chapter-rooted —
    they may legitimately live under a *semantic* (unnumbered) ancestor
    (`## Quick Start`), but must NOT level-fallback through an unrelated
    *numbered* ancestor. Concrete failure: a Brief-Contents block where
    `### Chapter 24 Title` is followed by `#### 1 Intro 31` would attach the
    level-4 chapter listing to Chapter 24 via level-only matching, producing
    a misleading breadcrumb.

    Unnumbered sections still fall back to plain level-only matching.
    """
    if section.number is not None:
        section_parts = section.number.split(".")
        for candidate in reversed(sections):
            if candidate.number is None:
                continue
            candidate_parts = candidate.number.split(".")
            if len(candidate_parts) != len(section_parts) - 1:
                continue
            if (
                section.number.startswith(candidate.number + ".")
                and candidate.level < section.level
            ):
                return candidate
        if len(section_parts) >= 2:
            # Multi-part numbered with no prefix ancestor: orphan, not
            # level-attached. Stops `### 2.6.` from latching onto `## 2.5.`.
            return None
        # Single-part numbered: skip numbered candidates during level
        # fallback. May still attach to a semantic (unnumbered) ancestor.
        for candidate in reversed(sections):
            if candidate.level < section.level and candidate.number is None:
                return candidate
        return None

    for candidate in reversed(sections):
        if candidate.level < section.level:
            return candidate
    return None


def _numbered_parse_is_representative(sections: list[_Section], lines: list[str]) -> bool:
    """True if the numbered-only parse actually represents the
    document's top-level structure.

    The default (`min_level=None`) parse only recognizes numbered
    headings. That's correct for docs with a real numbered outline
    where the numbered headings ARE the structure. But it silently
    fails on docs whose only "numbered" headings are deep-level false
    positives — e.g. a document whose real structure is non-numbered
    H1/H2, but which has a couple of deep headings like
    `#### 35 mm and 65 mm` / `#### 16 mm` (measurement labels) that
    `_parse_numbered_heading` misparses as sections "35" and "16". The
    numbered parse yields those spurious deep sections while the
    document's real H1/H2/H3 headings are dropped.

    Representativeness test: the parsed numbered sections must include
    at least one heading at the document's *shallowest* heading depth.
    If every numbered section is deeper than the shallowest heading in
    the document, the numbered parse has missed the entire top-level
    structure → not representative → caller should fall back to
    mixed-mode (non-numbered) parsing.

    An empty parse is trivially not representative — the zero-section
    case is the degenerate form of "zero sections at the document's
    top level".
    """
    if not sections:
        return False
    doc_shallowest = None
    for line in lines:
        m = ANY_HEADING_RE.match(line)
        if m:
            depth = len(m.group(1))
            if doc_shallowest is None or depth < doc_shallowest:
                doc_shallowest = depth
    if doc_shallowest is None:
        # No headings at all — nothing to be representative of.
        return False
    min_section_level = min(s.level for s in sections)
    return min_section_level <= doc_shallowest


def _detect_fallback_min_level(lines: list[str]) -> int | None:
    """Find the heading depth that is the document's real chapter level.

    Used by ``split_into_sections`` when default-mode parsing produces
    zero sections (no numbered headings in the document). The returned
    level becomes the ``min_level`` for a fallback parse pass, so
    non-numbered semantic hierarchies still produce section files.

    Base rule — "shallowest with ≥2": a doc title is typically a
    single H1 followed by multiple H2 chapters (flat-manual
    shape). Picking the shallowest depth that has a
    real sibling group identifies the chapter level. If every heading
    is at H1 with no siblings, returns 1 — single-chapter docs still
    get one section file.

    Sparse-shallow-group correction: the base rule accepts
    any depth with ≥2 headings, but a count of exactly 2 at a shallow
    depth is usually a doc title plus one stray promoted heading
    (a flat manual: ``{1: 2, 2: 10, 3: 19}`` — picking H1 buried
    10 chapters in 2 giant sections). When the candidate depth is a
    minimal pair (count ≤ ``FALLBACK_SPARSE_GROUP_MAX``) AND the next
    deeper present depth has a substantially larger sibling group
    (≥ ``FALLBACK_SPARSE_GROUP_RATIO`` × the candidate's count), the
    shallow level is chrome — advance to the larger group and re-test.
    Genuine large shallow groups (a non-numbered manual H1=28) and groups
    above the minimal-pair threshold (H2=17) are untouched.

    Returns None when the document has zero headings.
    """
    depth_counts: dict[int, int] = {}
    for line in lines:
        m = ANY_HEADING_RE.match(line)
        if not m:
            continue
        hashes = m.group(1)
        depth = len(hashes)
        depth_counts[depth] = depth_counts.get(depth, 0) + 1
    if not depth_counts:
        return None
    depths = sorted(depth_counts.keys())
    # Base rule: shallowest depth with ≥2 occurrences.
    candidate: int | None = next((d for d in depths if depth_counts[d] >= 2), None)
    if candidate is None:
        # No depth has ≥2 occurrences — fall back to the shallowest
        # depth with any heading (single-chapter doc).
        return min(depths)
    # Sparse-shallow-group correction: while the candidate is a minimal
    # pair sitting directly above a ≥RATIO×-larger group, the candidate
    # is chrome — advance to that larger group.
    while depth_counts[candidate] <= FALLBACK_SPARSE_GROUP_MAX:
        deeper = [d for d in depths if d > candidate]
        if not deeper:
            break
        nxt = deeper[0]
        if depth_counts[nxt] >= FALLBACK_SPARSE_GROUP_RATIO * depth_counts[candidate]:
            candidate = nxt
        else:
            break
    return candidate


def _parse_sections(lines: list[str], *, min_level: int | None) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None

    for line in lines:
        is_ancestor_only = False
        if min_level is None:
            parsed_num = _parse_numbered_heading(line)
            parsed: tuple[str, str | None, str] | None = parsed_num
        else:
            # also parse UNNUMBERED headings shallower than
            # min_level — those become "ancestor-only" sections that
            # don't get files written but DO appear in descendants'
            # parent chains (so breadcrumbs show the chapter context).
            # Numbered headings below min_level are ALREADY writable per
            # `_parse_any_heading`'s "numbered always parses" rule; they
            # get section files and are NOT ancestor-only.
            parsed = _parse_any_heading(line, min_level=1)
            if parsed:
                hashes, number, _title = parsed
                if number is None and len(hashes) < min_level:
                    is_ancestor_only = True

        if parsed:
            hashes, number, title = parsed
            section = _Section(
                level=len(hashes),
                number=number,
                title=title.strip(),
                heading_line=_build_heading_line(hashes, number, title.strip()),
                is_ancestor_only=is_ancestor_only,
            )
            parent = _find_parent(section, sections)
            if parent is not None:
                section.parent = parent
                parent.children.append(section)
            sections.append(section)
            current = section
            continue

        if current is not None:
            current.content_lines.append(line)

    return sections


def _is_page_anchor_line(line: str) -> bool:
    return bool(_PAGE_ANCHOR_LINE_RE.match(line))
