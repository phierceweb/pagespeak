"""Heuristic demote of Marker-promoted prose-shaped headings + TOC-entry
phantom-section detection.

Marker promotes lines that start with `N.` (and sometimes plain prose) to
headings. That's correct for genuine section headings but wrong for:

- Numbered bullets where each item is a full sentence:
    ### 1. This is a full sentence promoted to a heading. It continues
    with more prose across the line and reads as body text, not a heading.
- Figure / table captions promoted to headings:
    #### Figure 13.24 A labeled overview of the system.
- Sentence fragments from running text:
    ### If you're just getting started, here's how the parts fit together.
- front-matter TOC / chapter-end summary list items with page-number
  suffixes that duplicate real subsection content:
    #### 20.2. A Subsection Title, p. 596

This module exposes:
- `demote_prose_heading(line)` — runs in `cleanup_markdown` to demote
  prose-shaped headings back to list items / plain text.
- `is_toc_phantom_heading(text)` — used by the splitter to drop TOC-
  entry phantom sections before writing.
"""

from __future__ import annotations

import re

# `### 1.2.3. <title>` — the heading shapes promote_numbered_heading emits.
NUMBERED_HEADING_RE = re.compile(r"^(#+)\s+(\d+(?:\.\d+)*\.)\s+(.+?)\s*$")
# Any heading line: `### <title>`. Used as a fallback after the numbered
# regex misses, for the non-numbered prose-demote pass.
ANY_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")
# `Figure N` / `Figure N.NN` / `Fig. N` / `Table N` etc. — caption-shape
# prefixes that Marker promotes to headings. These are demoted
# regardless of length / punctuation when the title is non-trivial.
_CAPTION_PREFIX_RE = re.compile(r"^(?:Figure|Fig\.|Table|Tbl\.|Eq\.|Equation)\s+\d", re.IGNORECASE)

# Internal sentence boundary: `. ` followed by a capital letter. Catches
# real prose ("Closed. At rest...") without firing on abbreviations
# followed by lowercase ("e.g. foo"). Abbreviation-then-capital ("Inc. Foo")
# is a known false-positive corner case; real section titles almost never
# contain `Abbr. Word` shapes.
INTERNAL_SENTENCE_RE = re.compile(r"\. [A-Z]")

# Trim trailing-punctuation tolerance: a title can end in `?` / `!` / `.`
# if it's short. The threshold below decides "short".
SHORT_TERMINAL_OK_LEN = 40

# Hard length cap. Real section titles rarely exceed this.
MAX_TITLE_LEN = 120


def is_prose_shaped_title(title: str) -> bool:
    """Return True if `title` looks like a sentence, not a section name.

    Heuristics (any one fires → True):
      1. `len(title) > 120` — too long to be a section name.
      2. Internal `. <Capital>` boundary in all but the trailing 10 chars
         — a sentence ends mid-title.
      3. `len(title) > 40` AND ends in `.`, `?`, or `!` — long titles
         ending in terminal punctuation are sentences.
      4. First character is lowercase — section titles start with a
         capital; lowercase suggests a continuation.
    """
    title = title.strip()
    if not title:
        return False

    # 1. Length.
    if len(title) > MAX_TITLE_LEN:
        return True

    # 2. Internal sentence boundary, ignoring the trailing 10 chars (so a
    # legitimate abbreviation near the end like `... U.S. data` doesn't
    # fire).
    if len(title) > 10:
        body = title[:-10]
        if INTERNAL_SENTENCE_RE.search(body):
            return True

    # 3. Long title with terminal punctuation.
    if len(title) > SHORT_TERMINAL_OK_LEN and title[-1] in ".?!":
        return True

    # 4. Lowercase first char (continuation, not a real title).
    first = title[0]
    return bool(first.isalpha() and first.islower())


def demote_prose_heading(line: str) -> str:
    """Demote `### N. <prose>` back to `N. <prose>` list item.

    Three branches (in priority order):

    1. **Numbered prose** — `### 1. <prose-shaped title>` demotes to
       `1. <title>`, preserving the numeric prefix so the surrounding
       list renders correctly. Original behavior.
    2. **Caption-shape promote** — `### Figure 13.24 <caption>`
       and friends (`Fig.`, `Table`, `Eq.`) demote to plain prose.
       Marker promotes figure / table captions to `####`-headings; the
       splitter then creates section files for them. Always a noise
       shape, regardless of length.
    3. **Non-numbered prose** — `### <prose-shaped title>`
       (no number prefix, but the title's shape is sentence-like) demotes
       to plain prose. Catches Marker's promotion of inline sentences in
       running text. Stricter than the numbered case to avoid demoting
       legitimate long product-manual section titles.

    Returns `line` unchanged if no rule fires.
    """
    stripped = line.strip()
    if not stripped.startswith("#"):
        return line

    # Branch 1: numbered prose
    m = NUMBERED_HEADING_RE.match(stripped)
    if m:
        _, num, title = m.groups()
        if is_prose_shaped_title(title):
            return f"{num} {title}"
        return line

    # Branches 2 + 3 require a non-numbered heading
    m_any = ANY_HEADING_RE.match(stripped)
    if not m_any:
        return line
    _, title = m_any.groups()
    title = title.strip()

    # Branch 2: caption-shape promote
    if _CAPTION_PREFIX_RE.match(title):
        return title

    # Branch 3: non-numbered prose. Stricter than the numbered case —
    # require BOTH (a) length > 40 with terminal punctuation OR (b) an
    # internal `. <Capital>` boundary, AND (c) not all-caps (real
    # product-manual section titles like `INTRODUCTION` slip through
    # `is_prose_shaped_title`'s lowercase check but aren't prose).
    if title.isupper():
        return line
    has_terminal_punct = len(title) > 40 and title.endswith((".", "?", "!"))
    has_internal_sentence = len(title) > 10 and INTERNAL_SENTENCE_RE.search(title[:-10]) is not None
    if has_terminal_punct or has_internal_sentence:
        return title
    return line


