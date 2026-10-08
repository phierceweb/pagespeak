"""Heading-line parsing for the splitter: a heading's level, section number,
and title (`_parse_numbered_heading` / `_parse_any_heading` /
`_parse_chapter_heading`), plus the document numbering
(`_heading_numbering`) that decides whether a bare-integer prefix is a
section number at all.
"""

from __future__ import annotations

import re

NUMBERED_HEADING_RE = re.compile(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$")

MEASUREMENT_HEADING_RE = re.compile(r"^#{1,6}\s+\d+(?:\.\d+)?\s+[a-z]")

# Uppercase-initial unit symbols the lowercase-letter heuristic above can't see
# (`6.3 Hz`, `48 V`, `2.4 GHz`). Matched only as a standalone token (a trailing
# `[^A-Za-z]` boundary) so a Title-Case word starting with a unit letter
# (`Vacuum`, `Wireless`) is NOT mistaken for a measurement. Bare A/I/N/… are
# excluded on purpose — they collide with articles/section words.
_UPPER_UNITS = (
    "THz",
    "GHz",
    "MHz",
    "Hz",
    "Vpp",
    "Vrms",
    "VA",
    "V",
    "Wh",
    "Wb",
    "W",
    "MPa",
    "Pa",
    "Nm",
    "MΩ",
    "Ω",
    "Sv",
    "Gy",
    "Bq",
)
MEASUREMENT_UNIT_HEADING_RE = re.compile(
    r"^#{1,6}\s+[-+]?\d+(?:\.\d+)?\s+(?:" + "|".join(_UPPER_UNITS) + r")(?![A-Za-z])"
)

ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+?)$")

BARE_INTEGER_HEADING_RE = re.compile(r"^#{1,6}\s+(\d+)\s")

CHAPTER_TITLE_RE = re.compile(r"^Chapter\s+(\d+)(?:[\s.:]+(.+))?$", re.IGNORECASE)


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


def _heading_numbering(lines: list[str], fenced: list[bool]) -> frozenset[int]:
    """The integers a bare-integer heading prefix (`## 404 Handling`) may carry
    as a section number: one with a dotted child (`404.1`), or one next to an
    integer leading any heading number (403 / 405). Any other bare integer is
    title text.
    """
    leading: set[int] = set()
    with_children: set[int] = set()
    for line, in_fence in zip(lines, fenced, strict=True):
        parsed = None if in_fence else _parse_any_heading(line, min_level=1)
        if parsed is None or parsed[1] is None:
            continue
        head, _, rest = parsed[1].partition(".")
        leading.add(int(head))
        if rest:
            with_children.add(int(head))
    return frozenset(with_children | {n + step for n in leading for step in (-1, 1)})


def _is_section_number(line: str, numbering: frozenset[int] | None) -> bool:
    bare = BARE_INTEGER_HEADING_RE.match(line)
    return numbering is None or bare is None or int(bare.group(1)) in numbering


def _parse_numbered_heading(
    line: str, *, numbering: frozenset[int] | None = None
) -> tuple[str, str, str] | None:
    """Return `(hashes, number, title)` if this line is a numbered section heading.

    Heuristic: at heading level 2, require a `.` in the number. `## 1 Step`
    looks like a procedure step inside a section, not a real `## 1.4. TITLE`.
    With `numbering` (see `_heading_numbering`), a bare integer the document's
    numbering doesn't reach is not a section number either.

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
        # reject `<number> <unit>` measurement shapes (`35 mm`, `6.3 mm`,
        # `50 ohm`, `6.3 Hz`, `48 V`) — the number is a quantity, not a
        # section prefix. Two guards: lowercase-initial units, and a curated
        # word-boundaried whitelist for uppercase-initial ones.
        if MEASUREMENT_HEADING_RE.match(line) or MEASUREMENT_UNIT_HEADING_RE.match(line):
            return None
        if not _is_section_number(line, numbering):
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


def _parse_any_heading(
    line: str, min_level: int, *, numbering: frozenset[int] | None = None
) -> tuple[str, str | None, str] | None:
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
    # `## 6.3 mm stereo jack plug` is a spec label and `## 404 Handling` (with
    # nothing numbered 403/405/404.x) is a title, not a section number. Both
    # stay sections, unnumbered.
    is_measurement = bool(
        MEASUREMENT_HEADING_RE.match(line) or MEASUREMENT_UNIT_HEADING_RE.match(line)
    )
    if num_m and not is_measurement and _is_section_number(line, numbering):
        return hashes, num_m.group(1), num_m.group(2).strip()
    chap = _parse_chapter_heading(body)
    if chap:
        number, title = chap
        return hashes, number, title
    if len(hashes) < min_level:
        return None
    return hashes, None, body.strip()