# --- TOC-entry phantom heading detection ----------------------------
# Marker promotes front-matter TOC items into headings when shaped like a
# numbered title + trailing page number (`20.2. Title, p. 596`,
# `Chapter 1 Title 31`). These duplicate real subsection content; the
# splitter's `is_toc_phantom_heading` drops them. Mirrors
# `_heading_normalize._is_structural_heading` to keep the LLM-pass and
# split-time filters in sync (kept local to avoid a cross-module import).

_TOC_CHAPTER_PREFIX_RE = re.compile(r"^Chapter\s+\d+\b", re.IGNORECASE)
# Multi-part numbered (1.1, 1.1.1, ...) only — bare `\d+` would
# false-positive on `Chapter 14` (no subtitle), where the splitter
# emits the display name `14. Chapter 14`.
_TOC_NUMBERED_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)+\b")
# Bare numbered (1., 14.) followed by a real title — separate branch
# below to handle the `Chapter N` no-subtitle false-positive.
_TOC_BARE_NUMBERED_PREFIX_RE = re.compile(r"^(\d+)\.\s+(.+)$")
_TOC_PAGE_SUFFIX_RE = re.compile(r"\bp\.\s*\d+\s*$", re.IGNORECASE)
_TOC_TRAILING_PAGE_NUMBER_RE = re.compile(r"\b\d{2,}\s*$")


def is_toc_phantom_heading(text: str) -> bool:
    """True if `text` looks like a TOC-entry promote, not real content.

    Three matching shapes:

    1. Title ends with `, p. NN` (or `p. NN` after whitespace) — direct
       front-matter / back-matter TOC entry. Strong signal regardless
       of any prefix.
    2. `Chapter N <title> <NN>` — a chapter-prefixed heading whose
       trailing 2-3-digit number is a page reference. The Marker
       chapter-promote pattern.
    3. `<N.M[.O]> <title> <NN>` — a multi-part-numbered subsection
       heading with a trailing page number.

    Bare numerics without a Chapter/numbered prefix (e.g. `RFC 822`,
    `IEEE 802.11`, `Section 100`) are NOT flagged — they could be real
    titles, and we don't have the context to disambiguate. The
    real-section twin is what we want to keep.
    """
    text = text.strip()
    if not text:
        return False
    # Rule 1: trailing `, p. NN`
    if _TOC_PAGE_SUFFIX_RE.search(text):
        return True
    # Rule 2: Chapter-prefixed with trailing page number
    chap = _TOC_CHAPTER_PREFIX_RE.match(text)
    if chap:
        rest = text[chap.end() :].strip()
        if rest and _TOC_TRAILING_PAGE_NUMBER_RE.search(rest):
            return True
    # Rule 3: multi-part numbered prefix with trailing page number
    num = _TOC_NUMBERED_PREFIX_RE.match(text)
    if num:
        rest = text[num.end() :].strip()
        if rest and _TOC_TRAILING_PAGE_NUMBER_RE.search(rest):
            return True
    # Rule 4: bare numbered prefix (`14. <title> NN`). Skip when the
    # title repeats the chapter form ("Chapter NN") — that's the
    # splitter's no-subtitle fallback display name (`14. Chapter 14`),
    # not a TOC entry.
    bare = _TOC_BARE_NUMBERED_PREFIX_RE.match(text)
    if bare:
        rest = bare.group(2).strip()
        # False-positive guard: `14. Chapter 14` has rest = "Chapter 14",
        # which matches the trailing-page-number rule. Skip when rest
        # is `Chapter <same-num>` — that's the splitter's no-subtitle
        # fallback display name, not a TOC entry.
        if (
            rest
            and _TOC_TRAILING_PAGE_NUMBER_RE.search(rest)
            and not _is_chapter_n_fallback_rest(bare.group(1), rest)
        ):
            return True
    return False


def _is_chapter_n_fallback_rest(num_str: str, rest: str) -> bool:
    """Detect the splitter's no-subtitle Chapter-N fallback display
    name shape: a heading `## Chapter 14` with no further title parses
    as `(number=14, title="Chapter 14")` → display_name `14. Chapter 14`.
    The trailing `14` is NOT a page number; it's the chapter number
    repeated. Don't treat as TOC."""
    return bool(re.match(rf"^Chapter\s+{re.escape(num_str)}\s*$", rest, re.IGNORECASE))
